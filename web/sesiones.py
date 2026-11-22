"""Inicio de sesión en la web.

- Las contraseñas se guardan solo como hash (scrypt con sal aleatoria, de Werkzeug): ni en la base
  de datos ni en ningún otro sitio queda la contraseña.
- La sesión va en una cookie firmada (no se puede falsificar sin la clave secreta del servidor),
  HttpOnly (el JavaScript de la página no la ve), SameSite=Lax (otras webs no la pueden usar para
  hacer cambios) y Secure cuando se entra por HTTPS.
- "Mantener la sesión iniciada": la cookie dura SESION_DIAS días (90 por defecto) y se renueva
  con cada visita, así que mientras se use al menos una vez cada 90 días no se vuelve a pedir.
  Sin marcarlo, la sesión se cierra al cerrar el navegador.
- Cambiar la contraseña (o "cerrar sesión en todos los dispositivos") invalida todas las cookies
  de ese usuario, aunque no hayan caducado.
- Tras varios intentos fallidos seguidos se bloquea un rato ese usuario y esa IP.
- Registro desde la web (/registro): la cuenta queda pendiente hasta que el administrador la
  aprueba en su página Cuenta. Se puede desactivar con REGISTRO=no en el .env.
"""
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
import logging
import os
import re
import secrets
import threading
import time

from flask import (Blueprint, abort, g, jsonify, redirect, render_template, request, session, url_for)
from flask.sessions import SecureCookieSessionInterface
from werkzeug.security import check_password_hash, generate_password_hash

import db

log = logging.getLogger(__name__)
sesiones_bp = Blueprint('sesiones', __name__)

LONGITUD_MINIMA = 10
MAX_FALLOS = 5
BLOQUEO = 15 * 60  # segundos

# Rutas que se pueden ver sin iniciar sesión
PUBLICAS = {'sesiones.login', 'sesiones.registro', 'static', 'manifiesto', 'service_worker', 'legal_inicio', 'legal_privacidad'}
BLUEPRINTS_PUBLICOS = {'whatsapp'}  # el webhook de Meta tiene su propia verificación
SOLO_ADMIN_API = ('/api/correos', '/api/conexiones', '/api/google')
SOLO_ADMIN_PAGINAS = ('/correos',)
MAX_REGISTROS_IP = 3  # registros por hora desde una misma IP
MAX_PENDIENTES = 20  # solicitudes sin revisar a la vez (para que nadie llene la base de datos)


# --- Contraseñas ----------------------------------------------------------------------

def hash_clave(clave):
    return generate_password_hash(clave, method='scrypt')


def clave_valida(clave):
    """Mensaje de error si la contraseña es demasiado débil, o None."""
    if len(clave or '') < LONGITUD_MINIMA:
        return f'La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres'
    if clave.strip() != clave:
        return 'La contraseña no puede empezar ni acabar con espacios'
    return None


# Hash de una contraseña cualquiera: si el usuario no existe se comprueba contra este, para que
# la respuesta tarde lo mismo y no se pueda adivinar qué usuarios existen
_HASH_FALSO = hash_clave(secrets.token_urlsafe(16))


def comprobar(usuario, clave):
    """El usuario si la contraseña es correcta, o None."""
    datos = db.usuario_por_nombre(usuario)
    if datos is None:
        check_password_hash(_HASH_FALSO, clave or '')
        return None
    if not check_password_hash(datos['clave_hash'], clave or ''):
        return None
    datos.pop('clave_hash')
    return datos


# --- Intentos fallidos ----------------------------------------------------------------

_fallos = {}  # clave -> [instantes de los fallos recientes]
_cerrojo = threading.Lock()


def _claves_intento(usuario):
    return [f'ip:{request.remote_addr}', f'usuario:{(usuario or "").strip().lower()}']


def _bloqueado(usuario):
    ahora = time.monotonic()
    with _cerrojo:
        for clave in _claves_intento(usuario):
            recientes = [t for t in _fallos.get(clave, []) if ahora - t < BLOQUEO]
            _fallos[clave] = recientes
            if len(recientes) >= MAX_FALLOS:
                return True
    return False


def _anotar_fallo(usuario):
    with _cerrojo:
        for clave in _claves_intento(usuario):
            _fallos.setdefault(clave, []).append(time.monotonic())


def _olvidar_fallos(usuario):
    with _cerrojo:
        for clave in _claves_intento(usuario):
            _fallos.pop(clave, None)


