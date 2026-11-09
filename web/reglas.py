"""Motor de reglas: reconoce las peticiones habituales sin necesidad de un modelo de lenguaje.

`interpretar()` devuelve un diccionario con la intención o None si no está seguro;
en ese caso el mensaje pasa al LLM local.
"""
from datetime import datetime
import re

from fechas import (extraer_fecha, extraer_horario, extraer_momento, extraer_repeticion, normalizar, proximo_dia,
                    proximo_dia_del_mes, rango_periodo)

# Artículos y muletillas que pueden ir delante del nombre de una tarea
_OBJETO = r'(?:(?:la|el|lo|las)\s+)?(?:tarea\s+)?(?:(?:de|del|que)\s+)?'
_PERIODO = (r'(?P<periodo>hoy|manana|pasado\s+manana|esta\s+semana|(?:la\s+)?semana\s+que\s+viene|'
            r'(?:la\s+)?proxima\s+semana|este\s+mes|(?:este|el)\s+(?:fin\s+de\s+semana|finde))')
_FIN = r'[\s?!.¿¡]*$'

SALUDO = re.compile(r'^(?:hola|buenas|buenos\s+dias|buenas\s+(?:tardes|noches)|hey|ey)\b[\s,!.]*(?:que\s+tal)?' + _FIN)
GRACIAS = re.compile(r'^(?:gracias|muchas\s+gracias|perfecto|genial|guay)' + _FIN)
AFIRMACION = re.compile(r'^(?:si|sip|ok|vale|dale|adelante|confirmo|claro|venga|de\s+acuerdo|hazlo|borrala)' + _FIN)
AYUDA = re.compile(r'^(?:ayuda|help|\?|menu|comandos|que\s+puedes\s+hacer|como\s+funcionas)' + _FIN)
SELECCION = re.compile(r'^(?:la\s+|el\s+|opcion\s+)?(?P<num>[1-9]|primera|segunda|tercera|cuarta|quinta)' + _FIN)
TODOS = re.compile(r'^(?:todos|todas|ambos|ambas|los\s+dos|las\s+dos|todo)' + _FIN)
# "deshaz", "deshazlo", "me he equivocado", "vuelve atrás", "deshaz lo último"...
DESHACER = re.compile(r'^(?:(?:me\s+he\s+equivocado|me\s+equivoque|ups|uy)[\s,.!]*)?'
                      r'(?:(?:deshaz|deshazlo|deshacer|deshace|desaz|desazlo)'
                      r'(?:\s+(?:eso|esto|lo\s+ultimo|el\s+ultimo\s+\w+|lo\s+que\s+(?:has\s+hecho|acabas\s+de\s+hacer)))?'
                      r'|vuelve\s+atras|marcha\s+atras|undo|ctrl\s*\+?\s*z|anula\s+(?:eso|lo\s+ultimo)'
                      r'|revierte(?:lo)?(?:\s+(?:eso|lo\s+ultimo))?|me\s+he\s+equivocado|me\s+equivoque)' + _FIN)
NEGACION = re.compile(r'^(?:no|ninguna|nada|cancela|cancelar|dejalo|olvidalo)' + _FIN)

LISTAR = [
    re.compile(r'^(?:y\s+)?(?:que|q)\s+(?:tengo|hay|me\s+queda|tengo\s+pendiente)(?:\s+(?:que\s+hacer|pendiente|para))?'
               rf'(?:\s+{_PERIODO})?' + _FIN),
    re.compile(r'^(?:(?:dime|ensename|muestrame|ver|lista(?:\s+de)?)\s+)?(?:(?:mis|las)\s+)?(?:tareas|pendientes|agenda)'
               rf'(?:\s+pendientes)?(?:\s+(?:de|para))?(?:\s+{_PERIODO})?' + _FIN),
    re.compile(r'^(?:(?:que\s+)?tareas\s+(?:tengo\s+)?)?(?P<filtro>atrasadas|vencidas|retrasadas|urgentes|importantes|en\s+curso)' + _FIN),
]

CREAR = re.compile(r'^(?:por\s+favor\s+)?(?:anade(?:me)?|apunta(?:me)?|agrega(?:me)?|crea(?:me)?|nueva\s+tarea|'
                   r'tengo\s+que|hay\s+que|tarea)\s*[:,-]?\s+(?P<resto>.+)$')

