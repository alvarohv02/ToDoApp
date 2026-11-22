"""Envía los recordatorios cuando llega su hora, por Telegram o por WhatsApp."""
from datetime import datetime, timedelta, timezone
import logging
import os
import threading
import time

import requests

import db
import telegram_bot
import usuarios
import whatsapp

log = logging.getLogger(__name__)

INTERVALO = 20  # segundos entre comprobaciones
MAX_INTENTOS = 3
VENTANA_WHATSAPP = timedelta(hours=24)


def _texto_aviso(recordatorio, ahora):
    cuando = datetime.strptime(recordatorio['cuando'], '%Y-%m-%d %H:%M')
    texto = f'⏰ *Recordatorio*\n{recordatorio["texto"]}'
    if ahora - cuando > timedelta(minutes=10):
        # El servidor estuvo apagado o reiniciándose a la hora del aviso
        texto += f'\n\n_(con retraso: era para el {cuando:%d/%m} a las {cuando:%H:%M})_'
    return texto


def ventana_hasta(telefono):
    """Hasta cuándo (hora local) se le puede escribir por WhatsApp sin plantilla, o None si nunca escribió."""
    ultimo = db.ultimo_mensaje_usuario(telefono)  # en UTC, lo escribe SQLite
    if not ultimo:
        return None
    momento = datetime.strptime(ultimo, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).astimezone()
    return momento.replace(tzinfo=None) + VENTANA_WHATSAPP


def _dentro_de_ventana(telefono):
    ultimo = db.ultimo_mensaje_usuario(telefono)  # en UTC, lo escribe SQLite
    if not ultimo:
        return False
    return datetime.utcnow() - datetime.strptime(ultimo, '%Y-%m-%d %H:%M:%S') < VENTANA_WHATSAPP


def _enviar_whatsapp(telefono, recordatorio, texto):
    if _dentro_de_ventana(telefono):
        return whatsapp.enviar_mensaje(telefono, texto)

    plantilla = os.getenv('WHATSAPP_REMINDER_TEMPLATE')
    if plantilla:
        idioma = os.getenv('WHATSAPP_REMINDER_TEMPLATE_LANG', 'es')
        return whatsapp.enviar_plantilla(telefono, plantilla, idioma, [recordatorio['texto']])

    log.warning('Recordatorio %s sin enviar: fuera de la ventana de 24 h de WhatsApp y sin plantilla',
                recordatorio['id'])
    return False


def _enviar(recordatorio, ahora):
    texto = _texto_aviso(recordatorio, ahora)
    grupo = db.obtener_grupo(recordatorio['grupo_id']) if recordatorio.get('grupo_id') else None
    if grupo and 'recordatorios' in grupo['comparte']:
        texto += f'\n_👨‍👩‍👧 {grupo["nombre"]}_'
        # Al resto del grupo solo en el primer intento: si falla el envío principal y se reintenta,
        # los demás no lo reciben repetido
        if not recordatorio.get('intentos'):
            _avisar_al_grupo(grupo, recordatorio, texto)
    return _enviar_a(recordatorio['destino'], recordatorio, texto)


def _avisar_al_grupo(grupo, recordatorio, texto):
    """Manda el recordatorio a los demás miembros del grupo, a cada uno por su chat (Telegram si lo tiene)."""
    dueno = db.usuario_por_chat(recordatorio['destino'])
    ya_avisados = {recordatorio['destino']}
    for miembro in db.miembros_de(grupo['id']):
        if dueno and miembro['id'] == dueno['id']:
            continue
        chats = usuarios.chats_de(db.obtener_usuario(miembro['id']))
        chat = next((c for c in chats if c.startswith('tg:')), chats[0] if chats else None)
        if not chat or chat in ya_avisados:
            continue
        ya_avisados.add(chat)
        try:
            if not _enviar_a(chat, recordatorio, texto):
                log.warning('Recordatorio %s sin entregar a un miembro del grupo', recordatorio['id'])
        except (requests.RequestException, RuntimeError) as error:
            log.warning('Error enviando el recordatorio %s a un miembro del grupo: %s', recordatorio['id'], error)


def _enviar_a(destino, recordatorio, texto):
    if destino.startswith('tg:'):
        telegram_bot.enviar_mensaje(int(destino[3:]), texto)
        return True
    return _enviar_whatsapp(destino, recordatorio, texto)


def revisar(ahora=None):
    """Envía los recordatorios vencidos. Devuelve cuántos se han enviado."""
    ahora = ahora or datetime.now()
    enviados = 0
    for recordatorio in db.recordatorios_vencidos(ahora):
        try:
            ok = _enviar(recordatorio, ahora)
        except (requests.RequestException, RuntimeError) as error:
            log.warning('Error enviando el recordatorio %s: %s', recordatorio['id'], error)
            ok = False

        if ok:
            db.actualizar_recordatorio(recordatorio['id'], 'enviado')
            enviados += 1
        else:
            intentos = recordatorio['intentos'] + 1
            estado = 'error' if intentos >= MAX_INTENTOS else 'pendiente'
            db.actualizar_recordatorio(recordatorio['id'], estado, intentos)
    return enviados


def _bucle():
    log.info('Programador de recordatorios en marcha')
    while True:
        try:
            revisar()
        except Exception:
            log.exception('Error revisando recordatorios')
        time.sleep(INTERVALO)


def arrancar_en_segundo_plano():
    threading.Thread(target=_bucle, name='avisos', daemon=True).start()