# --- Cookie de sesión -------------------------------------------------------------------

class _SesionSegura(SecureCookieSessionInterface):
    """Marca la cookie como Secure cuando se entra por HTTPS (nginx avisa con X-Forwarded-Proto).

    Así funciona tanto en https://...:8443 (la app del móvil) como en la dirección http:// de Tailscale.
    """

    def get_cookie_secure(self, app):
        return request.is_secure


def _clave_secreta():
    """SECRET_KEY del .env o, si no hay, una aleatoria guardada en data/ (sobrevive a las actualizaciones)."""
    if os.getenv('SECRET_KEY'):
        return os.getenv('SECRET_KEY')
    archivo = Path(db.DB_PATH).parent / 'clave_sesiones'
    if not archivo.exists():
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(secrets.token_hex(32), encoding='utf-8')
        os.chmod(archivo, 0o600)
    return archivo.read_text(encoding='utf-8').strip()


def configurar(app):
    from werkzeug.middleware.proxy_fix import ProxyFix

    # Detrás de nginx: la IP real del cliente y si la conexión original era HTTPS
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.secret_key = _clave_secreta()
    app.session_interface = _SesionSegura()
    app.config.update(
        SESSION_COOKIE_NAME='mi_notion_sesion',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(days=int(os.getenv('SESION_DIAS', '90'))),
        SESSION_REFRESH_EACH_REQUEST=True,
    )
    app.register_blueprint(sesiones_bp)
    app.before_request(_exigir_sesion)
    app.teardown_request(_soltar_usuario)


def _usuario_de_la_sesion():
    usuario_id = session.get('uid')
    if not usuario_id:
        return None
    usuario = db.obtener_usuario(usuario_id)
    # Usuario borrado, contraseña cambiada o "cerrar todas las sesiones": la cookie ya no vale
    if usuario is None or usuario['estado'] != 'activo' or usuario['version_sesion'] != session.get('v'):
        session.clear()
        return None
    return usuario


def _mismo_origen():
    """Las peticiones que cambian algo deben venir de esta misma web (defensa extra contra CSRF)."""
    origen = request.headers.get('Origin')
    if not origen:
        return True  # navegadores antiguos o peticiones sin Origin: queda la protección de SameSite
    # Solo se compara el nombre, sin puerto: nginx pasa el Host sin el ":8443" de la app del móvil
    return (urlsplit(origen).hostname or '').lower() == request.host.split(':')[0].lower()


def _exigir_sesion():
    g.usuario = None
    if request.blueprint in BLUEPRINTS_PUBLICOS or request.endpoint in PUBLICAS:
        return None
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and not _mismo_origen():
        abort(403)

    usuario = _usuario_de_la_sesion()
    if usuario is None:
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Tienes que iniciar sesión', 'login': True}), 401
        return redirect(url_for('sesiones.login', siguiente=request.full_path.rstrip('?')))

    g.usuario = usuario
    g.marca_usuario = db.usar_usuario(usuario)
    if not usuario['es_admin'] and (request.path.startswith(SOLO_ADMIN_API) or request.path in SOLO_ADMIN_PAGINAS):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Solo disponible para el administrador'}), 403
        return redirect('/')
    return None


def _soltar_usuario(_error=None):
    marca = g.pop('marca_usuario', None)
    if marca is not None:
        db.soltar_usuario(marca)


def _destino_seguro(siguiente):
    """Solo rutas de esta web ("/tareas"), nunca otra web ("//malo.com" o "https://...")."""
    if not siguiente or not siguiente.startswith('/') or siguiente.startswith('//') or '\\' in siguiente:
        return '/'
    return siguiente


# --- Páginas ----------------------------------------------------------------------------