_HECHA = r'(?:hecha|hecho|terminada|terminado|completada|completado|acabada|lista)'
COMPLETAR = [
    re.compile(rf'^(?:marca|marcar|pon|poner)\s+(?:como\s+)?{_HECHA}\s+{_OBJETO}(?P<objeto>.+)$'),
    re.compile(rf'^(?:marca|marcar|pon|poner)\s+{_OBJETO}(?P<objeto>.+?)\s+(?:como\s+)?{_HECHA}' + _FIN),
    re.compile(rf'^(?:ya\s+)?(?:he\s+(?:terminado|acabado|hecho|completado)|termine|acabe|hice|complete|completa|termina|terminar|completar)'
               rf'\s+(?:con\s+)?{_OBJETO}(?P<objeto>.+)$'),
    re.compile(rf'^{_OBJETO}(?P<objeto>.+?)\s+(?:ya\s+(?:esta\s+)?|esta\s+){_HECHA}' + _FIN),
]
EMPEZAR = [
    re.compile(rf'^(?:empiezo|empiezo\s+con|empezar|comienzo|me\s+pongo\s+con|estoy\s+con|estoy\s+haciendo)\s+(?:con\s+)?{_OBJETO}(?P<objeto>.+)$'),
    re.compile(rf'^(?:marca|pon)\s+{_OBJETO}(?P<objeto>.+?)\s+(?:como\s+)?en\s+curso' + _FIN),
]
BORRAR = re.compile(rf'^(?:borra|borrar|elimina|eliminar|quita|quitar|cancela|cancelar)\s+{_OBJETO}(?P<objeto>.+)$')
# "mueve X al lunes", "cambia la cena a las 22", "pasa la clase de mates del lunes al martes de 9 a 11"
_VERBO_MOVER = re.compile(r'^(?:mueve|mover|cambia|cambiar|pasa|pasar|aplaza|aplazar|retrasa|retrasar|adelanta|'
                          r'adelantar|pon|poner)\s+')
_CORTE_MOVER = re.compile(r'\s(?=(?:a|al|para|hasta|de)\s)')
_CONECTORES_MOVER = {'a', 'al', 'para', 'el', 'la', 'las', 'hasta', 'de', 'y'}
_QUE_CAMBIAR = re.compile(r'(?:la\s+)?(?:hora|fecha|dia)\s+(?:de\s+(?:la\s+|el\s+|lo\s+de\s+)?|del\s+)')
RENOMBRAR = [
    re.compile(rf'^(?:cambia|cambiar|pon|poner)\s+(?:el\s+)?(?:nombre|titulo)\s+(?:de|del|a|al)\s+{_OBJETO}'
               rf'(?P<objeto>.+?)\s+(?:a|por|como|en)\s+(?P<nuevo>.+?)' + _FIN),
    re.compile(rf'^(?:renombra|renombrar)\s+{_OBJETO}(?P<objeto>.+?)\s+(?:a|como|por)\s+(?P<nuevo>.+?)' + _FIN),
]
# Debe ir antes que BORRAR: "quita la fecha del informe" no es borrar la tarea
QUITAR_FECHA = re.compile(rf'^(?:quita|quitar|elimina|eliminar|borra|borrar)\s+(?:la\s+)?fecha(?:\s+limite)?\s+'
                          rf'(?:de|del|a|al)\s+{_OBJETO}(?P<objeto>.+)$')

_NIVEL = r'(?P<imp>alta|media|baja|urgente|importante)'
CAMBIAR_IMPORTANCIA = [
    re.compile(rf'^(?:cambia|cambiar|pon|poner|sube|subir|baja|bajar)\s+(?:la\s+)?(?:importancia|prioridad)\s+(?:de\s+|del\s+|a\s+|al\s+)?'
               rf'{_OBJETO}(?P<objeto>.+?)\s+(?:a|en)\s+{_NIVEL}' + _FIN),
    re.compile(rf'^(?:pon|poner|marca|marcar)\s+{_OBJETO}(?P<objeto>.+?)\s+(?:como\s+|con\s+(?:importancia|prioridad)\s+|a\s+|en\s+){_NIVEL}' + _FIN),
    re.compile(rf'^{_OBJETO}(?P<objeto>.+?)\s+es\s+(?:muy\s+)?{_NIVEL}' + _FIN),
]
ASIGNAR = [
    re.compile(rf'^(?:asigna|asignar|asignale|pasale|pasa|pasar|dale|encarga|encargale)\s+{_OBJETO}(?P<objeto>.+?)\s+a\s+(?P<persona>[a-z]+)' + _FIN),
    re.compile(rf'^(?P<persona>[a-z]+)\s+se\s+(?:encarga|ocupa)\s+de\s+{_OBJETO}(?P<objeto>.+?)' + _FIN),
]

# "¿qué tengo el viernes?" / "tareas para el 3 de noviembre": cualquier fecha que entienda extraer_fecha
LISTAR_FECHA = re.compile(r'^(?:y\s+)?(?:que\s+(?:tengo|hay)|(?:mis\s+)?tareas)\s+(?:(?:pendientes|para)\s+)?(?P<cuando>.+?)' + _FIN)
LISTAR_ALGO = re.compile(r'^(?:y\s+)?(?:si\s+)?(?:tengo|tenemos|hay)\s+(?:algo|alguna\s+cosa|planes?|cosas?|mucho|algun\s+evento)'
                         r'(?:\s+(?:para|que\s+hacer))?\s+(?P<cuando>.+?)' + _FIN)
LISTAR_PERSONA = [
    re.compile(r'^(?:y\s+)?(?:que|cuantas)\s+(?:tareas\s+)?(?:tiene|le\s+quedan\s+a)\s+(?:pendiente\s+)?(?P<persona>[a-z]+)' + _FIN),
    re.compile(r'^(?:(?:las|ver)\s+)?tareas\s+(?:de|asignadas\s+a)\s+(?P<persona>[a-z]+)' + _FIN),
]

