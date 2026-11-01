"""Copia de seguridad diaria de la base de datos, en data/copias/ (y, si se quiere, por Telegram).

Se hace con la copia "en caliente" de SQLite, así que no hace falta parar la app. Cada copia se
comprime con gzip y se guardan las de los últimos COPIA_DIAS días.
"""
from datetime import datetime
import gzip
import logging
import os
import shutil
import sqlite3
import threading
import time

import requests

import db

log = logging.getLogger(__name__)

INTERVALO = 15 * 60  # segundos entre comprobaciones
PREFIJO = 'tareas-'
EXTENSION = '.sqlite3.gz'


def carpeta():
    return db.DB_PATH.parent / 'copias'


def _hora():
    try:
        return int(os.getenv('COPIA_HORA', '4'))
    except ValueError:
        return 4


def _dias():
    try:
        return max(1, int(os.getenv('COPIA_DIAS', '14')))
    except ValueError:
        return 14


def _ruta(dia):
    return carpeta() / f'{PREFIJO}{dia:%Y-%m-%d}{EXTENSION}'


def hacer_copia(dia=None):
    """Copia la base de datos a data/copias/tareas-AAAA-MM-DD.sqlite3.gz y devuelve la ruta."""
    dia = dia or datetime.now().date()
    carpeta().mkdir(parents=True, exist_ok=True)
    destino = _ruta(dia)
    temporal = destino.with_name(destino.name + '.tmp')
    sin_comprimir = carpeta() / 'copia_en_curso.sqlite3'

    origen = sqlite3.connect(db.DB_PATH)
    copia = sqlite3.connect(sin_comprimir)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()
    try:
        with open(sin_comprimir, 'rb') as entrada, gzip.open(temporal, 'wb') as salida:
            shutil.copyfileobj(entrada, salida)
        temporal.replace(destino)  # así nunca queda a medias una copia con el nombre bueno
    finally:
        sin_comprimir.unlink(missing_ok=True)
        temporal.unlink(missing_ok=True)
    return destino


def limpiar():
    """Borra las copias más antiguas, dejando las COPIA_DIAS más recientes."""
    copias = sorted(carpeta().glob(f'{PREFIJO}*{EXTENSION}'))
    for vieja in copias[:-_dias()]:
        vieja.unlink(missing_ok=True)
    return copias[-_dias():]


def _chat_telegram():
    """El primer id numérico de TELEGRAM_ALLOWED_USERS (los @usuarios no sirven para enviar)."""
    for usuario in os.getenv('TELEGRAM_ALLOWED_USERS', '').split(','):
        if usuario.strip().isdigit():
            return usuario.strip()
    return None


def enviar_por_telegram(ruta):
    chat = _chat_telegram()
    if not (os.getenv('TELEGRAM_TOKEN') and chat):
        log.warning('COPIA_TELEGRAM activado pero falta TELEGRAM_TOKEN o un id numérico en TELEGRAM_ALLOWED_USERS')
        return False
    url = f'https://api.telegram.org/bot{os.getenv("TELEGRAM_TOKEN")}/sendDocument'
    with open(ruta, 'rb') as archivo:
        respuesta = requests.post(url, data={'chat_id': chat, 'disable_notification': 'true',
                                             'caption': f'💾 Copia de seguridad del {ruta.name[len(PREFIJO):][:10]}'},
                                  files={'document': (ruta.name, archivo)}, timeout=60)
    if not respuesta.ok:
        log.warning('No se pudo enviar la copia por Telegram: %s', respuesta.text[:200])
    return respuesta.ok


def comprobar(ahora=None):
    """Hace la copia de hoy si ya es la hora y aún no existe. Devuelve la ruta si la ha hecho."""
    ahora = ahora or datetime.now()
    if ahora.hour < _hora() or _ruta(ahora.date()).exists():
        return None
    ruta = hacer_copia(ahora.date())
    limpiar()
    log.info('Copia de seguridad hecha: %s (%d KB)', ruta.name, ruta.stat().st_size // 1024)
    if os.getenv('COPIA_TELEGRAM', 'false').lower() == 'true':
        enviar_por_telegram(ruta)
    return ruta


def _bucle():
    while True:
        try:
            comprobar()
        except Exception:
            log.exception('Error haciendo la copia de seguridad')
        time.sleep(INTERVALO)


def arrancar_en_segundo_plano():
    threading.Thread(target=_bucle, name='copias', daemon=True).start()
