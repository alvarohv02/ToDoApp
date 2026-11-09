"""Webhook de WhatsApp Cloud API (Meta) conectado al asistente."""
import hashlib
import hmac
import logging
import os
import re
import threading

import requests
from flask import Blueprint, Response, abort, request

import asistente
import db

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

whatsapp_bp = Blueprint('whatsapp', __name__)

LIMITE_WHATSAPP = 4096  # caracteres máximos por mensaje de texto


def _config(nombre, defecto=None):
    return os.getenv(nombre, defecto)


def _numeros_permitidos():
    valor = _config('WHATSAPP_ALLOWED_NUMBERS') or _config('WHATSAPP_TO') or ''
    return {n.strip().lstrip('+') for n in valor.split(',') if n.strip()}


def _firma_valida(cuerpo, cabecera):
    """Comprueba la cabecera X-Hub-Signature-256 si hay APP_SECRET configurado."""
    secreto = _config('WHATSAPP_APP_SECRET')
    if not secreto:
        return True
    esperado = 'sha256=' + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecera or '')


def _enviar(cuerpo):
    version = _config('WHATSAPP_API_VERSION', 'v23.0')
    url = f'https://graph.facebook.com/{version}/{_config("WHATSAPP_PHONE_NUMBER_ID")}/messages'
    respuesta = requests.post(
        url,
        headers={'Authorization': f'Bearer {_config("TOKEN")}'},
        json={'messaging_product': 'whatsapp', **cuerpo},
        timeout=15,
    )
    if not respuesta.ok:
        log.error('Error enviando WhatsApp (%s): %s', respuesta.status_code, respuesta.text)
    return respuesta.ok


def enviar_mensaje(telefono, texto):
    """Mensaje de texto libre. Solo funciona en las 24 h siguientes al último mensaje del usuario."""
    for inicio in range(0, len(texto), LIMITE_WHATSAPP):
        if not _enviar({'to': telefono, 'type': 'text', 'text': {'body': texto[inicio:inicio + LIMITE_WHATSAPP]}}):
            return False
    return True


def enviar_plantilla(telefono, nombre, idioma, parametros):
    """Mensaje con una plantilla aprobada por Meta: se puede enviar en cualquier momento."""
    return _enviar({
        'to': telefono,
        'type': 'template',
        'template': {
            'name': nombre,
            'language': {'code': idioma},
            'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': p} for p in parametros]}],
        },
    })


def _procesar(telefono, texto):
    try:
        respuesta = asistente.responder(telefono, texto)
    except Exception:
        log.exception('Error generando la respuesta')
        respuesta = 'Ha habido un error procesando tu mensaje. Inténtalo de nuevo en un momento.'
    enviar_mensaje(telefono, respuesta)


def _descargar_media(media_id):
    """Los audios de WhatsApp se descargan en dos pasos: id -> URL temporal -> contenido."""
    version = _config('WHATSAPP_API_VERSION', 'v23.0')
    cabeceras = {'Authorization': f'Bearer {_config("TOKEN")}'}
    info = requests.get(f'https://graph.facebook.com/{version}/{media_id}', headers=cabeceras, timeout=15)
    info.raise_for_status()
    contenido = requests.get(info.json()['url'], headers=cabeceras, timeout=60)
    contenido.raise_for_status()
    return contenido.content


def _procesar_audio(telefono, media_id):
    try:
        respuesta = asistente.responder_audio(telefono, _descargar_media(media_id))
    except Exception:
        log.exception('Error procesando un audio de WhatsApp')
        respuesta = 'No he podido procesar el audio. Inténtalo de nuevo o escríbemelo.'
    enviar_mensaje(telefono, respuesta)


@whatsapp_bp.route('/webhook/', methods=['GET'])
def verificar_webhook():
    # Meta llama aquí una vez al configurar el webhook en el panel de desarrolladores
    esperado = _config('WHATSAPP_VERIFY_TOKEN') or ''
    recibido = request.args.get('hub.verify_token') or ''
    # Sin token configurado no se acepta nada (antes, None == None daba por buena cualquier petición)
    if not (esperado and request.args.get('hub.mode') == 'subscribe'
            and hmac.compare_digest(recibido.encode(), esperado.encode())):
        return Response('Error de autentificacion.', status=403, mimetype='text/plain')

    # Meta manda un número: se devuelve solo si lo parece, y como texto plano (nunca como HTML)
    reto = request.args.get('hub.challenge', '')
    if not re.fullmatch(r'[0-9A-Za-z_-]{1,128}', reto):
        return Response('Reto no válido.', status=400, mimetype='text/plain')
    respuesta = Response(reto, mimetype='text/plain')
    respuesta.headers['X-Content-Type-Options'] = 'nosniff'
    return respuesta


@whatsapp_bp.route('/webhook/', methods=['POST'])
def recibir_mensaje():
    if not _firma_valida(request.get_data(), request.headers.get('X-Hub-Signature-256')):
        abort(403)

    data = request.get_json(silent=True) or {}
    permitidos = _numeros_permitidos()

    for entry in data.get('entry', []):
        for change in entry.get('changes', []):
            # Los avisos de estado (enviado/leído) llegan sin 'messages'
            for mensaje in change.get('value', {}).get('messages', []):
                telefono = mensaje.get('from', '')

                # Sin lista de números autorizados no atendemos a nadie: el bot puede borrar tareas
                if telefono not in permitidos:
                    log.warning('Mensaje ignorado de un número no autorizado: %s', telefono)
                    continue

                if not db.marcar_procesado(mensaje.get('id', '')):
                    continue  # reintento de Meta de un mensaje ya atendido

                if mensaje.get('type') == 'audio':
                    threading.Thread(
                        target=_procesar_audio,
                        args=(telefono, mensaje['audio']['id']),
                        daemon=True,
                    ).start()
                    continue

                if mensaje.get('type') != 'text':
                    threading.Thread(
                        target=enviar_mensaje,
                        args=(telefono, 'Entiendo mensajes de texto y notas de voz ✍️🎙️'),
                        daemon=True,
                    ).start()
                    continue

                # Respondemos 200 enseguida y procesamos en segundo plano: si Meta no recibe
                # respuesta rápido, reenvía el webhook
                threading.Thread(
                    target=_procesar,
                    args=(telefono, mensaje['text']['body']),
                    daemon=True,
                ).start()

    return {'status': 'success'}, 200