@sesiones_bp.route('/login', methods=['GET', 'POST'])
def login():
    siguiente = _destino_seguro(request.values.get('siguiente'))
    if not db.hay_usuarios():
        return render_template('login.html', sin_usuarios=True, siguiente=siguiente), 503
    if request.method == 'GET':
        if _usuario_de_la_sesion():
            return redirect(siguiente)
        return render_template('login.html', siguiente=siguiente, salir=request.args.get('salir') == '1',
                               registro=_registro_abierto())

    if not _mismo_origen():
        abort(403)
    usuario = (request.form.get('usuario') or '').strip()
    clave = request.form.get('clave') or ''
    if _bloqueado(usuario):
        return render_template('login.html', siguiente=siguiente, usuario=usuario,
                               error='Demasiados intentos fallidos. Espera 15 minutos y vuelve a probar.'), 429
    datos = comprobar(usuario, clave)
    if datos is None:
        _anotar_fallo(usuario)
        log.warning('Inicio de sesión fallido para %r desde %s', usuario, request.remote_addr)
        return render_template('login.html', siguiente=siguiente, usuario=usuario,
                               error='Usuario o contraseña incorrectos', registro=_registro_abierto()), 401

    _olvidar_fallos(usuario)
    if datos['estado'] != 'activo':
        return render_template('login.html', siguiente=siguiente, usuario=usuario, registro=_registro_abierto(),
                               error='Tu cuenta todavía está pendiente de que el administrador la apruebe.'), 403
    session.clear()  # una sesión nueva al entrar: nada de lo anterior se reutiliza
    session['uid'] = datos['id']
    session['v'] = datos['version_sesion']
    session.permanent = request.form.get('recordar') == '1'
    log.info('Sesión iniciada: %s', datos['usuario'])
    return redirect(siguiente)


@sesiones_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    # ?salir=1: la página de login borra la copia de las páginas que guarda la app instalada
    return redirect(url_for('sesiones.login', salir=1))


# --- Registro ---------------------------------------------------------------------------

def _registro_abierto():
    return os.getenv('REGISTRO', 'si').strip().lower() not in ('no', 'false', '0')


_registros = {}  # ip -> [instantes de los registros recientes]


def _demasiados_registros():
    ahora = time.monotonic()
    clave = request.remote_addr
    with _cerrojo:
        recientes = [t for t in _registros.get(clave, []) if ahora - t < 3600]
        _registros[clave] = recientes
        if len(recientes) >= MAX_REGISTROS_IP:
            return True
        recientes.append(ahora)
    return False


def _leer_chats_del_formulario(formulario, usuario_id=None):
    """(chats, error) con el WhatsApp y el Telegram del formulario."""
    import usuarios  # aquí para evitar una importación circular al arrancar

    whatsapp = usuarios.leer_whatsapp(formulario.get('whatsapp'))
    if whatsapp is None:
        return [], 'El número de WhatsApp no es válido (con prefijo de país, p. ej. 34600111222)'
    telegram = usuarios.leer_telegram(formulario.get('telegram'))
    if telegram is None:
        return [], 'El id de Telegram son solo números (escribe al bot y te lo dirá)'
    chats = [c for c in (whatsapp, telegram) if c]
    if set(chats) & usuarios.chats_en_uso(usuario_id):
        return [], 'Ese WhatsApp o Telegram ya lo usa otra cuenta'
    return chats, None


def _avisar_al_admin(texto):
    """Manda un mensaje al administrador por el bot (en segundo plano: si falla, no pasa nada)."""
    def enviar():
        import telegram_bot
        import usuarios
        import whatsapp

        admin = db.obtener_usuario(db.id_admin_principal())
        chats = usuarios.chats_de(admin)
        # Telegram primero: WhatsApp solo deja escribir si le has hablado al bot en las últimas 24 h
        for chat in sorted(chats, key=lambda c: not c.startswith('tg:')):
            try:
                if chat.startswith('tg:'):
                    telegram_bot.enviar_mensaje(chat[3:], texto)
                    return
                if whatsapp.enviar_mensaje(chat, texto):
                    return
            except Exception as error:  # noqa: BLE001 - el aviso es opcional
                log.warning('No se pudo avisar al administrador de un registro: %s', error)

    threading.Thread(target=enviar, daemon=True).start()


