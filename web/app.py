from datetime import date, datetime
from pathlib import Path
import os

from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request, send_from_directory

# El .env vive en la raíz del proyecto (un nivel por encima de /web)
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

import asignaciones
import avisos
import copias
import correo
import db
import eventos
import google_cal
import resumen
import sesiones
import telegram_bot
import usuarios
from whatsapp import whatsapp_bp

app = Flask(__name__)
app.register_blueprint(whatsapp_bp)
# Inicio de sesión: todas las páginas y la API lo piden salvo el webhook, /legal/ y los estáticos
sesiones.configurar(app)


@app.context_processor
def datos_comunes():
    usuario = g.get('usuario')
    nombre = usuario['nombre'] if usuario else os.getenv('NOMBRE_USUARIO', '').strip()
    # Aviso junto al nombre: cuentas nuevas por aprobar (administrador) e invitaciones a grupos
    solicitudes = db.contar_pendientes() if usuario and usuario['es_admin'] else 0
    invitaciones = db.contar_invitaciones(usuario['id']) if usuario else 0
    return {'persona_defecto': db.persona_por_defecto(), 'nombre_usuario': nombre, 'usuario': usuario,
            'solicitudes': solicitudes + invitaciones,
            'ancla_cuenta': '#grupos' if invitaciones else ('#usuarios' if solicitudes else '')}


@app.route('/')
def index():
    return render_template('./index.html')


@app.route('/index')
def index_web():
    return render_template('./index.html')


@app.route('/tareas')
def doing():
    return render_template('./tareas.html')


@app.route('/calendar')
def calendario():
    return render_template('./calendar.html')


# --- App instalable (PWA): el manifiesto y el service worker tienen que servirse desde la raíz
# para que abarquen toda la web, y con su tipo MIME correcto

@app.route('/manifest.webmanifest')
def manifiesto():
    return send_from_directory(app.static_folder, 'manifest.webmanifest', mimetype='application/manifest+json')


@app.route('/sw.js')
def service_worker():
    respuesta = send_from_directory(app.static_folder, 'js/sw.js', mimetype='application/javascript')
    respuesta.headers['Cache-Control'] = 'no-cache'
    return respuesta


@app.route('/legal/')
def legal_inicio():
    # Páginas públicas que Google exige para publicar la app de OAuth (página principal y privacidad)
    return render_template('legal/inicio.html')


@app.route('/legal/privacidad')
def legal_privacidad():
    return render_template('legal/privacidad.html')


@app.route('/recordatorios')
def recordatorios():
    return render_template('./recordatorios.html')


@app.route('/notas')
def notas():
    return render_template('./notas.html')


@app.route('/correos')
def correos():
    return render_template('./correos.html')


# --- Correo --------------------------------------------------------------------------

@app.route('/api/correos')
def correos_api():
    return jsonify({'cuentas': correo.resumen_cuentas(), 'correos': correo.no_leidos()})


@app.route('/api/correos/actualizar', methods=['POST'])
def correos_actualizar():
    correo.actualizar()
    return correos_api()


@app.route('/api/correos/<cuenta>/<int:uid>')
def correo_api(cuenta, uid):
    try:
        return jsonify(correo.leer(cuenta, uid))
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 404
    except Exception as error:
        app.logger.warning('No se pudo abrir el correo %s/%s: %s', cuenta, uid, error)
        return jsonify({'error': f'No se pudo abrir el correo: {correo._mensaje_error(error)}'}), 502


@app.route('/api/correos/<cuenta>/<int:uid>/<que>', methods=['POST'])
def correo_accion_api(cuenta, uid, que):
    try:
        correo.accion(cuenta, uid, que)
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 400
    except Exception as error:
        app.logger.warning('No se pudo hacer «%s» con el correo %s/%s: %s', que, cuenta, uid, error)
        return jsonify({'error': f'No se pudo hacer: {correo._mensaje_error(error)}'}), 502
    return jsonify({'ok': True})


@app.route('/api/conexiones')
def conexiones_api():
    """Qué está conectado, para el panel de inicio (sin datos sensibles)."""
    return jsonify({
        'google': {**google_cal.estado, 'configurado': google_cal.configurado()},
        'telegram': bool(os.getenv('TELEGRAM_TOKEN')),
        'whatsapp': bool(os.getenv('TOKEN') and os.getenv('WHATSAPP_PHONE_NUMBER_ID')),
        'correos': correo.resumen_cuentas(),
    })


