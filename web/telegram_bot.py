"""Bot de Telegram conectado al mismo asistente que WhatsApp.

Usa long polling: el servidor pregunta a Telegram por mensajes nuevos, así que no hace falta
abrir puertos, dominio ni HTTPS. Se arranca en un hilo desde app.py si hay TELEGRAM_TOKEN.
"""
import logging
import os
import threading
import time

import requests

import asistente

log = logging.getLogger(__name__)

LIMITE_TELEGRAM = 4096

# Comandos del menú de Telegram, traducidos a frases que entiende el motor de reglas
COMANDOS = {
    '/start': ('ayuda', 'Cómo usar el bot'),
    '/ayuda': ('ayuda', 'Ejemplos de lo que entiendo'),
    '/hoy': ('qué tengo hoy', 'Tareas para hoy y atrasadas'),
    '/semana': ('qué tengo esta semana', 'Tareas de esta semana'),
    '/tareas': ('tareas', 'Todas las pendientes'),
    '/sinfecha': ('tareas sin fecha', 'Tareas sin fecha límite'),
    '/atrasadas': ('tareas atrasadas', 'Tareas con la fecha pasada'),
    '/recordatorios': ('mis recordatorios', 'Recordatorios pendientes'),
    '/deshacer': ('deshaz', 'Deshacer lo último que hice'),
}


def _api(metodo, espera_http=15, **datos):
    url = f'https://api.telegram.org/bot{os.getenv("TELEGRAM_TOKEN")}/{metodo}'
    respuesta = requests.post(url, json=datos, timeout=espera_http)
    cuerpo = respuesta.json()
    if not cuerpo.get('ok'):
        raise RuntimeError(f'Telegram {metodo}: {cuerpo.get("description")}')
    return cuerpo['result']


def _usuarios_permitidos():
    valor = os.getenv('TELEGRAM_ALLOWED_USERS', '')
    return {u.strip().lstrip('@').lower() for u in valor.split(',') if u.strip()}


def _autorizado(usuario):
    permitidos = _usuarios_permitidos()
    return str(usuario.get('id')) in permitidos or (usuario.get('username') or '').lower() in permitidos


def enviar_mensaje(chat_id, texto):
    for inicio in range(0, len(texto), LIMITE_TELEGRAM):
        trozo = texto[inicio:inicio + LIMITE_TELEGRAM]
        try:
            # Las respuestas usan *negrita* al estilo WhatsApp, que coincide con el Markdown de Telegram
            _api('sendMessage', chat_id=chat_id, text=trozo, parse_mode='Markdown')
        except RuntimeError:
            # Un "_" o "*" suelto en el nombre de una tarea rompe el Markdown: se reenvía en texto plano
            _api('sendMessage', chat_id=chat_id, text=trozo)


def _texto_de(mensaje):
    texto = (mensaje.get('text') or '').strip()
    comando = texto.split()[0].split('@')[0].lower() if texto.startswith('/') else ''
    if comando in COMANDOS:
        return COMANDOS[comando][0]
    return texto


MAX_AUDIO_BYTES = 20 * 1024 * 1024  # límite de descarga de la Bot API


def _responder_audio(chat_id, nota):
    if (nota.get('file_size') or 0) > MAX_AUDIO_BYTES:
        return 'Ese audio es demasiado largo 🙉 Mándamelo en trozos más cortos.'
    _api('sendChatAction', chat_id=chat_id, action='typing')  # "escribiendo..." mientras se transcribe
    archivo = _api('getFile', file_id=nota['file_id'])
    url = f'https://api.telegram.org/file/bot{os.getenv("TELEGRAM_TOKEN")}/{archivo["file_path"]}'
    descarga = requests.get(url, timeout=60)
    descarga.raise_for_status()
    return asistente.responder_audio(f'tg:{chat_id}', descarga.content)


def _procesar(update):
    mensaje = update.get('message') or update.get('edited_message')
    if not mensaje:
        return

    chat_id = mensaje['chat']['id']
    usuario = mensaje.get('from', {})

    if not _autorizado(usuario):
        log.warning('Mensaje de Telegram de un usuario no autorizado: %s', usuario)
        # Le decimos su id para que el dueño pueda añadirlo a TELEGRAM_ALLOWED_USERS si quiere
        enviar_mensaje(chat_id, f'No estás autorizado para usar este bot. Tu id de Telegram es {usuario.get("id")}.')
        return

    texto = _texto_de(mensaje)
    nota_de_voz = mensaje.get('voice') or mensaje.get('audio')
    if not texto and not nota_de_voz:
        enviar_mensaje(chat_id, 'Entiendo mensajes de texto y notas de voz ✍️🎙️')
        return

    try:
        if nota_de_voz:
            respuesta = _responder_audio(chat_id, nota_de_voz)
        else:
            respuesta = asistente.responder(f'tg:{chat_id}', texto)
    except Exception:
        log.exception('Error generando la respuesta')
        respuesta = 'Ha habido un error procesando tu mensaje. Inténtalo de nuevo en un momento.'
    enviar_mensaje(chat_id, respuesta)


def escuchar():
    """Bucle de long polling. No termina nunca; los errores de red se reintentan."""
    try:
        _api('setMyCommands', commands=[{'command': c[1:], 'description': d} for c, (_, d) in COMANDOS.items()])
    except (requests.RequestException, RuntimeError) as error:
        log.warning('No se pudo registrar el menú de comandos: %s', error)

    log.info('Bot de Telegram escuchando')
    siguiente = None
    espera = 1
    while True:
        try:
            # Telegram mantiene la petición abierta hasta 50 s si no hay mensajes nuevos
            updates = _api('getUpdates', espera_http=60, offset=siguiente, timeout=50,
                           allowed_updates=['message', 'edited_message'])
            espera = 1
        except (requests.RequestException, RuntimeError, ValueError) as error:
            log.warning('Error consultando Telegram (reintento en %ss): %s', espera, error)
            time.sleep(espera)
            espera = min(espera * 2, 60)
            continue

        for update in updates:
            siguiente = update['update_id'] + 1
            try:
                _procesar(update)
            except Exception:
                log.exception('Error procesando un mensaje de Telegram')


def arrancar_en_segundo_plano():
    if not os.getenv('TELEGRAM_TOKEN'):
        log.info('Sin TELEGRAM_TOKEN: el bot de Telegram no se arranca')
        return
    threading.Thread(target=escuchar, name='telegram', daemon=True).start()
