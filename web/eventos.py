"""Eventos del calendario (clases, cumpleaños...): validación y cálculo de repeticiones."""
from datetime import date, datetime, timedelta

import db

CATEGORIAS = ['Clase', 'Cumpleaños', 'Reunión', 'Examen', 'Otro']
REPETICIONES = {'': 'No se repite', 'semanal': 'Cada semana', 'anual': 'Cada año'}
EMOJI_CATEGORIA = {'Clase': '📚', 'Cumpleaños': '🎂', 'Reunión': '👥', 'Examen': '📝', 'Otro': '📌'}


def _hora(valor, campo):
    valor = (valor or '').strip()[:5]
    if valor:
        try:
            datetime.strptime(valor, '%H:%M')
        except ValueError as error:
            raise ValueError(f'{campo} no válida (usa HH:MM)') from error
    return valor


def validar(datos):
    """Normaliza los datos de un evento o lanza ValueError con un mensaje para el usuario."""
    titulo = (datos.get('titulo') or '').strip()
    if not titulo:
        raise ValueError('El evento necesita un título')

    categoria = datos.get('categoria') or 'Otro'
    if categoria not in CATEGORIAS:
        raise ValueError(f'Categoría no válida. Usa una de: {", ".join(CATEGORIAS)}')

    try:
        fecha = date.fromisoformat(datos.get('fecha') or '')
    except ValueError as error:
        raise ValueError('Fecha no válida') from error

    hora_inicio = _hora(datos.get('hora_inicio'), 'Hora de inicio')
    hora_fin = _hora(datos.get('hora_fin'), 'Hora de fin')
    if hora_fin and not hora_inicio:
        raise ValueError('Si pones hora de fin, pon también la de inicio')
    if hora_fin and hora_fin <= hora_inicio:
        raise ValueError('La hora de fin debe ser posterior a la de inicio')

    repeticion = datos.get('repeticion') or ''
    if repeticion not in REPETICIONES:
        raise ValueError('Repetición no válida')

    hasta = (datos.get('hasta') or '') if repeticion == 'semanal' else ''
    if hasta:
        try:
            fin = date.fromisoformat(hasta)
        except ValueError as error:
            raise ValueError('Fecha de fin no válida') from error
        if fin < fecha:
            raise ValueError('La fecha de fin de la repetición es anterior al inicio')

    return {'titulo': titulo, 'categoria': categoria, 'fecha': fecha.isoformat(), 'hora_inicio': hora_inicio,
            'hora_fin': hora_fin, 'repeticion': repeticion, 'hasta': hasta}


def _mismo_dia_en(anio, fecha):
    """El 29 de febrero se celebra el 28 en los años no bisiestos."""
    try:
        return fecha.replace(year=anio)
    except ValueError:
        return fecha.replace(year=anio, day=28)


def _fechas(evento, desde, hasta):
    inicio = date.fromisoformat(evento['fecha'])
    if evento['repeticion'] == 'semanal':
        if evento['hasta']:
            hasta = min(hasta, date.fromisoformat(evento['hasta']))
        primera = inicio if desde <= inicio else inicio + timedelta(weeks=-(-(desde - inicio).days // 7))
        while primera <= hasta:
            yield primera
            primera += timedelta(weeks=1)
    elif evento['repeticion'] == 'anual':
        for anio in range(max(desde.year, inicio.year), hasta.year + 1):
            dia = _mismo_dia_en(anio, inicio)
            if desde <= dia <= hasta:
                yield dia
    elif desde <= inicio <= hasta:
        yield inicio


def en_rango(desde, hasta):
    """Ocurrencias de todos los eventos entre dos fechas (incluidas), ordenadas por fecha y hora.

    Cada ocurrencia es el evento con 'fecha' = el día concreto y 'fecha_inicio' = la fecha original.
    """
    ocurrencias = []
    excepciones = db.excepciones_por_evento()
    for evento in db.listar_eventos():
        quitados = excepciones.get(evento['id'], set())
        for dia in _fechas(evento, desde, hasta):
            if dia.isoformat() not in quitados:
                ocurrencias.append(dict(evento, fecha=dia.isoformat(), fecha_inicio=evento['fecha']))
    return sorted(ocurrencias, key=lambda e: (e['fecha'], e['hora_inicio'] or '99', e['titulo']))


def horario(evento):
    if evento['hora_inicio'] and evento['hora_fin']:
        return f'{evento["hora_inicio"]}–{evento["hora_fin"]}'
    return evento['hora_inicio']


ALCANCES = ('uno', 'siguientes', 'serie')


def ocurre_el(evento, dia):
    """True si el evento (con sus repeticiones) cae ese día."""
    return any(True for _ in _fechas(evento, dia, dia))


def proxima_ocurrencia(evento, desde):
    """Primer día en que cae el evento a partir de `desde` (sin contar los días quitados), o None."""
    quitados = db.excepciones_por_evento().get(evento['id'], set())
    for dia in _fechas(evento, desde, desde + timedelta(days=800)):
        if dia.isoformat() not in quitados:
            return dia
    return None


def borrar(evento, alcance='serie', dia=None):
    """Borra un evento: solo un día ('uno'), ese día y los siguientes ('siguientes') o toda la serie."""
    if alcance == 'serie' or not evento['repeticion']:
        db.borrar_evento(evento['id'])
        return
    if dia is None or not ocurre_el(evento, dia):
        raise ValueError('Ese día no hay ninguna repetición de este evento')
    if alcance == 'uno':
        db.anadir_excepcion(evento['id'], dia)
    elif alcance == 'siguientes':
        if evento['repeticion'] != 'semanal':
            raise ValueError('«Este y los siguientes» solo vale para eventos semanales')
        if dia <= date.fromisoformat(evento['fecha']):
            db.borrar_evento(evento['id'])  # desde el primero: es toda la serie
        else:
            db.guardar_evento(dict(evento, hasta=(dia - timedelta(days=1)).isoformat()), evento['id'])
    else:
        raise ValueError('Alcance no válido')


def modificar(evento, datos, alcance='serie', dia=None):
    """Guarda los cambios de un evento. Devuelve el id del evento resultante.

    'uno': ese día se quita de la serie y se crea un evento suelto con los cambios.
    'siguientes': la serie termina el día anterior y empieza una nueva desde ese día con los cambios.
    """
    if alcance == 'serie' or not evento['repeticion']:
        return db.guardar_evento(validar(datos), evento['id'])
    if dia is None or not ocurre_el(evento, dia):
        raise ValueError('Ese día no hay ninguna repetición de este evento')
    if alcance == 'uno':
        nuevo = validar(dict(datos, repeticion='', hasta=''))
        db.anadir_excepcion(evento['id'], dia)
        return db.guardar_evento(nuevo)
    if alcance == 'siguientes':
        if evento['repeticion'] != 'semanal':
            raise ValueError('«Este y los siguientes» solo vale para eventos semanales')
        nuevo = validar(dict(datos, fecha=datos.get('fecha') or dia.isoformat()))
        borrar(evento, 'siguientes', dia)
        return db.guardar_evento(nuevo)
    raise ValueError('Alcance no válido')