_NIVELES = r'(alta|media|baja|maxima|normal)'
IMPORTANCIA = [
    # "importancia alta", "con prioridad baja", "importancia: alta", "de prioridad media"
    re.compile(r'(?:,\s*)?(?:(?:con|de)\s+)?(?:importancia|prioridad)\s*:?\s*' + _NIVELES + r'\b'),
    # "alta importancia", "de baja prioridad"
    re.compile(r'(?:,\s*)?(?:(?:con|de)\s+)?' + _NIVELES + r'\s+(?:importancia|prioridad)\b'),
    # "urgente", "es importante", "sin prisa"
    re.compile(r'(?:,\s*)?(?:(?:es|muy)\s+)*\b(urgente|importante|sin\s+prisa|poco\s+importante|no\s+urgente)\b'),
    # ", alta" al final (solo tras coma, para no confundir "persiana baja")
    re.compile(r',\s*' + _NIVELES + r'\s*$'),
]
VALOR_IMPORTANCIA = {'alta': 'Alta', 'maxima': 'Alta', 'urgente': 'Alta', 'importante': 'Alta',
                     'media': 'Media', 'normal': 'Media',
                     'baja': 'Baja', 'sin prisa': 'Baja', 'poco importante': 'Baja', 'no urgente': 'Baja'}
PERSONA = re.compile(r'(?:,\s*)?\b(?:asignada\s+a|asignala\s+a|encargad[oa]|responsable)\s*:?\s+(\w+)')

RECORDATORIO = re.compile(r'^(?:por\s+favor\s+)?(?:recuerda(?:me)?|avisa(?:me)?|'
                          r'pon(?:me)?\s+un\s+(?:recordatorio|aviso)|recordatorio|aviso)\b\s*[:,-]?\s*(?P<resto>.+)$')
LISTAR_RECORDATORIOS = re.compile(r'^(?:(?:que|mis|ver|los|lista\s+de)\s+)?(?:recordatorios|avisos)'
                                  r'(?:\s+(?:tengo|pendientes|hay|tengo\s+pendientes))?' + _FIN)
CANCELAR_RECORDATORIO = re.compile(r'^(?:borra|borrar|elimina|eliminar|quita|quitar|cancela|cancelar|anula|anular)\s+'
                                   r'(?:el\s+|ese\s+)?(?:recordatorio|aviso)\s*(?:de\s+(?:la\s+|el\s+|lo\s+de\s+)?|del\s+|que\s+)?'
                                   r'(?P<objeto>.*?)' + _FIN)
# Separa "cuándo" de "qué": "mañana a las 10 que…", "a las 8: tomar pastilla". Una coma o unos dos
# puntos entre números son parte de la hora ("11:00", "9,30"), no un separador
_SEPARADOR = re.compile(r'\s+(?:de\s+que|que|para\s+que)\s+|\s*(?<!\d)[,:;]\s*|\s*[,:;](?!\d)\s*')

LISTAR_EVENTOS = re.compile(r'^(?:y\s+)?(?:(?:que|mis|los|las|ver)\s+)?(?P<tipo>eventos|clases|cumpleanos|cumples|examenes)'
                            r'(?:\s+(?:tengo|hay))?(?:\s+(?:de|para))?(?:\s+' + _PERIODO + r')?' + _FIN)
CATEGORIA_POR_PALABRA = {'clases': 'Clase', 'cumpleanos': 'Cumpleaños', 'cumples': 'Cumpleaños', 'examenes': 'Examen'}

# Eventos del calendario
EVENTO_EXPLICITO = re.compile(
    r'^(?:por\s+favor\s+)?(?:(?:anade|apunta|pon|mete|agrega|guarda)(?:me)?\s+(?:en\s+el|al)\s+calendario|'
    r'(?:crea|anade|apunta|pon|agrega)(?:me)?\s+(?:un\s+)?evento|nuevo\s+evento|evento|'
    r'reserva(?:r|me|nos)?(?:\s+en\s+el\s+calendario)?)\s*[:,-]?\s*(?:que\s+)?(?P<resto>.+)$')
EVENTO_CUMPLE = re.compile(r'^(?:el\s+|mi\s+)?(?P<resto>(?:cumple|cumpleanos)\s+(?:de|del)\s+.+)$')
EVENTO_TENGO = re.compile(r'^(?:tengo|tenemos|hay)\s+(?!que\b)(?P<resto>.+)$')
BORRAR_EVENTO = [
    re.compile(r'^(?:borra|borrar|elimina|eliminar|quita|quitar|cancela|cancelar)\s+(?:el\s+)?evento\s+'
               r'(?:de\s+(?:la\s+|el\s+|lo\s+de\s+)?|del\s+)?(?P<objeto>.+?)' + _FIN),
    re.compile(r'^(?:borra|borrar|elimina|eliminar|quita|quitar)\s+(?:la\s+|el\s+|lo\s+de\s+)?(?P<objeto>.+?)\s+del\s+calendario' + _FIN),
]
CATEGORIA_EVENTO = [
    (re.compile(r'\b(?:clase|clases)\b'), 'Clase'),
    (re.compile(r'\b(?:cumple|cumpleanos)\b'), 'Cumpleaños'),
    (re.compile(r'\b(?:examen|parcial|recuperacion)\b'), 'Examen'),
    (re.compile(r'\b(?:reunion|tutoria|quedada|cita)\b'), 'Reunión'),
]

