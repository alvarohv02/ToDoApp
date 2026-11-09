"""Correo por IMAP (Gmail, universidad, trabajo...): ver los no leídos y ordenarlos.

Cada cuenta se configura en el .env (ver .env.example): CORREO_CUENTAS=personal,uni y, por cada una,
CORREO_PERSONAL_USUARIO, CORREO_PERSONAL_CLAVE (contraseña de aplicación) y, si no es Gmail,
CORREO_PERSONAL_SERVIDOR. Cada CORREO_MINUTOS se miran los no leídos de la bandeja de entrada (solo
las cabeceras, sin marcarlos como leídos); abrir, marcar como leído, archivar o borrar se hace al momento.
"""
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
import imaplib
import logging
import os
import re
import socket
import ssl
import threading
import time

from db import DatosNoValidos

log = logging.getLogger(__name__)

MAX_POR_CUENTA = 50  # no leídos que se guardan de cada cuenta (los más recientes)
MAX_TEXTO = 20000  # caracteres del cuerpo que se muestran al abrir un correo
ACCIONES = ('leido', 'archivar', 'borrar')

# imaplib no conoce MOVE (RFC 6851), aunque Gmail y casi todos los servidores lo admiten
imaplib.Commands.setdefault('MOVE', ('SELECTED',))

estado = {}  # id de cuenta -> {'correos': [...], 'no_leidos': n, 'error': str|None, 'actualizado': iso}
_cerrojo = threading.Lock()


# --- Cuentas -----------------------------------------------------------------------------

def cuentas():
    """Cuentas configuradas en el .env (con la contraseña: no sacar de este módulo)."""
    lista = []
    for ident in (c.strip().lower() for c in os.getenv('CORREO_CUENTAS', '').split(',')):
        if not ident:
            continue
        clave = f'CORREO_{ident.upper()}_'
        usuario = os.getenv(clave + 'USUARIO', '').strip()
        servidor = os.getenv(clave + 'SERVIDOR', '').strip()
        if not servidor and usuario.lower().endswith(('@gmail.com', '@googlemail.com')):
            servidor = 'imap.gmail.com'
        lista.append({
            'id': ident,
            'nombre': os.getenv(clave + 'NOMBRE', '').strip() or ident.capitalize(),
            'usuario': usuario,
            'clave': os.getenv(clave + 'CLAVE', '').replace(' ', ''),  # Google la muestra en grupos de 4
            'servidor': servidor,
            # Opcional: conectar a esta IP (p. ej. la del servidor de correo en la red de casa) en vez de
            # a la que dé el DNS; el certificado se sigue comprobando con el nombre de SERVIDOR
            'ip': os.getenv(clave + 'IP', '').strip(),
            'puerto': int(os.getenv(clave + 'PUERTO', '993') or 993),
        })
    return lista


def configurado():
    return bool(cuentas())


def _cuenta(ident):
    cuenta = next((c for c in cuentas() if c['id'] == ident), None)
    if cuenta is None:
        raise DatosNoValidos('Esa cuenta de correo no existe')
    return cuenta


class _IMAPPorIP(imaplib.IMAP4_SSL):
    """Conecta a una IP (la del servidor en la red de casa) comprobando el certificado con su nombre."""

    def __init__(self, ip, nombre, puerto, ssl_context, timeout):
        self._nombre = nombre
        super().__init__(ip, puerto, ssl_context=ssl_context, timeout=timeout)

    def _create_socket(self, timeout):
        return self.ssl_context.wrap_socket(socket.create_connection((self.host, self.port), timeout),
                                            server_hostname=self._nombre)


def _conectar(cuenta):
    if not (cuenta['usuario'] and cuenta['clave'] and cuenta['servidor']):
        raise DatosNoValidos('Falta el usuario, la contraseña o el servidor en el .env')
    # Siempre se comprueba el certificado (imaplib, por defecto, no lo hace)
    contexto = ssl.create_default_context()
    if cuenta['ip']:
        conexion = _IMAPPorIP(cuenta['ip'], cuenta['servidor'], cuenta['puerto'], contexto, 30)
    else:
        conexion = imaplib.IMAP4_SSL(cuenta['servidor'], cuenta['puerto'], ssl_context=contexto, timeout=30)
    conexion.login(cuenta['usuario'], cuenta['clave'])
    return conexion


# --- Leer ----------------------------------------------------------------------------------

def _texto(valor):
    """Cabecera codificada ('=?UTF-8?B?...?=') -> texto normal."""
    try:
        return str(make_header(decode_header(valor or ''))).strip()
    except Exception:
        return (valor or '').strip()


def _fecha(valor):
    try:
        return parsedate_to_datetime(valor).astimezone().replace(tzinfo=None).isoformat(timespec='minutes')
    except Exception:
        return ''