@sesiones_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    if not db.hay_usuarios() or not _registro_abierto():
        return redirect(url_for('sesiones.login'))
    if request.method == 'GET':
        if _usuario_de_la_sesion():
            return redirect('/')
        return render_template('registro.html', datos={})

    if not _mismo_origen():
        abort(403)
    datos = {campo: (request.form.get(campo) or '').strip()
             for campo in ('nombre', 'usuario', 'whatsapp', 'telegram')}
    clave = request.form.get('clave') or ''
    chats, error = _leer_chats_del_formulario(request.form)
    if not error:
        if not re.fullmatch(r'[A-Za-z0-9._-]{2,40}', datos['usuario']):
            error = 'El usuario debe tener entre 2 y 40 letras sin tildes, números, puntos o guiones'
        elif not 1 <= len(datos['nombre']) <= 60:
            error = 'Escribe tu nombre (hasta 60 caracteres)'
        elif clave != request.form.get('repetida'):
            error = 'Las dos contraseñas no coinciden'
        else:
            error = clave_valida(clave)
    if not error and db.usuario_por_nombre(datos['usuario']):
        error = 'Ese usuario ya existe, elige otro'
    if not error and (db.contar_pendientes() >= MAX_PENDIENTES or _demasiados_registros()):
        error = 'Ahora mismo no se pueden hacer más registros. Prueba dentro de un rato.'
    if error:
        return render_template('registro.html', datos=datos, error=error), 400

    db.crear_usuario(datos['usuario'], datos['nombre'], hash_clave(clave), False, chats, estado='pendiente')
    log.info('Nuevo registro pendiente de aprobar: %s', datos['usuario'])
    _avisar_al_admin(f'👤 *{datos["nombre"]}* ({datos["usuario"]}) se ha registrado en Mi Notion. '
                     'Apruébalo o recházalo en la web, en tu página Cuenta.')
    return render_template('registro.html', enviado=True, datos=datos)


# --- Cuenta -----------------------------------------------------------------------------

def _accion_de_admin(accion, usuario_id):
    """Aprobar, rechazar o eliminar a otro usuario. Devuelve (mensaje, error)."""
    otro = db.obtener_usuario(int(usuario_id)) if usuario_id.isdigit() else None
    if otro is None or otro['es_admin']:
        return None, 'Ese usuario no existe o es administrador'
    if accion == 'aprobar' and otro['estado'] == 'pendiente':
        db.aprobar_usuario(otro['id'])
        return f'{otro["nombre"]} ya puede entrar.', None
    if accion == 'rechazar' and otro['estado'] == 'pendiente':
        db.borrar_usuario(otro['id'])
        return f'Solicitud de {otro["nombre"]} rechazada.', None
    if accion == 'eliminar' and otro['estado'] == 'activo':
        db.borrar_usuario(otro['id'])
        return f'{otro["nombre"]} y todo lo suyo se han borrado.', None
    return None, 'Esa acción no se puede hacer'


@sesiones_bp.route('/cuenta', methods=['GET', 'POST'])
def cuenta():
    import usuarios  # aquí para evitar una importación circular al arrancar

    usuario = g.usuario
    mensaje = error = None
    if request.method == 'POST':
        accion = request.form.get('accion')
        if accion == 'clave':
            if comprobar(usuario['usuario'], request.form.get('actual')) is None:
                error = 'La contraseña actual no es correcta'
            elif request.form.get('nueva') != request.form.get('repetida'):
                error = 'Las dos contraseñas nuevas no coinciden'
            else:
                error = clave_valida(request.form.get('nueva'))
            if not error:
                db.cambiar_clave(usuario['id'], hash_clave(request.form['nueva']))
                # Las demás sesiones se cierran; esta sigue abierta con la versión nueva
                session['v'] = db.obtener_usuario(usuario['id'])['version_sesion']
                mensaje = 'Contraseña cambiada. Se ha cerrado la sesión en los demás dispositivos.'
        elif accion == 'cerrar_todas':
            db.cerrar_sesiones(usuario['id'])
            session.clear()
            return redirect(url_for('sesiones.login', salir=1))
        elif accion == 'chats' and not usuario['es_admin']:
            chats, error = _leer_chats_del_formulario(request.form, usuario['id'])
            if not error:
                db.fijar_chats(usuario['id'], chats)
                usuario = g.usuario = db.obtener_usuario(usuario['id'])
                mensaje = 'Chats del bot guardados.'
        elif accion in ('aprobar', 'rechazar', 'eliminar') and usuario['es_admin']:
            mensaje, error = _accion_de_admin(accion, request.form.get('id') or '')
        else:
            error = 'Acción no válida'

    otros = [u for u in db.listar_usuarios() if u['id'] != usuario['id']] if usuario['es_admin'] else []
    chats = usuarios.chats_de(usuario)
    return render_template(
        'cuenta.html', mensaje=mensaje, error=error, chats=chats,
        whatsapp=next((c for c in chats if not c.startswith('tg:')), ''),
        telegram=next((c[3:] for c in chats if c.startswith('tg:')), ''),
        pendientes=[u for u in otros if u['estado'] == 'pendiente'],
        activos=[u for u in otros if u['estado'] == 'activo'],
    ), (400 if error else 200)
