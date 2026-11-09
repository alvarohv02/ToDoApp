"""Normalización de texto e interpretación de fechas en español, sin dependencias externas."""
import calendar
from datetime import date, datetime, time, timedelta
import re
import unicodedata

DIAS_SEMANA = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']
DIAS_SEMANA_BONITOS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
         'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
NUMEROS = {'un': 1, 'una': 1, 'uno': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5,
           'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10, 'quince': 15}


def normalizar(texto):
    """Minúsculas y sin tildes, conservando la longitud (cada carácter se mapea a uno)."""
    return ''.join(unicodedata.normalize('NFD', c)[0].lower() if c.strip() else ' ' for c in texto)


def _numero(valor):
    return int(valor) if valor.isdigit() else NUMEROS[valor]


def _proximo_dia_semana(hoy, indice, saltar_semana=False):
    dias = (indice - hoy.weekday()) % 7 or 7
    return hoy + timedelta(days=dias + (7 if saltar_semana else 0))


def _fecha_segura(anio, mes, dia):
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def _sumar_meses(fecha, meses):
    mes = fecha.month - 1 + meses
    anio, mes = fecha.year + mes // 12, mes % 12 + 1
    for dia in (fecha.day, 30, 29, 28):
        resultado = _fecha_segura(anio, mes, dia)
        if resultado:
            return resultado


def _fecha_sin_anio(hoy, mes, dia):
    """Una fecha sin año se entiende en el futuro: si ya ha pasado este año, es la del siguiente."""
    fecha = _fecha_segura(hoy.year, mes, dia)
    if fecha and fecha < hoy:
        fecha = _fecha_segura(hoy.year + 1, mes, dia)
    return fecha


_DIAS_RE = '|'.join(DIAS_SEMANA)
_MESES_RE = '|'.join(MESES)
_CANTIDAD_RE = r'\d+|' + '|'.join(NUMEROS)

# Conectores que suelen ir delante de una fecha y que hay que quitar del nombre de la tarea
_PREFIJO = r'(?:(?:para|antes del?|hasta el|el|este|esta|la|de)\s+)*'

PATRONES = [
    (rf'pasado\s+manana', lambda m, h: h + timedelta(days=2)),
    (rf'manana', lambda m, h: h + timedelta(days=1)),
    (rf'hoy|esta\s+tarde|esta\s+noche', lambda m, h: h),
    (rf'dentro\s+de\s+({_CANTIDAD_RE})\s+(dias?|semanas?|mes(?:es)?)|en\s+({_CANTIDAD_RE})\s+(dias?|semanas?)',
     lambda m, h: _desplazamiento(m, h)),
    # "el lunes 9", "el sábado 14 de noviembre": manda el número de día (y el mes si se dice)
    (rf'(?:{_DIAS_RE})\s+(?:dia\s+)?(\d{{1,2}})(?:\s+de\s+({_MESES_RE})(?:\s+(?:de|del)\s+(\d{{4}}))?)?(?!\s*[:./h\d])',
     lambda m, h: _fecha_dia_semana(m, h)),
    (rf'(?:proximo\s+)?({_DIAS_RE})(\s+que\s+viene|\s+proximo|\s+de\s+la\s+semana\s+que\s+viene)?',
     lambda m, h: _proximo_dia_semana(h, DIAS_SEMANA.index(m.group(1)),
                                      saltar_semana='semana que viene' in (m.group(2) or ''))),
    (r'fin\s+de\s+semana|finde', lambda m, h: _proximo_dia_semana(h, 5) if h.weekday() != 5 else h),
    (r'(?:semana\s+que\s+viene|proxima\s+semana)', lambda m, h: _proximo_dia_semana(h, 0)),
    (r'(?:mes\s+que\s+viene|proximo\s+mes)', lambda m, h: _sumar_meses(h, 1)),
    (rf'(\d{{1,2}})\s+de\s+({_MESES_RE})(?:\s+(?:de|del)\s+(\d{{4}}))?',
     lambda m, h: _fecha_segura(int(m.group(3)), MESES.index(m.group(2)) + 1, int(m.group(1)))
     if m.group(3) else _fecha_sin_anio(h, MESES.index(m.group(2)) + 1, int(m.group(1)))),
    (r'(\d{4})-(\d{1,2})-(\d{1,2})', lambda m, h: _fecha_segura(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    (r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?', lambda m, h: _fecha_dd_mm(m, h)),
    (r'(?:dia\s+)(\d{1,2})', lambda m, h: _dia_del_mes(h, int(m.group(1)))),
]


def _desplazamiento(m, hoy):
    cantidad = _numero(m.group(1) or m.group(3))
    unidad = m.group(2) or m.group(4)
    if unidad.startswith('dia'):
        return hoy + timedelta(days=cantidad)
    if unidad.startswith('semana'):
        return hoy + timedelta(weeks=cantidad)
    return _sumar_meses(hoy, cantidad)


def _fecha_dia_semana(m, hoy):
    dia = int(m.group(1))
    if not m.group(2):
        return _dia_del_mes(hoy, dia)
    mes = MESES.index(m.group(2)) + 1
    return _fecha_segura(int(m.group(3)), mes, dia) if m.group(3) else _fecha_sin_anio(hoy, mes, dia)


def _fecha_dd_mm(m, hoy):
    dia, mes = int(m.group(1)), int(m.group(2))
    if m.group(3):
        anio = int(m.group(3))
        return _fecha_segura(anio + 2000 if anio < 100 else anio, mes, dia)
    return _fecha_sin_anio(hoy, mes, dia)


def _dia_del_mes(hoy, dia):
    fecha = _fecha_segura(hoy.year, hoy.month, dia)
    if fecha is None or fecha < hoy:
        siguiente = _sumar_meses(hoy.replace(day=1), 1)
        fecha = _fecha_segura(siguiente.year, siguiente.month, dia)
    return fecha


def extraer_fecha(texto, hoy=None):
    """Busca una fecha en el texto.

    Devuelve (fecha, texto_sin_la_fecha). Si no hay fecha, (None, texto).
    El texto devuelto conserva mayúsculas y tildes del original.
    """
    hoy = hoy or date.today()
    normal = normalizar(texto)

    for patron, construir in PATRONES:
        m = re.search(rf'(?<!\w){_PREFIJO}(?:{patron})(?!\w)', normal)
        if not m:
            continue
        # Volvemos a casar sin el prefijo para que los grupos del patrón queden en su sitio
        nucleo = re.match(_PREFIJO + rf'({patron})', normal[m.start():m.end()])
        interno = re.fullmatch(patron, nucleo.group(1))
        fecha = construir(interno, hoy)
        if fecha is None:
            continue
        resto = (texto[:m.start()] + ' ' + texto[m.end():]).strip()
        return fecha, re.sub(r'\s{2,}', ' ', resto)

    return None, texto


def rango_periodo(periodo, hoy=None):
    """Rango de fechas (desde, hasta) para expresiones de consulta como 'esta semana'."""
    hoy = hoy or date.today()
    periodo = normalizar(periodo or '').strip()

    if periodo in ('', 'todo', 'todas'):
        return None, None
    if periodo == 'hoy':
        return hoy, hoy
    if periodo == 'manana':
        return hoy + timedelta(days=1), hoy + timedelta(days=1)
    if periodo == 'pasado manana':
        return hoy + timedelta(days=2), hoy + timedelta(days=2)
    if periodo == 'esta semana':
        return hoy, hoy + timedelta(days=6 - hoy.weekday())
    if periodo in ('la semana que viene', 'semana que viene', 'la proxima semana', 'proxima semana'):
        lunes = _proximo_dia_semana(hoy, 0)
        return lunes, lunes + timedelta(days=6)
    if periodo in ('este fin de semana', 'el fin de semana', 'el finde', 'este finde'):
        sabado = hoy if hoy.weekday() == 5 else _proximo_dia_semana(hoy, 5)
        return sabado, sabado + timedelta(days=1)
    if periodo == 'este mes':
        return hoy, _sumar_meses(hoy.replace(day=1), 1) - timedelta(days=1)

    fecha, _ = extraer_fecha(periodo, hoy)
    return (fecha, fecha) if fecha else (None, None)


def formatear(fecha_iso, hoy=None):
    """'2026-10-23' -> 'vie 23/10' (con año solo si no es el actual)."""
    if not fecha_iso:
        return ''
    hoy = hoy or date.today()
    fecha = date.fromisoformat(fecha_iso)
    if fecha == hoy:
        return 'hoy'
    if fecha == hoy + timedelta(days=1):
        return 'mañana'
    texto = f'{DIAS_SEMANA_BONITOS[fecha.weekday()][:3]} {fecha.day:02d}/{fecha.month:02d}'
    return texto if fecha.year == hoy.year else f'{texto}/{fecha.year}'


# --- Horas (para recordatorios) ----------------------------------------------------

_HORA = re.compile(
    r'(?:\b(?:a|sobre|hacia|para|antes\s+de|hasta)\s+)?\blas?\s+(?P<h>\d{1,2})'
    r'(?:\s*[:.h]\s*(?P<m>\d{2})|\s+y\s+(?P<fr>media|cuarto)|\s+menos\s+(?P<menos>cuarto))?'
    r'(?:\s*(?:h|horas)\b)?'
    r'(?:\s+(?:de\s+la\s+|del\s+|por\s+la\s+)(?P<franja>manana|tarde|noche|madrugada|mediodia)'
    r'|\s+(?P<franja2>tarde|noche|madrugada)\b|\s*(?P<ampm>am|pm)\b)?'
)
_DESPLAZAMIENTO = re.compile(
    r'(?:en|dentro\s+de)\s+(?:(?P<n>\d+|' + '|'.join(NUMEROS) + r'|media)\s+)?'
    r'(?P<unidad>minutos?|mins?|horas?)(?P<ymedia>\s+y\s+media)?'
)
_FRANJA = re.compile(r'\b(?:por\s+la|esta|a)\s+(?P<franja>manana|tarde|noche|mediodia)\b')
# Horas sin "las": "11:00", "9.30", "11h", "11:00h", "11am", "a 11:00"
_HORA_SUELTA = re.compile(
    r'(?:\b(?:a|sobre|hacia|para|antes\s+de|hasta)\s+)?(?<![\d/:.,])\b(?P<h>\d{1,2})'
    r'(?:\s*[:.]\s*(?P<m>\d{2})(?!\d)(?:\s*h\b)?|\s*(?P<ampm>am|pm)\b|\s*h\b)'
    r'(?:\s+(?:de\s+la\s+|del\s+|por\s+la\s+)(?P<franja>manana|tarde|noche|madrugada|mediodia)'
    r'|\s+(?P<franja2>tarde|noche|madrugada)\b)?'
)
_PREFIJO_HORA = re.compile(r'\b(?:a|sobre|hacia|para|antes\s+de|hasta)\s')


class _Hora:
    """Resultado común de _HORA y _HORA_SUELTA (las dos tienen grupos distintos)."""

    def __init__(self, m):
        self._m = m

    def group(self, nombre):
        grupos = self._m.groupdict()
        if nombre == 'franja':  # "de la tarde" o "tarde" a secas; "mañana" a secas es el día siguiente
            return grupos.get('franja') or grupos.get('franja2')
        return grupos.get(nombre)

    def start(self):
        return self._m.start()

    def end(self):
        return self._m.end()


def buscar_hora(normal):
    """La hora más probable del texto normalizado, o None.

    Si hay varias ("la reunión de las 12 a las 11:30"), gana la que lleva "a/sobre/para..." delante.
    """
    candidatas = [m for m in _HORA.finditer(normal) if int(m.group('h')) <= 24]
    for m in _HORA_SUELTA.finditer(normal):
        if int(m.group('h')) <= 24 and int(m.group('m') or 0) <= 59 and \
                not any(m.start() < c.end() and c.start() < m.end() for c in candidatas):
            candidatas.append(m)
    if not candidatas:
        return None
    candidatas.sort(key=lambda m: (not _PREFIJO_HORA.match(normal, m.start()), m.start()))
    return _Hora(candidatas[0])
HORA_FRANJA = {'manana': (9, 0), 'mediodia': (13, 0), 'tarde': (17, 0), 'noche': (21, 0)}


def _limpiar(texto, inicio, fin):
    return re.sub(r'\s{2,}', ' ', (texto[:inicio] + ' ' + texto[fin:])).strip(' ,.')


def extraer_momento(texto, ahora):
    """Busca una fecha y hora ('mañana a las 10', 'en 20 minutos', 'el viernes por la tarde').

    Devuelve (datetime, texto_restante) o (None, texto) si no hay hora.
    Solo se usa la primera hora que aparece; una fecha sin hora no cuenta.
    """
    normal = normalizar(texto)

    m = _DESPLAZAMIENTO.search(normal)
    if m and (m.group('n') or m.group('unidad').startswith('hora')):
        n = m.group('n') or 'una'
        cantidad = 0.5 if n == 'media' else _numero(n)
        if m.group('ymedia'):
            cantidad += 0.5
        minutos = cantidad * (60 if m.group('unidad').startswith('hora') else 1)
        momento = (ahora + timedelta(minutes=minutos)).replace(second=0, microsecond=0)
        return momento, _limpiar(texto, m.start(), m.end())

    m = buscar_hora(normal)
    if m:
        h, minuto = int(m.group('h')), int(m.group('m') or 0)
        franja, ampm = m.group('franja'), m.group('ampm')
        if m.group('fr'):
            minuto = 30 if m.group('fr') == 'media' else 15
        if m.group('menos'):
            h, minuto = h - 1, 45
        explicita = bool(franja or ampm)
        if h < 12 and (franja in ('tarde', 'noche') or ampm == 'pm'):
            h += 12
        if h == 12 and (franja in ('noche', 'madrugada') or ampm == 'am'):
            h = 0
        if h == 24:
            h = 0
        if minuto > 59 or h > 23:
            return None, texto
        resto = _limpiar(texto, m.start(), m.end())
    else:
        m = _FRANJA.search(normal)
        if not m:
            return None, texto
        h, minuto = HORA_FRANJA[m.group('franja')]
        explicita = True
        resto = _limpiar(texto, m.start(), m.end())

    fecha, resto = extraer_fecha(resto, ahora.date())
    momento = datetime.combine(fecha or ahora.date(), time(h, minuto))

    if not explicita and h < 12:
        # "a las 5" sin más: de 1 a 7 casi siempre es por la tarde; y si ya ha pasado hoy, la de la tarde
        if 1 <= h <= 7 or (fecha is None and momento <= ahora and momento + timedelta(hours=12) > ahora):
            momento += timedelta(hours=12)
    if fecha is None and momento <= ahora:
        momento += timedelta(days=1)

    return momento, resto


# --- Horas y repeticiones (para eventos del calendario) --------------------------------

_HM = r'(\d{1,2})(?:\s*[:.h]\s*(\d{2}))?'
_RANGO_HORAS = re.compile(
    r'(?:de|desde)\s+(?:las?\s+)?' + _HM + r'(?:\s*(?:h|horas)\b)?\s+(?:a|hasta)\s+(?:las?\s+)?' + _HM + r'(?:\s*(?:h|horas)\b)?'
    r'(?:\s+(?:de\s+la\s+|del\s+|por\s+la\s+)(?P<franja>manana|tarde|noche|mediodia)|\s+(?P<franja2>tarde|noche)\b)?'
)
_DIAS_REPETIDOS = re.compile(
    r'(?:todos\s+los|cada|los)\s+(?P<dias>(?:' + _DIAS_RE + r')(?:\s*(?:,|y)\s*(?:los\s+)?(?:' + _DIAS_RE + r'))*)'
)
_REPETICION = re.compile(r'(?P<diaria>todos\s+los\s+dias|cada\s+dia|a\s+diario|diariamente)|'
                         r'(?P<semanal>cada\s+semana|todas\s+las\s+semanas|semanalmente)|'
                         r'(?P<mensual>cada\s+mes|todos\s+los\s+meses|mensualmente)|'
                         r'(?P<anual>cada\s+ano|todos\s+los\s+anos|anualmente)')
# "el día 5 de cada mes", "el 5 de cada mes", "los días 5 (de cada mes)"
_DIA_DEL_MES = re.compile(r'(?:el\s+)?(?:dia\s+)?(?P<n>\d{1,2})\s+de\s+cada\s+mes|'
                          r'(?:todos\s+)?los\s+dias\s+(?P<n2>\d{1,2})(?:\s+de\s+cada\s+mes)?\b')
_HASTA = re.compile(r'hasta\s+(?:el\s+)?(?!las?\s)')


def _ajustar_hora(h, minuto, franja):
    """Hora de 24 h a partir de '9', '5 de la tarde'... Sin franja, de 1 a 7 se entiende por la tarde."""
    if franja in ('tarde', 'noche') and h < 12:
        h += 12
    elif franja is None and 1 <= h <= 7:
        h += 12
    if h > 23 or minuto > 59:
        return None
    return f'{h:02d}:{minuto:02d}'


def extraer_horario(texto):
    """'de 9 a 11' -> ('09:00', '11:00', resto); 'a las 16:30' -> ('16:30', '', resto); sin hora -> ('', '', texto)."""
    normal = normalizar(texto)

    m = _RANGO_HORAS.search(normal)
    if m:
        franja = m.group('franja') or m.group('franja2')
        inicio = _ajustar_hora(int(m.group(1)), int(m.group(2) or 0), franja)
        fin = _ajustar_hora(int(m.group(3)), int(m.group(4) or 0), franja)
        # "de 11 a 1" -> la 1 es por la tarde; "de 9 a 2" igual
        if inicio and fin and fin <= inicio and int(m.group(3)) < 12 and franja is None:
            fin = f'{int(fin[:2]) + 12:02d}{fin[2:]}' if int(fin[:2]) + 12 <= 23 else fin
        if inicio and fin and fin > inicio:
            return inicio, fin, _limpiar(texto, m.start(), m.end())

    m = buscar_hora(normal)
    if m:
        h, minuto = int(m.group('h')), int(m.group('m') or 0)
        if m.group('fr'):
            minuto = 30 if m.group('fr') == 'media' else 15
        if m.group('menos'):
            h, minuto = h - 1, 45
        franja = m.group('franja') or {'pm': 'tarde', 'am': 'manana'}.get(m.group('ampm'))
        inicio = _ajustar_hora(h, minuto, franja)
        if inicio:
            return inicio, '', _limpiar(texto, m.start(), m.end())

    return '', '', texto


def extraer_repeticion(texto, hoy):
    """Devuelve (dias_semana, repeticion, hasta, resto, dia_del_mes).

    'los lunes y miércoles' -> ([0, 2], 'semanal', ...); 'cada año' -> ([], 'anual', ...);
    'todos los días' -> 'diaria'; 'el día 5 de cada mes' -> 'mensual' con dia_del_mes = 5;
    'hasta el 18 de diciembre' -> hasta = date(…, 12, 18).
    """
    dias, repeticion, hasta, dia_mes = [], '', None, None

    m = _HASTA.search(normalizar(texto))
    if m:
        # La fecha más larga que se entienda entera tras "hasta": "15/06", "18 de diciembre"...
        palabras = list(re.finditer(r'\S+', texto[m.end():]))
        for n in range(min(len(palabras), 6), 0, -1):
            fin = m.end() + palabras[n - 1].end()
            fecha, sobrante = extraer_fecha(texto[m.end():fin].rstrip(',.'), hoy)
            if fecha and not sobrante.strip(' ,.'):
                hasta = fecha
                texto = _limpiar(texto, m.start(), fin)
                break

    m = _DIA_DEL_MES.search(normalizar(texto))
    if m and 1 <= int(m.group('n') or m.group('n2')) <= 31:
        dia_mes, repeticion = int(m.group('n') or m.group('n2')), 'mensual'
        texto = _limpiar(texto, m.start(), m.end())

    m = _DIAS_REPETIDOS.search(normalizar(texto))
    if m:
        dias = sorted({DIAS_SEMANA.index(d) for d in re.findall(_DIAS_RE, m.group('dias'))})
        repeticion = 'semanal'
        texto = _limpiar(texto, m.start(), m.end())

    m = _REPETICION.search(normalizar(texto))
    if m:
        repeticion = next(r for r in ('diaria', 'semanal', 'mensual', 'anual') if m.group(r))
        texto = _limpiar(texto, m.start(), m.end())

    return dias, repeticion, hasta, texto, dia_mes


def proximo_dia_del_mes(hoy, dia):
    """Hoy o el siguiente día «dia» de un mes (el último del mes si ese mes es más corto)."""
    for meses in range(13):
        total = hoy.year * 12 + hoy.month - 1 + meses
        anio, mes = total // 12, total % 12 + 1
        fecha = date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1]))
        if fecha >= hoy:
            return fecha
    return hoy


def proximo_dia(hoy, indice):
    """Hoy si ya es ese día de la semana; si no, el siguiente."""
    return hoy + timedelta(days=(indice - hoy.weekday()) % 7)


# --- Números escritos con letras ("a las cinco", "el veintitrés") -------------------------

_UNIDADES = ['cero', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve', 'diez',
             'once', 'doce', 'trece', 'catorce', 'quince', 'dieciseis', 'diecisiete', 'dieciocho', 'diecinueve',
             'veinte', 'veintiuno', 'veintidos', 'veintitres', 'veinticuatro', 'veinticinco', 'veintiseis',
             'veintisiete', 'veintiocho', 'veintinueve']


def _palabras_numero():
    valores = {palabra: n for n, palabra in enumerate(_UNIDADES)}
    valores.update({'un': 1, 'una': 1, 'veintiun': 21, 'veintiuna': 21, 'primero': 1})
    for decena, nombre in ((30, 'treinta'), (40, 'cuarenta'), (50, 'cincuenta')):
        valores[nombre] = decena
        for unidad in range(1, 10):
            valores[f'{nombre} y {_UNIDADES[unidad]}'] = decena + unidad
    return valores


VALOR_PALABRA = _palabras_numero()
# Las más largas primero para que "treinta y cinco" gane a "treinta"
_NUM = '(?:' + '|'.join(sorted((re.escape(p).replace(r'\ ', r'\s+') for p in VALOR_PALABRA), key=len, reverse=True)) + ')'

_CONTEXTOS_NUMERO = [
    # Horas: "las cinco", "la una", "las once y diez", "las once treinta"
    re.compile(r'\blas?\s+(?P<a>' + _NUM + r')(?:\s+y\s+(?P<b>' + _NUM + r')|\s+(?P<c>' + _NUM + r'))?\b'),
    # Rangos: "de nueve a once"
    re.compile(r'\b(?:de|desde)\s+(?P<a>' + _NUM + r')\s+(?:a|hasta)\s+(?:las?\s+)?(?P<b2>' + _NUM + r')\b'),
    # Día del mes: "el veintitrés de octubre", "el día cinco", "el primero de noviembre"
    re.compile(r'\b(?P<a>' + _NUM + r')\s+(?=de\s+(?:' + '|'.join(MESES) + r')\b)'),
    re.compile(r'\bdia\s+(?P<a>' + _NUM + r')\b'),
    # Cantidades de tiempo: "en veinte minutos", "dentro de dos semanas"
    re.compile(r'\b(?:en|dentro\s+de)\s+(?P<a>' + _NUM + r')\s+(?=(?:minutos?|horas?|dias?|semanas?|mes(?:es)?)\b)'),
]


def numeros_a_digitos(texto):
    """Pasa a cifras los números escritos con letras cuando son horas, días o plazos.

    'a las once y media' -> 'a las 11 y media'; 'a las cinco y diez' -> 'a las 5:10';
    'el veintitrés de octubre' -> 'el 23 de octubre'. El resto ("una reunión") no se toca.
    """
    for patron in _CONTEXTOS_NUMERO:
        normal = normalizar(texto)
        cambios = []
        for m in patron.finditer(normal):
            for grupo in ('a', 'b2'):
                if m.groupdict().get(grupo):
                    valor = VALOR_PALABRA[re.sub(r'\s+', ' ', m.group(grupo))]
                    texto_grupo = str(valor)
                    minutos = m.groupdict().get('b') or m.groupdict().get('c')
                    if grupo == 'a' and minutos:
                        # "las once y diez" -> "11:10" (pero "y media"/"y cuarto" se quedan como están)
                        texto_grupo = f'{valor}:{VALOR_PALABRA[re.sub(r"\s+", " ", minutos)]:02d}'
                        fin = m.end('b') if m.group('b') else m.end('c')
                        cambios.append((m.start(grupo), fin, texto_grupo))
                    else:
                        cambios.append((m.start(grupo), m.end(grupo), texto_grupo))
        for inicio, fin, nuevo in sorted(cambios, reverse=True):
            texto = texto[:inicio] + nuevo + texto[fin:]
    return texto