# "la tarde del jueves", "el viernes por la mañana": tramo del día cuando no se da una hora exacta
_FRANJA_EVENTO = re.compile(r'\b(?:(?:por|durante|toda)\s+)?la\s+(?P<franja>manana|tarde|noche)\b(?:\s+del?\b)?')
TRAMO_FRANJA = {'manana': ('09:00', '14:00'), 'tarde': ('16:00', '20:00'), 'noche': ('20:00', '23:00')}
# "2 horas", "una hora", "media hora", "hora y media", "90 minutos"
_DURACION = re.compile(r'\b(?:(?:durante|por)\s+)?(?:(?P<n>\d+|una|un)\s+(?P<unidad>horas?|minutos?)(?P<ymedia>\s+y\s+media)?'
                       r'|(?P<media>media\s+hora)|(?P<horaymedia>hora\s+y\s+media))\b')
# Relleno típico al reservar: "resérvame un hueco el viernes..."
_RELLENO_RESERVA = re.compile(r'\b(?:un\s+|el\s+)?(?:hueco|rato|ratito|tiempo|espacio|bloque)\b')

ORDINALES = {'primera': 1, 'segunda': 2, 'tercera': 3, 'cuarta': 4, 'quinta': 5}


def _recortar(original, inicio, fin):
    """Devuelve el trozo del texto original equivalente a normal[inicio:fin]."""
    return original[inicio:fin].strip(' ,.;:-')


def _persona(texto):
    """Nombre de persona tal como se guarda: "a mí", "yo"... es la persona por defecto ("Yo")."""
    if normalizar(texto).strip() in ('yo', 'mi', 'me', 'mio', 'mia', 'nosotros'):
        import db  # se importa aquí: el motor de reglas no necesita la base de datos para nada más
        return db.persona_por_defecto()
    return texto.strip().capitalize()


def _palabra(original, m, grupo):
    return _persona(original[m.start(grupo):m.end(grupo)])


def _es_solo_fecha(texto, hoy):
    """True si el texto es una fecha y nada más ('el viernes', 'el 3 de noviembre')."""
    fecha, sobrante = extraer_fecha(texto, hoy)
    return fecha is not None and not sobrante.strip(' .!?')


def _quitar(original, m):
    return (original[:m.start()] + ' ' + original[m.end():]).strip()


def _interpretar_edicion(original, normal, hoy, ahora):
    """'mueve X al lunes a las 10' -> qué (X) y a cuándo; vale para tareas y para eventos.

    Se prueba a cortar por cada "a / al / para / hasta / de" y se queda el primer corte cuya parte
    derecha es solo una fecha y/o una hora: así "la clase de mates de 10 a 12" no corta en "de mates".
    """
    m = _VERBO_MOVER.match(normal)
    if not m:
        return None
    for corte in _CORTE_MOVER.finditer(normal, m.end()):
        derecha = original[corte.end():]
        separador = normal[corte.end():].split()[0]
        # "a los martes": toda la serie pasa a ese día de la semana
        semanal = re.match(r'(?:a\s+)?los\s+(?=(?:lunes|martes|miercoles|jueves|viernes|sabados?|domingos?)\b)',
                           normalizar(derecha))
        if semanal:
            derecha = 'el ' + re.sub(r'(?i)^(s[aá]bado|domingo)s\b', r'\1', derecha[semanal.end():])
        hora_inicio, hora_fin, resto = extraer_horario(derecha)
        fecha, resto = extraer_fecha(resto, hoy)
        if not (fecha or hora_inicio) or set(re.findall(r'\w+', normalizar(resto))) - _CONECTORES_MOVER:
            continue
        if separador == 'de' and not hora_fin:
            continue  # "de" solo vale para un horario: "de 10 a 12"

        inicio = m.end()
        que = _QUE_CAMBIAR.match(normal, inicio, corte.start())  # "cambia la hora de la cena..."
        if que:
            inicio = que.end()
        inicio = re.compile(_OBJETO).match(normal, inicio, corte.start()).end()
        objeto = _recortar(original, inicio, corte.start())
        if not objeto:
            return None

        accion = {'intencion': 'mover', 'objeto': objeto, 'fecha': fecha.isoformat() if fecha else '',
                  'hora_inicio': hora_inicio, 'hora_fin': hora_fin, 'todas': bool(semanal)}
        if fecha:
            accion['fecha_limite'] = fecha.isoformat()
        else:
            # Solo la hora: una tarea sin fecha se pone para la próxima vez que llegue esa hora
            momento, _ = extraer_momento(derecha, ahora)
            accion['fecha_si_no_hay'] = (momento.date() if momento else hoy).isoformat()
        if hora_inicio:
            accion['hora_limite'] = hora_inicio
        return accion
    return None


