"""LLM local servido por Ollama (https://ollama.com) en tu propio servidor.

Solo se usa para los mensajes que el motor de reglas no entiende.
"""
from datetime import date
import json
import logging
import os

import requests

import db
import herramientas
from fechas import DIAS_SEMANA_BONITOS

log = logging.getLogger(__name__)

MAX_ITERACIONES = 5

SYSTEM_PROMPT = f"""Eres un asistente de organización personal que habla por WhatsApp.
Gestionas la lista de tareas del usuario usando SOLO las herramientas disponibles.

Campos de una tarea:
- nombre (texto corto)
- importancia: {', '.join(db.IMPORTANCIAS)}
- status: {', '.join(db.ESTADOS)}
- fecha_limite: AAAA-MM-DD o vacío
- persona: persona encargada

Reglas:
- Convierte fechas relativas ("mañana", "el viernes") a AAAA-MM-DD usando la fecha de hoy.
- Para modificar o borrar una tarea, primero usa listar_tareas para obtener su id. Nunca inventes ids.
- Si varias tareas encajan, pregunta cuál antes de cambiar nada.
- Si no se indica importancia al crear, usa Media.
- No inventes tareas: lo que digas debe salir de las herramientas.
- Responde en español, breve y cercano. Sin tablas ni títulos. Fechas como dd/mm."""


def _herramienta(nombre, descripcion, propiedades, requeridos=()):
    return {
        'type': 'function',
        'function': {
            'name': nombre,
            'description': descripcion,
            'parameters': {'type': 'object', 'properties': propiedades, 'required': list(requeridos)},
        },
    }


_CAMPOS = {
    'nombre': {'type': 'string'},
    'importancia': {'type': 'string', 'enum': db.IMPORTANCIAS},
    'fecha_limite': {'type': 'string', 'description': 'AAAA-MM-DD, o "" para quitarla'},
    'hora_limite': {'type': 'string', 'description': 'HH:MM, opcional (requiere fecha_limite)'},
    'persona': {'type': 'string'},
    'status': {'type': 'string', 'enum': db.ESTADOS},
}

TOOLS = [
    _herramienta(
        'listar_tareas',
        'Lista tareas con su id. Filtros opcionales. Por defecto oculta las Terminado.',
        {
            'status': {'type': 'string', 'enum': db.ESTADOS},
            'importancia': {'type': 'string', 'enum': db.IMPORTANCIAS},
            'persona': {'type': 'string'},
            'texto': {'type': 'string', 'description': 'Texto contenido en el nombre'},
            'fecha_limite_desde': {'type': 'string', 'description': 'AAAA-MM-DD'},
            'fecha_limite_hasta': {'type': 'string', 'description': 'AAAA-MM-DD'},
            'incluir_terminadas': {'type': 'boolean'},
        },
    ),
    _herramienta('crear_tarea', 'Crea una tarea nueva.', _CAMPOS, ['nombre']),
    _herramienta('actualizar_tarea', 'Cambia los campos indicados de una tarea. Para completarla: status Terminado.',
                 dict(_CAMPOS, id={'type': 'string'}), ['id']),
    _herramienta('eliminar_tarea', 'Borra una tarea por su id.', {'id': {'type': 'string'}}, ['id']),
]

# Nombres de argumento válidos por herramienta: los modelos pequeños a veces se inventan otros
_ARGUMENTOS = {t['function']['name']: set(t['function']['parameters']['properties']) for t in TOOLS}


def _chat(mensajes):
    url = os.getenv('OLLAMA_URL', 'http://localhost:11434').rstrip('/')
    respuesta = requests.post(
        f'{url}/api/chat',
        json={
            'model': os.getenv('OLLAMA_MODEL', 'qwen2.5:7b'),
            'messages': mensajes,
            'tools': TOOLS,
            'stream': False,
            'keep_alive': '30m',  # mantiene el modelo cargado en memoria entre mensajes
            'options': {'temperature': 0.2},
        },
        timeout=int(os.getenv('OLLAMA_TIMEOUT', '180')),
    )
    respuesta.raise_for_status()
    return respuesta.json()['message']


def _ejecutar(llamada):
    funcion = llamada.get('function', {})
    nombre = funcion.get('name', '')
    argumentos = funcion.get('arguments') or {}
    if isinstance(argumentos, str):
        argumentos = json.loads(argumentos or '{}')

    permitidos = _ARGUMENTOS.get(nombre, set())
    argumentos = {k: v for k, v in argumentos.items() if k in permitidos and v is not None}

    try:
        resultado = herramientas.ejecutar(nombre, argumentos)
        return nombre, json.dumps(resultado, ensure_ascii=False)
    except ValueError as error:
        return nombre, f'Error: {error}'


def disponible():
    return os.getenv('OLLAMA_ENABLED', 'false').lower() not in ('0', 'false', 'no')


def responder(telefono, texto):
    """Devuelve la respuesta del LLM, o None si Ollama no está disponible."""
    hoy = date.today()
    sistema = f'{SYSTEM_PROMPT}\n\nHoy es {DIAS_SEMANA_BONITOS[hoy.weekday()]} {hoy.isoformat()}.'
    mensajes = [{'role': 'system', 'content': sistema}, *db.historial(telefono, limite=10),
                {'role': 'user', 'content': texto}]

    try:
        for _ in range(MAX_ITERACIONES):
            mensaje = _chat(mensajes)
            llamadas = mensaje.get('tool_calls') or []
            if not llamadas:
                return (mensaje.get('content') or '').strip() or None

            mensajes.append(mensaje)
            for llamada in llamadas:
                nombre, resultado = _ejecutar(llamada)
                mensajes.append({'role': 'tool', 'tool_name': nombre, 'content': resultado})
    except (requests.RequestException, KeyError, ValueError) as error:
        log.warning('Ollama no disponible o respuesta no válida: %s', error)
        return None

    return 'Me he liado con esta petición. ¿Puedes decírmelo de otra forma?'
