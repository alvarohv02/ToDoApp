from datetime import date, datetime
from pathlib import Path
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

# El .env vive en la raíz del proyecto (un nivel por encima de /web)
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

import avisos
import copias
import correo
import db
import eventos
import google_cal
import resumen
import telegram_bot
from whatsapp import whatsapp_bp

app = Flask(__name__)
app.register_blueprint(whatsapp_bp)


@app.context_processor
def datos_comunes():
    return {'persona_defecto': db.persona_por_defecto(), 'nombre_usuario': os.getenv('NOMBRE_USUARIO', '').strip()}


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
    }


def canales_recordatorio():
    """Chats a los que se pueden mandar avisos desde la web: los de WhatsApp y Telegram configurados."""
    whatsapp = [n.strip() for n in os.getenv('WHATSAPP_ALLOWED_NUMBERS', '').split(',') if n.strip()]         if os.getenv('TOKEN') and os.getenv('WHATSAPP_PHONE_NUMBER_ID') else []
    telegram = [u.strip() for u in os.getenv('TELEGRAM_ALLOWED_USERS', '').split(',') if u.strip().isdigit()]         if os.getenv('TELEGRAM_TOKEN') else []
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
    """Valida lo que manda la web. Devuelve (texto, cuando, destino) o lanza ValueError."""
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
            texto, cuando, destino = leer_recordatorio(request.get_json(silent=True) or {})
        except db.DatosNoValidos as error:
            return jsonify({'error': error.mensaje}), 400
        nuevo = db.crear_recordatorio(destino, texto, cuando)
        return jsonify(recordatorio_a_json(db.obtener_recordatorio(nuevo))), 201
    return jsonify([recordatorio_a_json(r) for r in db.listar_recordatorios()])


@app.route('/api/recordatorios/canales')
def recordatorios_canales():
    return jsonify(canales_recordatorio())


@app.route('/api/recordatorios/<int:recordatorio_id>', methods=['PUT', 'DELETE'])
def recordatorio_api(recordatorio_id):
    recordatorio = db.obtener_recordatorio(recordatorio_id)
    if recordatorio is None or recordatorio['estado'] == 'cancelado':
        return jsonify({'error': 'Recordatorio no encontrado'}), 404

    if request.method == 'DELETE':
        db.actualizar_recordatorio(recordatorio_id, 'cancelado')
        return '', 204

    try:
        texto, cuando, destino = leer_recordatorio(request.get_json(silent=True) or {}, recordatorio['destino'])
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 400

    db.editar_recordatorio(recordatorio_id, texto, cuando, destino)
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

    return jsonify(task), 201


@app.route('/api/tareas/<task_id>', methods=['PUT', 'DELETE'])
def tarea_api(task_id):
    if request.method == 'DELETE':
        if not db.delete_task(task_id):
            return jsonify({'error': 'Tarea no encontrada'}), 404
        return '', 204

    payload = request.get_json(silent=True) or {}

    try:
        task = db.update_task(task_id, payload)
    except db.DatosNoValidos as error:
        return jsonify({'error': error.mensaje}), 400

    if task is None:
        return jsonify({'error': 'Tarea no encontrada'}), 404

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