def recordatorio_a_json(recordatorio):
    return {
        'id': recordatorio['id'],
        'texto': recordatorio['texto'],
        # Formato que entiende <input type="datetime-local">
        'cuando': recordatorio['cuando'].replace(' ', 'T'),
        'estado': recordatorio['estado'],
        'canal': 'Telegram' if recordatorio['destino'].startswith('tg:') else 'WhatsApp',
        'destino': recordatorio['destino'],
        'grupo_id': recordatorio.get('grupo_id'),
        # Si es de otro miembro del grupo, el aviso le llega a cada uno por su propio chat
        'mio': recordatorio['destino'] in usuarios.chats_de(g.get('usuario')),
    }


def canales_recordatorio():
    """Chats a los que el usuario puede mandarse avisos desde la web: los suyos de WhatsApp y Telegram."""
    suyos = usuarios.chats_de(g.get('usuario'))
    whatsapp = [c for c in suyos if not c.startswith('tg:')]
    telegram = [c[3:] for c in suyos if c.startswith('tg:')]
    canales = []
    for numero in whatsapp:
        hasta = avisos.ventana_hasta(numero)
        canales.append({
            'destino': numero, 'canal': 'WhatsApp',
            'etiqueta': 'WhatsApp' + (f' · …{numero[-3:]}' if len(whatsapp) > 1 else ''),
            # Sin plantilla, WhatsApp solo entrega si has escrito al bot en las 24 h anteriores al aviso
            'ventana_hasta': hasta.isoformat(timespec='minutes') if hasta else None,
            'plantilla': bool(os.getenv('WHATSAPP_REMINDER_TEMPLATE')),
        })
    for usuario in telegram:
        canales.append({'destino': f'tg:{usuario}', 'canal': 'Telegram',
                        'etiqueta': 'Telegram' + (f' · …{usuario[-3:]}' if len(telegram) > 1 else ''),
                        'ventana_hasta': None, 'plantilla': True})
    return canales


def leer_recordatorio(payload, destino_actual=None):
    """Valida lo que manda la web. Devuelve (texto, cuando, destino) o lanza DatosNoValidos."""
    texto = (payload.get('texto') or '').strip()
    if not texto:
        raise db.DatosNoValidos('El recordatorio necesita un texto')
    try:
        cuando = datetime.strptime((payload.get('cuando') or '')[:16], '%Y-%m-%dT%H:%M')
    except ValueError as error:
        raise db.DatosNoValidos('Fecha y hora no válidas') from error
    if cuando <= datetime.now():
        raise db.DatosNoValidos('La fecha y hora deben ser futuras')
    destino = payload.get('destino') or destino_actual
    if destino != destino_actual and destino not in {c['destino'] for c in canales_recordatorio()}:
        raise db.DatosNoValidos('Elige si quieres el aviso por WhatsApp o por Telegram')
    return texto, cuando, destino


def grupo_del_recordatorio(payload, recordatorio=None):
    """El grupo con el que compartir el recordatorio (comprobado), o el que ya tenía si no se indica."""
    if 'grupo_id' not in payload:
        return recordatorio['grupo_id'] if recordatorio else None
    existente = None
    if recordatorio is not None:
        dueno = db.usuario_por_chat(recordatorio['destino'])
        existente = {'grupo_id': recordatorio['grupo_id'], 'usuario_id': dueno['id'] if dueno else None}
    return db.comprobar_grupo('recordatorios', payload.get('grupo_id'), existente)


def recordatorio_visible(recordatorio):
    """Los de los chats de quien ha iniciado sesión y los compartidos en sus grupos."""
    if recordatorio['destino'] in usuarios.chats_de(g.usuario):
        return True
    return bool(recordatorio['grupo_id']) and any(
        grupo['id'] == recordatorio['grupo_id'] for grupo in db.grupos_de(g.usuario['id'], tipo='recordatorios'))


@app.route('/api/grupos')
def grupos_api():
    """Grupos del usuario y qué comparte cada uno, para elegir con quién compartir algo."""
    if not g.usuario:
        return jsonify([])
    return jsonify([{'id': grupo['id'], 'nombre': grupo['nombre'], 'comparte': grupo['comparte']}
                    for grupo in db.grupos_de(g.usuario['id'])])


@app.route('/api/eventos', methods=['GET', 'POST'])
def eventos_api():
    if request.method == 'POST':
        try:
            datos = eventos.validar(request.get_json(silent=True) or {})
        except db.DatosNoValidos as error:
            return jsonify({'error': error.mensaje}), 400
        return jsonify(db.obtener_evento(db.guardar_evento(datos))), 201

    # GET ?desde=AAAA-MM-DD&hasta=AAAA-MM-DD -> ocurrencias (las repeticiones ya expandidas)
    try:
        desde = date.fromisoformat(request.args.get('desde', ''))
        hasta = date.fromisoformat(request.args.get('hasta', ''))
    except ValueError:
        return jsonify({'error': 'Indica desde y hasta en formato AAAA-MM-DD'}), 400
    if (hasta - desde).days > 400:
        return jsonify({'error': 'Rango demasiado grande'}), 400
    return jsonify(eventos.en_rango(desde, hasta))


