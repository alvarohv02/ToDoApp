"""Resumen de buenos días: lo que hay ese día, enviado solo a una hora fija.

Por defecto a las 8:00 de lunes a viernes y a las 10:00 los fines de semana, por WhatsApp si se
puede (has escrito al bot en las últimas 24 h) y si no por Telegram.
Si el servidor estaba apagado a esa hora, se envía al arrancar (hasta MARGEN después).
"""
from datetime import datetime, timedelta
import logging
import os
import threading
import time

import asistente
import avisos
import db
import telegram_bot
import whatsapp

log = logging.getLogger(__name__)

INTERVALO = 30  # segundos entre comprobaciones
MARGEN = timedelta(hours=3)  # pasado este tiempo ya no tiene sentido mandarlo
AJUSTE = 'resumen_enviado'


def _hora(dia):
    """Hora del resumen ese día: RESUMEN_HORA_LABORABLE (lunes a viernes) o RESUMEN_HORA_FINDE."""
    valor = os.getenv('RESUMEN_HORA_FINDE', '10:00') if dia.weekday() >= 5 else os.getenv('RESUMEN_HORA_LABORABLE', '08:00')
    try:
        return datetime.strptime(valor.strip(), '%H:%M').time()
    except ValueError:
        log.warning('Hora de resumen no válida: %r (usa HH:MM)', valor)
        return datetime.strptime('10:00' if dia.weekday() >= 5 else '08:00', '%H:%M').time()


def destinos():
    """A quién se envía: una lista de personas, cada una con sus chats por orden de preferencia.

    RESUMEN_DESTINOS usa el formato de CUENTAS_VINCULADAS: personas separadas por ';' y chats por ','
    ("34600111222,tg:123456789"). Si está vacío: tu WhatsApp (el primero de WHATSAPP_ALLOWED_NUMBERS)
    y, si no se puede, tu Telegram (el primer id numérico de TELEGRAM_ALLOWED_USERS).
    """
    configurados = [[c.strip() for c in grupo.split(',') if c.strip()]
                    for grupo in os.getenv('RESUMEN_DESTINOS', '').split(';')]
    configurados = [grupo for grupo in configurados if grupo]
    if configurados:
        return configurados
    chats = [n.strip() for n in os.getenv('WHATSAPP_ALLOWED_NUMBERS', '').split(',') if n.strip()][:1]
    chats += [f'tg:{u.strip()}' for u in os.getenv('TELEGRAM_ALLOWED_USERS', '').split(',') if u.strip().isdigit()][:1]
    return [chats] if chats else []


def _enviar(destino, texto):
    if destino.startswith('tg:'):
        telegram_bot.enviar_mensaje(int(destino[3:]), texto)
        return True
    # WhatsApp solo deja escribir primero si has hablado con el bot en las últimas 24 h
    if avisos._dentro_de_ventana(destino):
        return whatsapp.enviar_mensaje(destino, texto)
    log.info('Resumen no enviado por WhatsApp a %s: más de 24 h sin escribir al bot', destino)
    return False


def _enviar_a_alguno(chats, texto):
    """Prueba los chats en orden (WhatsApp antes que Telegram) y para en el primero que funciona."""
    for chat in chats:
        try:
            if _enviar(chat, texto):
                return chat
        except Exception:
            log.exception('Error enviando el resumen a %s', chat)
    return None


def comprobar(ahora=None):
    """Envía el resumen de hoy si ya es la hora y aún no se ha enviado. Devuelve a quién se ha enviado."""
    if os.getenv('RESUMEN_DIARIO', 'true').lower() == 'false':
        return []
    ahora = ahora or datetime.now()
    hoy = ahora.date()
    momento = datetime.combine(hoy, _hora(hoy))
    if not momento <= ahora < momento + MARGEN or db.leer_ajuste(AJUSTE) == hoy.isoformat():
        return []

    # Se apunta antes de enviar: si un envío falla no se reintenta cada 30 segundos durante horas
    db.guardar_ajuste(AJUSTE, hoy.isoformat())
    enviados = []
    for chats in destinos():
        enviado = _enviar_a_alguno(chats, asistente.resumen_del_dia(chats[0], hoy))
        if enviado:
            enviados.append(enviado)
        else:
            log.warning('No se pudo enviar el resumen por ninguno de: %s', ', '.join(chats))
    log.info('Resumen del día enviado a: %s', ', '.join(enviados) or 'nadie')
    return enviados


def _bucle():
    while True:
        try:
            comprobar()
        except Exception:
            log.exception('Error con el resumen del día')
        time.sleep(INTERVALO)


def arrancar_en_segundo_plano():
    threading.Thread(target=_bucle, name='resumen', daemon=True).start()