def _resumen(uid, cabeceras, cuenta):
    mensaje = message_from_bytes(cabeceras)
    nombre, direccion = parseaddr(_texto(mensaje['From']))
    return {
        'cuenta': cuenta['id'],
        'cuenta_nombre': cuenta['nombre'],
        'uid': uid,
        'de': nombre or direccion,
        'direccion': direccion,
        'asunto': _texto(mensaje['Subject']) or '(sin asunto)',
        'fecha': _fecha(mensaje['Date']),
    }


def _no_leidos(cuenta):
    """(número total de no leídos, los MAX_POR_CUENTA más recientes) de la bandeja de entrada."""
    conexion = _conectar(cuenta)
    try:
        conexion.select('INBOX', readonly=True)
        _, datos = conexion.uid('SEARCH', None, 'UNSEEN')
        uids = datos[0].split()
        recientes = uids[-MAX_POR_CUENTA:]
        correos = []
        if recientes:
            _, datos = conexion.uid('FETCH', b','.join(recientes), '(UID BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])')
            for parte in datos:
                if isinstance(parte, tuple):
                    uid = re.search(rb'UID (\d+)', parte[0])
                    if uid:
                        correos.append(_resumen(uid.group(1).decode(), parte[1], cuenta))
        correos.sort(key=lambda c: c['fecha'], reverse=True)
        return len(uids), correos
    finally:
        _cerrar(conexion)


def _cerrar(conexion):
    try:
        conexion.logout()
    except Exception:
        pass


def _es_error_de_clave(error):
    return isinstance(error, imaplib.IMAP4.error) and bool(re.search(r'(?i)auth|login|credential|password', str(error)))


def actualizar(automatico=False):
    """Vuelve a mirar los no leídos de todas las cuentas.

    En la revisión automática se saltan las cuentas cuya contraseña ha fallado: reintentar cada pocos
    minutos con una clave mala puede hacer que el servidor bloquee la cuenta. Se vuelven a probar al
    pulsar «Actualizar», al preguntar al bot o al reiniciar (tras cambiar el .env).
    """
    configuradas = cuentas()
    for cuenta in configuradas:
        anterior = estado.get(cuenta['id'], {})
        if automatico and anterior.get('clave_mala'):
            continue
        try:
            total, correos = _no_leidos(cuenta)
            nuevo = {'correos': correos, 'no_leidos': total, 'error': None}
        except Exception as error:
            log.warning('Correo %s: %s', cuenta['id'], error)
            nuevo = {'correos': anterior.get('correos', []), 'no_leidos': anterior.get('no_leidos', 0),
                     'error': _mensaje_error(error), 'clave_mala': _es_error_de_clave(error)}
            if nuevo['clave_mala']:
                nuevo['error'] += ' (no se reintenta solo: corrige el .env o pulsa Actualizar)'
        nuevo['actualizado'] = datetime.now().isoformat(timespec='seconds')
        with _cerrojo:
            estado[cuenta['id']] = nuevo
    with _cerrojo:
        for ident in set(estado) - {c['id'] for c in configuradas}:
            del estado[ident]


def _mensaje_error(error):
    """Motivo para enseñar en la web o el bot; el detalle técnico solo va a los registros del servidor."""
    if isinstance(error, DatosNoValidos):
        return error.mensaje
    if _es_error_de_clave(error):
        return 'Usuario o contraseña de aplicación incorrectos'
    if isinstance(error, ssl.SSLCertVerificationError):
        return 'El certificado del servidor de correo no es válido'
    if isinstance(error, (OSError, TimeoutError)):
        return 'No se pudo conectar con el servidor de correo'
    return 'Error del servidor de correo (detalles en los registros)'


def resumen_cuentas():
    """Estado de cada cuenta, sin datos sensibles (para la web y el bot)."""
    with _cerrojo:
        return [{'id': c['id'], 'nombre': c['nombre'], 'usuario': c['usuario'],
                 'no_leidos': estado.get(c['id'], {}).get('no_leidos', 0),
                 'error': estado.get(c['id'], {}).get('error'),
                 'actualizado': estado.get(c['id'], {}).get('actualizado')} for c in cuentas()]


def no_leidos():
    """Todos los no leídos guardados, de más reciente a más antiguo."""
    with _cerrojo:
        todos = [c for datos in estado.values() for c in datos.get('correos', [])]
    return sorted(todos, key=lambda c: c['fecha'], reverse=True)


class _SoloTexto(HTMLParser):
    """Saca el texto de un correo en HTML (sin estilos ni scripts)."""

    def __init__(self):
        super().__init__()
        self.partes, self._ignorar = [], 0

    def handle_starttag(self, etiqueta, atributos):
        if etiqueta in ('style', 'script', 'head'):
            self._ignorar += 1
        elif etiqueta in ('br', 'p', 'div', 'tr', 'li', 'h1', 'h2', 'h3'):
            self.partes.append('\n')

    def handle_endtag(self, etiqueta):
        if etiqueta in ('style', 'script', 'head') and self._ignorar:
            self._ignorar -= 1

    def handle_data(self, datos):
        if not self._ignorar:
            self.partes.append(datos)