@app.route('/api/eventos/<int:evento_id>', methods=['PUT', 'DELETE'])
def evento_api(evento_id):
    evento = db.obtener_evento(evento_id)
    if evento is None:
        return jsonify({'error': 'Evento no encontrado'}), 404

    # En un evento que se repite: ?alcance=uno|siguientes|serie&fecha=AAAA-MM-DD (el día pulsado)
    alcance = request.args.get('alcance', 'serie')
    if alcance not in eventos.ALCANCES:
        return jsonify({'error': 'Alcance no válido'}), 400
    try:
        dia = date.fromisoformat(request.args['fecha']) if request.args.get('fecha') else None
    except ValueError:
        return jsonify({'error': 'Fecha no válida'}), 400

    try:
        if request.method == 'DELETE':
            eventos.borrar(evento, alcance, dia)
            return '', 204
        nuevo_id = eventos.modificar(evento, request.get_json(silent=True) or {}, alcance, dia)
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 400
    return jsonify(db.obtener_evento(nuevo_id))


@app.route('/api/google/estado')
def google_estado():
    return jsonify({**google_cal.estado, 'configurado': google_cal.configurado()})


@app.route('/api/google/sincronizar', methods=['POST'])
def google_sincronizar():
    if not google_cal.configurado():
        return jsonify({'error': 'Google Calendar no está configurado'}), 400
    try:
        google_cal.sincronizar()
    except Exception:  # el detalle queda en el estado y en el log
        app.logger.exception('Error sincronizando con Google Calendar')
        return jsonify({**google_cal.estado, 'configurado': True,
                        'error': 'No se pudo sincronizar con Google (detalles en los registros del servidor)'}), 502
    return jsonify({**google_cal.estado, 'configurado': True})


@app.route('/api/recordatorios', methods=['GET', 'POST'])
def recordatorios_api():
    if request.method == 'POST':
        try:
            payload = request.get_json(silent=True) or {}
            texto, cuando, destino = leer_recordatorio(payload)
            grupo = grupo_del_recordatorio(payload)
        except db.DatosNoValidos as error:
            return jsonify({'error': error.mensaje}), 400
        nuevo = db.crear_recordatorio(destino, texto, cuando, grupo)
        return jsonify(recordatorio_a_json(db.obtener_recordatorio(nuevo))), 201
    return jsonify([recordatorio_a_json(r) for r in db.listar_recordatorios(usuarios.chats_de(g.usuario))])


@app.route('/api/recordatorios/canales')
def recordatorios_canales():
    return jsonify(canales_recordatorio())


@app.route('/api/recordatorios/<int:recordatorio_id>', methods=['PUT', 'DELETE'])
def recordatorio_api(recordatorio_id):
    recordatorio = db.obtener_recordatorio(recordatorio_id)
    if recordatorio is not None and not recordatorio_visible(recordatorio):
        recordatorio = None
    if recordatorio is None or recordatorio['estado'] == 'cancelado':
        return jsonify({'error': 'Recordatorio no encontrado'}), 404

    if request.method == 'DELETE':
        db.actualizar_recordatorio(recordatorio_id, 'cancelado')
        return '', 204

    try:
        payload = request.get_json(silent=True) or {}
        texto, cuando, destino = leer_recordatorio(payload, recordatorio['destino'])
        grupo = grupo_del_recordatorio(payload, recordatorio)
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 400

    db.editar_recordatorio(recordatorio_id, texto, cuando, destino, grupo)
    return jsonify(recordatorio_a_json(db.obtener_recordatorio(recordatorio_id)))


@app.route('/api/tareas', methods=['GET', 'POST'])
def tareas_api():
    if request.method == 'GET':
        return jsonify(db.fetch_all_tasks())

    payload = request.get_json(silent=True) or {}

    try:
        task = db.insert_task(payload)
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 400

    # Si es de un grupo y el encargado es otro miembro, el bot se lo dice
    aviso = asignaciones.al_guardar(None, task)
    if aviso:
        task['aviso'] = aviso
    return jsonify(task), 201


@app.route('/api/carpetas', methods=['GET', 'POST'])
def carpetas_api():
    """Carpetas de tareas que ve el usuario ("Universidad", "Casa"...): las suyas y las de sus grupos."""
    if request.method == 'GET':
        return jsonify(db.listar_carpetas())
    try:
        datos = request.get_json(silent=True) or {}
        carpeta = db.crear_carpeta(datos.get('nombre'), datos.get('grupo_id'))
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 400
    return jsonify(carpeta), 201