def _interpretar_creacion(original, hoy, ahora):
    """Saca nombre, fecha, hora, importancia y persona de 'entregar la práctica el viernes a las 14, urgente'."""
    texto = original
    importancia = 'Media'
    persona = ''

    for patron in IMPORTANCIA:
        m = patron.search(normalizar(texto))
        if m:
            importancia = VALOR_IMPORTANCIA[re.sub(r'\s+', ' ', m.group(1))]
            texto = _quitar(texto, m)
            break

    m = PERSONA.search(normalizar(texto))
    if m:
        persona = _persona(texto[m.start(1):m.end(1)])
        texto = _quitar(texto, m)

    hora = ''
    momento, resto = extraer_momento(texto, ahora)
    if momento:
        fecha, hora, texto = momento.date(), f'{momento:%H:%M}', resto
    else:
        fecha, texto = extraer_fecha(texto, hoy)

    nombre = re.sub(r'\s{2,}', ' ', texto).strip(' ,.;:-')
    nombre = re.sub(r'(?i)\s+(?:para|el|de|y)$', '', nombre)
    if not nombre:
        return None

    return {
        'nombre': nombre[0].upper() + nombre[1:],
        'importancia': importancia,
        'fecha_limite': fecha.isoformat() if fecha else '',
        'hora_limite': hora,
        'persona': persona,
    }


def _quitar_patron(texto, patron):
    """Quita la primera coincidencia del patrón (buscada sin tildes) y devuelve (coincidencia, texto)."""
    m = patron.search(normalizar(texto))
    if not m:
        return None, texto
    return m, re.sub(r'\s{2,}', ' ', texto[:m.start()] + ' ' + texto[m.end():]).strip()


def _limpiar_titulo(texto):
    """'para la reunión con Juan' -> 'reunión con Juan' (sin conectores al principio ni al final)."""
    titulo = re.sub(r'\s{2,}', ' ', texto).strip(' ,.;:-')
    titulo = re.sub(r'(?i)^(?:para|por)\s+', '', titulo)
    titulo = re.sub(r'(?i)^(?:un|una|el|la|los|las|que)\s+', '', titulo)
    return re.sub(r'(?i)\s+(?:es|son|sera|será|para|el|de|y|a)$', '', titulo).strip(' ,.;:-')


def _sumar_minutos(hora, minutos):
    total = min(int(hora[:2]) * 60 + int(hora[3:]) + minutos, 23 * 60 + 59)
    return f'{total // 60:02d}:{total % 60:02d}'


def _interpretar_evento(original, hoy, explicito=True):
    """'clase de Cálculo los lunes y miércoles de 9 a 11' -> intención crear_evento, o None si no hay fecha."""
    normal = normalizar(original)
    categoria = next((c for patron, c in CATEGORIA_EVENTO if patron.search(normal)), 'Otro')

    _, texto = _quitar_patron(original, _RELLENO_RESERVA)
    dias, repeticion, hasta, texto, dia_mes = extraer_repeticion(texto, hoy)
    duracion, texto = _quitar_patron(texto, _DURACION)
    inicio, fin, texto = extraer_horario(texto)
    if not inicio:
        franja, texto = _quitar_patron(texto, _FRANJA_EVENTO)
        if franja:
            inicio, fin = TRAMO_FRANJA[franja.group('franja')]
    if inicio and not fin and duracion:
        if duracion.group('media'):
            minutos = 30
        elif duracion.group('horaymedia'):
            minutos = 90
        else:
            n = 1 if duracion.group('n') in ('una', 'un') else int(duracion.group('n'))
            minutos = n * (60 if duracion.group('unidad').startswith('hora') else 1)
            if duracion.group('ymedia'):
                minutos += 30
        fin = _sumar_minutos(inicio, minutos)
    fecha, texto = extraer_fecha(texto, hoy)
    if fecha is None and dia_mes:
        fecha = proximo_dia_del_mes(hoy, dia_mes)
    elif fecha is None and repeticion == 'diaria':
        fecha = hoy  # "el gimnasio todos los días a las 7": desde hoy
    if fecha is None and not dias:
        if explicito or categoria != 'Otro':
            return {'intencion': 'evento_sin_fecha', 'titulo': _limpiar_titulo(texto)}
        return None

    if categoria == 'Cumpleaños' and not repeticion:
        repeticion = 'anual'
    if dias:
        fechas = [proximo_dia(fecha or hoy, d) for d in dias]
    else:
        fechas = [fecha]

    titulo = _limpiar_titulo(texto)
    if not titulo:
        return None

    return {
        'intencion': 'crear_evento',
        'eventos': [{
            'titulo': titulo[0].upper() + titulo[1:],
            'categoria': categoria,
            'fecha': f.isoformat(),
            'hora_inicio': inicio,
            'hora_fin': fin,
            'repeticion': repeticion,
            'hasta': hasta.isoformat() if hasta and repeticion in ('diaria', 'semanal', 'mensual') else '',
        } for f in fechas],
    }


def _interpretar_recordatorio(resto, ahora):
    """'mañana a las 10 que tengo reunión' -> (momento, 'Tengo reunión'), o None si no hay hora."""
    normal = normalizar(resto)

    # Forma "<cuándo> que <mensaje>": la hora se busca solo antes del "que",
    # así "a las 11" en "que tengo una reunión a las 11" se queda en el mensaje
    m = _SEPARADOR.search(normal)
    if m and m.start() > 0:
        momento, sobrante = extraer_momento(resto[:m.start()], ahora)
        if momento and not sobrante.strip(' ,.'):
            return momento, resto[m.end():].strip(' ,.:;-')

    # Forma libre: "llamar a Juan en 20 minutos", "que saque la ropa a las 6"
    momento, sobrante = extraer_momento(resto, ahora)
    if momento is None:
        return None
    mensaje = re.sub(r'^(?:de\s+que|que|de)\s+', '', sobrante.strip(' ,.:;-'), flags=re.IGNORECASE)
    return momento, mensaje


