from datetime import date, datetime
from pathlib import Path
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

# El .env vive en la raíz del proyecto (un nivel por encima de /web)
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

import avisos
import copias
import db
import eventos
import google_cal
import telegram_bot
from whatsapp import whatsapp_bp

app = Flask(__name__)
app.register_blueprint(whatsapp_bp)


@app.context_processor
def datos_comunes():
    return {'persona_defecto': db.persona_por_defecto()}


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


def recordatorio_a_json(recordatorio):
    return {
        'id': recordatorio['id'],
        'texto': recordatorio['texto'],
        # Formato que entiende <input type="datetime-local">
        'cuando': recordatorio['cuando'].replace(' ', 'T'),
        'estado': recordatorio['estado'],
        'canal': 'Telegram' if recordatorio['destino'].startswith('tg:') else 'WhatsApp',
    }


@app.route('/api/eventos', methods=['GET', 'POST'])
def eventos_api():
    if request.method == 'POST':
        try:
            datos = eventos.validar(request.get_json(silent=True) or {})
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
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
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
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
    except Exception as error:  # el detalle queda en el estado y en el log
        return jsonify({**google_cal.estado, 'configurado': True, 'error': str(error)}), 502
    return jsonify({**google_cal.estado, 'configurado': True})


@app.route('/api/recordatorios', methods=['GET'])
def recordatorios_api():
    return jsonify([recordatorio_a_json(r) for r in db.listar_recordatorios()])


@app.route('/api/recordatorios/<int:recordatorio_id>', methods=['PUT', 'DELETE'])
def recordatorio_api(recordatorio_id):
    recordatorio = db.obtener_recordatorio(recordatorio_id)
    if recordatorio is None or recordatorio['estado'] == 'cancelado':
        return jsonify({'error': 'Recordatorio no encontrado'}), 404

    if request.method == 'DELETE':
        db.actualizar_recordatorio(recordatorio_id, 'cancelado')
        return '', 204

    payload = request.get_json(silent=True) or {}
    texto = (payload.get('texto') or '').strip()
    if not texto:
        return jsonify({'error': 'El recordatorio necesita un texto'}), 400
    try:
        cuando = datetime.strptime((payload.get('cuando') or '')[:16], '%Y-%m-%dT%H:%M')
    except ValueError:
        return jsonify({'error': 'Fecha y hora no válidas'}), 400
    if cuando <= datetime.now():
        return jsonify({'error': 'La fecha y hora deben ser futuras'}), 400

    db.editar_recordatorio(recordatorio_id, texto, cuando)
    return jsonify(recordatorio_a_json(db.obtener_recordatorio(recordatorio_id)))


@app.route('/api/tareas', methods=['GET', 'POST'])
def tareas_api():
    if request.method == 'GET':
        return jsonify(db.fetch_all_tasks())

    payload = request.get_json(silent=True) or {}

    try:
        task = db.insert_task(payload)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

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
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

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

if __name__ == '__main__':
    # Desarrollo en local. En el servidor se ejecuta con Docker (ver docker-compose.yml)
    app.run(debug=os.getenv('FLASK_DEBUG') == '1')