@app.route('/api/carpetas/<int:carpeta_id>', methods=['PUT', 'DELETE'])
def carpeta_api(carpeta_id):
    if request.method == 'DELETE':
        if not db.borrar_carpeta(carpeta_id):
            return jsonify({'error': 'Carpeta no encontrada'}), 404
        return '', 204
    try:
        # nombre y/o grupo_id (null: solo para quien la creó)
        datos = request.get_json(silent=True) or {}
        carpeta = db.cambiar_carpeta(carpeta_id, {k: v for k, v in datos.items() if k in ('nombre', 'grupo_id')})
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 400
    if carpeta is None:
        return jsonify({'error': 'Carpeta no encontrada'}), 404
    return jsonify(carpeta)


# --- Notas (texto libre o listas que se tachan) ---------------------------------------------

def _datos_json():
    datos = request.get_json(silent=True)
    return datos if isinstance(datos, dict) else {}


def _respuesta_nota(funcion, *argumentos, estado=200):
    """Llama a la función de db y devuelve la nota en JSON (404 si no existe, 400 si los datos no valen)."""
    try:
        nota = funcion(*argumentos)
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 400
    if nota is None:
        return jsonify({'error': 'Nota no encontrada'}), 404
    return jsonify(nota), estado


@app.route('/api/notas', methods=['GET', 'POST'])
def notas_api():
    if request.method == 'GET':
        return jsonify(db.listar_notas())
    return _respuesta_nota(db.crear_nota, _datos_json(), estado=201)


@app.route('/api/notas/<int:nota_id>', methods=['PUT', 'DELETE'])
def nota_api(nota_id):
    if request.method == 'DELETE':
        if not db.borrar_nota(nota_id):
            return jsonify({'error': 'Nota no encontrada'}), 404
        return '', 204
    datos = {k: v for k, v in _datos_json().items() if k in ('titulo', 'contenido', 'fijada', 'grupo_id')}
    return _respuesta_nota(db.cambiar_nota, nota_id, datos)


@app.route('/api/notas/<int:nota_id>/elementos', methods=['POST'])
def nota_elementos_api(nota_id):
    datos = _datos_json()
    textos = datos['textos'] if isinstance(datos.get('textos'), list) else [datos.get('texto')]
    return _respuesta_nota(db.anadir_elementos, nota_id, textos, estado=201)


@app.route('/api/notas/<int:nota_id>/elementos/<int:elemento_id>', methods=['PUT', 'DELETE'])
def nota_elemento_api(nota_id, elemento_id):
    if request.method == 'DELETE':
        return _respuesta_nota(db.borrar_elemento, nota_id, elemento_id)
    datos = {k: v for k, v in _datos_json().items() if k in ('texto', 'hecho')}
    return _respuesta_nota(db.cambiar_elemento, nota_id, elemento_id, datos)


@app.route('/api/notas/<int:nota_id>/<accion>', methods=['POST'])
def nota_accion_api(nota_id, accion):
    """desmarcar (quitar todas las tachaduras) o limpiar (borrar lo tachado) en una lista."""
    if accion not in ('desmarcar', 'limpiar'):
        return jsonify({'error': 'Acción no válida'}), 404
    return _respuesta_nota(db.ordenar_lista, nota_id, accion)


@app.route('/api/tareas/<task_id>', methods=['PUT', 'DELETE'])
def tarea_api(task_id):
    if request.method == 'DELETE':
        if not db.delete_task(task_id):
            return jsonify({'error': 'Tarea no encontrada'}), 404
        return '', 204

    payload = request.get_json(silent=True) or {}

    antes = db.fetch_task(task_id)
    try:
        task = db.update_task(task_id, payload)
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 400

    if task is None:
        return jsonify({'error': 'Tarea no encontrada'}), 404

    aviso = asignaciones.al_guardar(antes, task)
    if aviso:
        task['aviso'] = aviso
    return jsonify(task)


db.init_db()

# Con FLASK_DEBUG=1 el recargador ejecuta este archivo dos veces; solo el proceso hijo debe escuchar
# a Telegram, o habría dos lectores a la vez y Telegram rechaza el segundo
if os.getenv('FLASK_DEBUG') != '1' or os.getenv('WERKZEUG_RUN_MAIN') == 'true':
    telegram_bot.arrancar_en_segundo_plano()
    avisos.arrancar_en_segundo_plano()
    google_cal.arrancar_en_segundo_plano()
    copias.arrancar_en_segundo_plano()
    resumen.arrancar_en_segundo_plano()
    correo.arrancar_en_segundo_plano()

if __name__ == '__main__':
    # Desarrollo en local. En el servidor se ejecuta con Docker (ver docker-compose.yml)
    app.run(debug=os.getenv('FLASK_DEBUG') == '1')