def interpretar(texto, hoy=None, ahora=None):
    original = texto.strip().lstrip('¿¡ ')
    normal = normalizar(original)
    if ahora is None:
        ahora = datetime.combine(hoy, datetime.now().time()) if hoy else datetime.now()
    hoy = hoy or ahora.date()

    if SALUDO.match(normal):
        return {'intencion': 'saludo'}
    if GRACIAS.match(normal):
        return {'intencion': 'gracias'}
    if AFIRMACION.match(normal):
        return {'intencion': 'afirmacion'}
    if AYUDA.match(normal):
        return {'intencion': 'ayuda'}

    m = SELECCION.match(normal)
    if m:
        num = m.group('num')
        return {'intencion': 'seleccion', 'numero': ORDINALES.get(num) or int(num)}
    if TODOS.match(normal):
        return {'intencion': 'seleccion_todos'}
    if NEGACION.match(normal):
        return {'intencion': 'negacion'}

    if LISTAR_RECORDATORIOS.match(normal):
        return {'intencion': 'listar_recordatorios'}

    m = CANCELAR_RECORDATORIO.match(normal)
    if m:
        return {'intencion': 'cancelar_recordatorio', 'objeto': _recortar(original, *m.span('objeto'))}

    m = RECORDATORIO.match(normal)
    if m:
        resultado = _interpretar_recordatorio(original[m.start('resto'):], ahora)
        if resultado:
            momento, mensaje = resultado
            if not mensaje:
                return None
            return {'intencion': 'recordatorio', 'cuando': momento.strftime('%Y-%m-%d %H:%M'),
                    'texto': mensaje[0].upper() + mensaje[1:]}

        # Sin hora: con día, se avisa ese día a las 9:00; sin día, el bot pregunta cuándo
        fecha, mensaje = extraer_fecha(original[m.start('resto'):], hoy)
        mensaje = re.sub(r'(?i)^(?:de\s+que|que|de|para)\s+', '', mensaje.strip(' ,.:;-'))
        if not mensaje:
            return None
        mensaje = mensaje[0].upper() + mensaje[1:]
        if fecha and fecha > hoy:
            return {'intencion': 'recordatorio', 'cuando': f'{fecha.isoformat()} 09:00', 'texto': mensaje,
                    'hora_por_defecto': True}
        return {'intencion': 'recordatorio_sin_hora', 'texto': mensaje, 'fecha': fecha.isoformat() if fecha else ''}

    m = LISTAR_EVENTOS.match(normal)
    if m:
        return {'intencion': 'listar_eventos', 'periodo': m.group('periodo') or '',
                'categoria': CATEGORIA_POR_PALABRA.get(m.group('tipo'))}

    filtro_tareas = _interpretar_filtro_tareas(original, normal)
    if filtro_tareas:
        return filtro_tareas

    # "qué tengo esta semana" -> agenda completa (eventos, tareas y recordatorios);
    # "tareas de esta semana" -> solo tareas
    solo_tareas = bool(re.search(r'\btareas\b', normal))
    for patron in LISTAR:
        m = patron.match(normal)
        if m:
            grupos = m.groupdict()
            return {'intencion': 'listar', 'periodo': grupos.get('periodo') or '',
                    'filtro': grupos.get('filtro') or '', 'persona': '', 'solo_tareas': solo_tareas}

    m = LISTAR_FECHA.match(normal)
    if m and _es_solo_fecha(original[m.start('cuando'):m.end('cuando')], hoy):
        return {'intencion': 'listar', 'periodo': normal[m.start('cuando'):m.end('cuando')], 'filtro': '',
                'persona': '', 'solo_tareas': solo_tareas}

    m = LISTAR_ALGO.match(normal)
    if m:
        periodo = normal[m.start('cuando'):m.end('cuando')]
        if _es_solo_fecha(original[m.start('cuando'):m.end('cuando')], hoy) or rango_periodo(periodo, hoy)[0]:
            return {'intencion': 'listar', 'periodo': periodo, 'filtro': '', 'persona': '', 'solo_tareas': False}

    for patron in LISTAR_PERSONA:
        m = patron.match(normal)
        if m:
            return {'intencion': 'listar', 'periodo': '', 'filtro': '', 'persona': _palabra(original, m, 'persona')}

    for patron in BORRAR_EVENTO:
        m = patron.match(normal)
        if m:
            return {'intencion': 'borrar_evento', 'objeto': _recortar(original, *m.span('objeto'))}

    for patron in (EVENTO_EXPLICITO, EVENTO_CUMPLE):
        m = patron.match(normal)
        if m:
            return _interpretar_evento(original[m.start('resto'):], hoy)

    m = CREAR.match(normal)
    if m:
        resto = original[m.start('resto'):]
        # "apunta el cumple de Marta el 23/10" es un evento, no una tarea
        if EVENTO_CUMPLE.match(normalizar(resto)):
            evento = _interpretar_evento(re.sub(r'(?i)^(?:el|mi)\s+', '', resto), hoy)
            if evento:
                return evento
        datos = _interpretar_creacion(resto, hoy, ahora)
        return dict(datos, intencion='crear') if datos else None

    # "tengo clase de Cálculo los lunes de 9 a 11", "tengo examen el jueves a las 16"
    m = EVENTO_TENGO.match(normal)
    if m:
        evento = _interpretar_evento(original[m.start('resto'):], hoy, explicito=False)
        if evento:
            return evento

    # El orden importa: "cambia la importancia de X a alta" o "quita la fecha de X"
    # no deben confundirse con mover ni borrar
    for patron in CAMBIAR_IMPORTANCIA:
        m = patron.match(normal)
        if m:
            nivel = {'alta': 'Alta', 'media': 'Media', 'baja': 'Baja'}.get(m.group('imp'), 'Alta')
            return {'intencion': 'importancia', 'objeto': _recortar(original, *m.span('objeto')), 'importancia': nivel}

    for patron in RENOMBRAR:
        m = patron.match(normal)
        if m:
            nuevo = _recortar(original, *m.span('nuevo')).strip('«»"\'')
            return {'intencion': 'renombrar', 'objeto': _recortar(original, *m.span('objeto')),
                    'nombre': nuevo[:1].upper() + nuevo[1:]}

    accion = _interpretar_edicion(original, normal, hoy, ahora)
    if accion:
        return accion

    m = QUITAR_FECHA.match(normal)
    if m:
        return {'intencion': 'mover', 'objeto': _recortar(original, *m.span('objeto')), 'fecha_limite': '',
                'hora_limite': ''}

    for patron in ASIGNAR:
        m = patron.match(normal)
        if m:
            return {'intencion': 'asignar', 'objeto': _recortar(original, *m.span('objeto')),
                    'persona': _palabra(original, m, 'persona')}

    for intencion, patrones in (('completar', COMPLETAR), ('empezar', EMPEZAR), ('borrar', [BORRAR])):
        for patron in patrones:
            m = patron.match(normal)
            if m:
                objeto = _recortar(original, *m.span('objeto'))
                return {'intencion': intencion, 'objeto': objeto} if objeto else None


    return None