def _cuerpo(mensaje):
    """Texto del correo: la parte de texto plano o, si no hay, el HTML convertido a texto."""
    plano = html = None
    for parte in mensaje.walk():
        if parte.get_content_maintype() == 'multipart' or parte.get_filename():
            continue
        try:
            contenido = parte.get_payload(decode=True).decode(parte.get_content_charset() or 'utf-8', 'replace')
        except Exception:
            continue
        if parte.get_content_type() == 'text/plain' and plano is None:
            plano = contenido
        elif parte.get_content_type() == 'text/html' and html is None:
            html = contenido
    if plano is None and html is not None:
        lector = _SoloTexto()
        lector.feed(html)
        plano = ''.join(lector.partes)
    texto = re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', (plano or '').replace('\r', ''))
    return texto.strip()[:MAX_TEXTO]


def leer(ident, uid):
    """Un correo completo (sin marcarlo como leído)."""
    cuenta = _cuenta(ident)
    conexion = _conectar(cuenta)
    try:
        conexion.select('INBOX', readonly=True)
        _, datos = conexion.uid('FETCH', str(uid), '(BODY.PEEK[])')
        crudo = next((p[1] for p in datos if isinstance(p, tuple)), None)
        if crudo is None:
            raise DatosNoValidos('Ese correo ya no está en la bandeja de entrada')
        mensaje = message_from_bytes(crudo)
        adjuntos = [_texto(p.get_filename()) for p in mensaje.walk() if p.get_filename()]
        return {**_resumen(str(uid), crudo, cuenta), 'para': _texto(mensaje['To']), 'texto': _cuerpo(mensaje),
                'adjuntos': adjuntos}
    finally:
        _cerrar(conexion)


# --- Ordenar -------------------------------------------------------------------------------

def _carpeta_especial(conexion, marca, nombres):
    """Carpeta con esa marca especial (\\Trash, \\All, \\Archive) o, si no, con alguno de esos nombres."""
    _, lineas = conexion.list()
    carpetas = []
    for linea in lineas or []:
        m = re.match(rb'\((?P<marcas>[^)]*)\) (?:"[^"]*"|NIL) (?P<nombre>.+)$', linea or b'')
        if m:
            carpetas.append((m.group('marcas').decode(errors='replace'), m.group('nombre').decode(errors='replace')))
    for marcas, nombre in carpetas:
        if marca.lower() in marcas.lower():
            return nombre
    for marcas, nombre in carpetas:
        if nombre.strip('"').split('/')[-1].lower() in nombres:
            return nombre
    return None


def _mover(conexion, uid, carpeta):
    if 'MOVE' in conexion.capabilities:
        estado_mov, _ = conexion.uid('MOVE', uid, carpeta)
        if estado_mov == 'OK':
            return
    conexion.uid('COPY', uid, carpeta)
    conexion.uid('STORE', uid, '+FLAGS', '(\\Deleted)')
    conexion.expunge()


def accion(ident, uid, que):
    """'leido', 'archivar' o 'borrar' un correo de la bandeja de entrada."""
    if que not in ACCIONES:
        raise DatosNoValidos('Acción no válida')
    cuenta = _cuenta(ident)
    uid = str(uid)
    conexion = _conectar(cuenta)
    try:
        conexion.select('INBOX')
        conexion.uid('STORE', uid, '+FLAGS', '(\\Seen)')
        if que == 'archivar':
            carpeta = _carpeta_especial(conexion, '\\All', ()) if cuenta['servidor'] == 'imap.gmail.com' else \
                _carpeta_especial(conexion, '\\Archive', ('archive', 'archivo', 'archived', 'archivados'))
            if carpeta is None:
                raise DatosNoValidos('Esta cuenta no tiene carpeta de archivo: márcalo como leído o bórralo')
            _mover(conexion, uid, carpeta)
        elif que == 'borrar':
            carpeta = _carpeta_especial(conexion, '\\Trash', ('trash', 'papelera', 'deleted items', 'elementos eliminados'))
            if carpeta:
                _mover(conexion, uid, carpeta)
            else:
                conexion.uid('STORE', uid, '+FLAGS', '(\\Deleted)')
                conexion.expunge()
    finally:
        _cerrar(conexion)

    # Ya no está sin leer: fuera de la lista guardada
    with _cerrojo:
        datos = estado.get(ident)
        if datos:
            antes = len(datos['correos'])
            datos['correos'] = [c for c in datos['correos'] if c['uid'] != uid]
            datos['no_leidos'] = max(0, datos['no_leidos'] - (antes - len(datos['correos'])))


# --- En segundo plano --------------------------------------------------------------------

def _bucle():
    minutos = max(1, int(os.getenv('CORREO_MINUTOS', '5') or 5))
    while True:
        try:
            actualizar(automatico=True)
        except Exception:
            log.exception('Error revisando el correo')
        time.sleep(minutos * 60)


def arrancar_en_segundo_plano():
    if not configurado():
        log.info('Sin cuentas de correo (CORREO_CUENTAS): no se revisa el correo')
        return
    threading.Thread(target=_bucle, name='correo', daemon=True).start()