# --- Varias peticiones en un mismo mensaje (sobre todo en audios) ------------------------

# Palabras con las que empieza una petición nueva
_INICIO_PETICION = (r'(?:apunta(?:me)?|anade(?:me)?|agrega(?:me)?|crea(?:me)?|pon(?:me)?|mete|recuerda(?:me)?|'
                    r'avisa(?:me)?|tengo|tenemos|hay\s+que|(?:el|mi)\s+cumple|nueva\s+tarea|nuevo\s+evento|'
                    r'borra|elimina|cancela|mueve|marca|he\s+terminado|ya\s+he\s+terminado|reserva(?:r|me|nos)?)\b')
# Solo se corta si la petición nueva va detrás de un conector: así "recuérdame que tengo que llamar" no se parte
_CORTE = re.compile(
    r'(?:\s*[,.;]\s*|\s+)(?:y\s+(?:luego|despues|tambien|ademas)|y|tambien|ademas|luego|despues|otra\s+cosa|'
    r'por\s+otro\s+lado)?\s*(?:,\s*)?(?=' + _INICIO_PETICION + ')'
)
_CONECTOR_FINAL = re.compile(r'(?:\s*[,.;]|\s+(?:y|tambien|ademas|luego|despues|vale|eh|pues))+\s*$')


def dividir_peticiones(texto):
    """'apunta X y recuérdame Y y tengo Z' -> ['apunta X', 'recuérdame Y', 'tengo Z'].

    Un mensaje con una sola petición se devuelve tal cual (en una lista de un elemento).
    """
    normal = normalizar(texto)
    cortes = []
    for m in _CORTE.finditer(normal):
        antes = normal[:m.start()]
        # Hace falta un conector explícito (o puntuación), salvo al principio del mensaje
        conector = normal[m.start():m.end()].strip(' ')
        if m.start() == 0 or not conector:
            continue
        cortes.append((m.start(), m.end()))
    if not cortes:
        return [texto]

    partes, inicio = [], 0
    for corte_inicio, corte_fin in cortes:
        partes.append(texto[inicio:corte_inicio])
        inicio = corte_fin
    partes.append(texto[inicio:])

    limpias = []
    for parte in partes:
        parte = _CONECTOR_FINAL.sub('', parte.strip()).strip(' ,.;')
        if parte:
            limpias.append(parte)
    return limpias or [texto]


# --- Filtro de tareas: "tareas importantes sin fecha", "tareas en curso de Marta"... ----------

_INICIO_TAREAS = re.compile(r'^(?:y\s+)?(?:(?:que|cuales|dime|ensename|muestrame|ver|lista\s+de|mis|las|todas\s+las)\s+)*tareas\b')
_FILTROS_TAREA = [
    ('ignorar', re.compile(r'(?:pendientes|que\s+tengo|que\s+hay|tengo|hay|que\s+son|que\s+esten|y|con\s+fecha\s+o\s+sin\s+ella)\b')),
    ('sin_fecha', re.compile(r'sin\s+(?:fecha(?:\s+limite)?|plazo|dia)\b')),
    ('con_fecha', re.compile(r'con\s+(?:fecha(?:\s+limite)?|plazo)\b')),
    ('importancia', re.compile(r'(?:de\s+|con\s+)?(?:importancia|prioridad)\s+(?P<valor>alta|media|baja)\b')),
    ('importancia', re.compile(r'(?:de\s+|con\s+)?(?P<valor>alta|media|baja)\s+(?:importancia|prioridad)\b')),
    ('importancia', re.compile(r'(?P<valor>importantes|urgentes|poco\s+importantes)\b')),
    ('status', re.compile(r'(?P<valor>en\s+curso|empezadas|sin\s+empezar|terminadas|hechas|completadas|acabadas)\b')),
    ('atrasadas', re.compile(r'(?:atrasadas|vencidas|retrasadas)\b')),
    ('periodo', re.compile(r'(?:(?:de|para|del|que\s+vencen)\s+)?' + _PERIODO + r'\b')),
    ('persona', re.compile(r'(?:de|asignadas\s+a|para)\s+(?P<valor>[a-z]+)\b')),
]
_VALOR_FILTRO = {'alta': 'Alta', 'importantes': 'Alta', 'urgentes': 'Alta', 'media': 'Media', 'baja': 'Baja',
                 'poco importantes': 'Baja', 'en curso': 'En Curso', 'empezadas': 'En Curso',
                 'sin empezar': 'Sin Empezar', 'terminadas': 'Terminado', 'hechas': 'Terminado',
                 'completadas': 'Terminado', 'acabadas': 'Terminado'}


def _interpretar_filtro_tareas(original, normal):
    """'tareas importantes sin fecha' -> intención listar_tareas con sus filtros; None si sobra algo."""
    m = _INICIO_TAREAS.match(normal)
    if not m:
        return None
    filtros = {}
    posicion = m.end()
    while True:
        resto = normal[posicion:]
        espacios = len(resto) - len(resto.lstrip(' ,'))
        posicion += espacios
        if not normal[posicion:].strip(' ?!.¿¡'):
            break
        for nombre, patron in _FILTROS_TAREA:
            f = patron.match(normal, posicion)
            if f:
                if nombre == 'persona':
                    filtros['persona'] = original[f.start('valor'):f.end('valor')].capitalize()
                elif nombre == 'periodo':
                    filtros['periodo'] = f.group('periodo')
                elif nombre in ('importancia', 'status'):
                    filtros[nombre] = _VALOR_FILTRO[re.sub(r'\s+', ' ', f.group('valor'))]
                elif nombre != 'ignorar':
                    filtros[nombre] = True
                posicion = f.end()
                break
        else:
            return None  # hay algo que no es un filtro: que lo intenten las demás reglas
    return {'intencion': 'listar_tareas', 'filtros': filtros}


# --- Llamar al bot por su nombre: "Jarvis, dime qué tengo hoy" ------------------------------

def _nombres_bot():
    """'Jarvis' y cómo lo suele escribir el reconocedor de voz; NOMBRE_BOT en el .env añade otro."""
    import os
    nombres = ['jarvis', 'yarvis', 'llarvis', 'jarbis', 'yarbis', 'harvis', 'jarvi', 'yarvi']
    extra = normalizar(os.getenv('NOMBRE_BOT', '')).strip()
    return nombres + ([extra] if extra else [])


_MULETILLAS = r'oye|hey|ey|ok|okay|dime|porfa|por\s+favor|a\s+ver|eh|bueno|venga|hola|buenas|que\s+tal|como\s+estas|bot'
_SIGNOS = r'[\s,.;:!¡]*'


def quitar_llamada(texto):
    """Quita el nombre del bot y las muletillas del principio y del final.

    'Jarvis, dime qué tengo hoy' -> 'qué tengo hoy'; 'Oye Jarvis' -> 'hola' (un saludo);
    'ok' o 'vale' se dejan tal cual (son respuestas a una pregunta del bot).
    """
    nombres = '|'.join(_nombres_bot())
    inicio = re.compile(rf'{_SIGNOS}(?:{nombres}|{_MULETILLAS})\b{_SIGNOS}')
    final = re.compile(rf'{_SIGNOS}(?:{nombres}|por\s+favor|porfa|gracias)\b[\s.!?]*$')

    resto = texto.strip()
    llamado = False
    while True:
        m = inicio.match(normalizar(resto))
        if not m or m.end() == 0:
            break
        llamado = llamado or bool(re.search(rf'\b(?:{nombres}|hola|buenas|hey|oye|dime)\b', normalizar(resto[:m.end()])))
        resto = resto[m.end():]
    while True:
        m = final.search(normalizar(resto))
        if not m or m.start() == 0:
            break
        resto = resto[:m.start()]
    resto = resto.strip()

    if not resto:
        # Solo "Jarvis", "hola Jarvis"... es un saludo; "ok", "vale"... se respeta tal cual
        return 'hola' if llamado else texto.strip()
    return resto


def es_deshacer(texto):
    return bool(DESHACER.match(normalizar(texto.strip().lstrip('¿¡ '))))
