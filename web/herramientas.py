"""Operaciones sobre tareas que usan tanto el motor de reglas como el LLM local."""
from datetime import date, datetime
from difflib import SequenceMatcher
import re

import db
from fechas import normalizar

PALABRAS_VACIAS = {'la', 'el', 'los', 'las', 'de', 'del', 'a', 'al', 'en', 'un', 'una', 'y', 'que',
                   'lo', 'con', 'por', 'para', 'mi', 'tarea', 'evento', 'eso', 'esto', 'cosa'}


# --- Validación ------------------------------------------------------------------

def validar_fecha(valor):
    if valor:
        try:
            datetime.strptime(valor, '%Y-%m-%d')
        except ValueError as error:
            raise db.DatosNoValidos('Fecha no válida (usa AAAA-MM-DD)') from error


def validar_campos(datos):
    if 'importancia' in datos and datos['importancia'] not in db.IMPORTANCIAS:
        raise db.DatosNoValidos(f'Importancia no válida: {datos["importancia"]}. Usa una de {db.IMPORTANCIAS}')
    if 'status' in datos and datos['status'] not in db.ESTADOS:
        raise db.DatosNoValidos(f'Status no válido: {datos["status"]}. Usa uno de {db.ESTADOS}')
    if 'fecha_limite' in datos:
        validar_fecha(datos['fecha_limite'])


# --- Búsqueda --------------------------------------------------------------------

def listar_tareas(status=None, persona=None, texto=None, fecha_limite_desde=None,
                  fecha_limite_hasta=None, incluir_terminadas=False, importancia=None):
    tareas = db.fetch_all_tasks()
    validar_fecha(fecha_limite_desde)
    validar_fecha(fecha_limite_hasta)

    if status:
        tareas = [t for t in tareas if t['status'] == status]
    elif not incluir_terminadas:
        tareas = [t for t in tareas if t['status'] != 'Terminado']
    if importancia:
        tareas = [t for t in tareas if t['importancia'] == importancia]
    if persona:
        tareas = [t for t in tareas if normalizar(persona) in normalizar(t['persona'])]
    if texto:
        tareas = [t for t in tareas if normalizar(texto) in normalizar(t['nombre'])]
    if fecha_limite_desde:
        tareas = [t for t in tareas if t['fecha_limite'] and t['fecha_limite'] >= fecha_limite_desde]
    if fecha_limite_hasta:
        tareas = [t for t in tareas if t['fecha_limite'] and t['fecha_limite'] <= fecha_limite_hasta]

    return tareas


def _palabras(texto):
    return {p for p in normalizar(texto).split() if p not in PALABRAS_VACIAS and len(p) > 1}


def _raiz(palabra):
    """'clases' -> 'clas', 'clase' -> 'clas': para que singular y plural coincidan."""
    for final in ('es', 's', 'e'):
        if len(palabra) > 4 and palabra.endswith(final):
            return palabra[:-len(final)]
    return palabra


def _palabra_parecida(buscada, palabra):
    """Cuánto se parece una palabra de la consulta a una del nombre (0 si nada)."""
    if buscada == palabra or _raiz(buscada) == _raiz(palabra):
        return 1.0
    if len(buscada) >= 3 and palabra.startswith(buscada):
        return 0.9  # "gim" -> "gimnasio", "cumple" -> "cumpleaños"
    if len(buscada) >= 4:
        ratio = SequenceMatcher(None, buscada, palabra).ratio()
        if ratio >= 0.8:
            return ratio  # faltas de ortografía: "prctica" -> "práctica"
    return 0.0


def parecido(consulta, nombre):
    c, n = normalizar(consulta).strip(), normalizar(nombre).strip()
    if c == n:
        return 1.0
    if c in n:
        return 0.9
    palabras_c, palabras_n = _palabras(c), _palabras(n)
    cobertura = 0
    if palabras_c and palabras_n:
        cobertura = sum(max(_palabra_parecida(pc, pn) for pn in palabras_n) for pc in palabras_c) / len(palabras_c)
    # El parecido letra a letra de la frase entera solo cuenta si es alto (faltas de ortografía):
    # si no, "clase de mates" se parecería a "cumpleaños de mi abuela" solo por las letras sueltas
    ratio = SequenceMatcher(None, c, n).ratio()
    return max(cobertura * 0.85, ratio if ratio >= 0.75 else 0)


def elegir(puntuados, umbral=0.5, margen=0.15, maximo=5):
    """De una lista [(nota, ...)] ordenada de mayor a menor: la mejor si destaca claramente, o las primeras."""
    puntuados = [p for p in puntuados if p[0] >= umbral]
    if puntuados and (len(puntuados) == 1 or puntuados[0][0] - puntuados[1][0] >= margen):
        return puntuados[:1]
    # Las que se quedan muy por detrás de la mejor no merecen salir en la lista
    return [p for p in puntuados if p[0] >= puntuados[0][0] - 2 * margen][:maximo]


def buscar_por_nombre(consulta, incluir_terminadas=False):
    """Tareas cuyo nombre se parece a la consulta, de más a menos parecida."""
    candidatas = listar_tareas(incluir_terminadas=incluir_terminadas)
    puntuadas = sorted(((parecido(consulta, t['nombre']), t) for t in candidatas),
                       key=lambda par: par[0], reverse=True)
    return [t for _, t in elegir(puntuadas)]


# --- Carpetas y grupos por su nombre ("Universidad", "familia") ---------------------

def _por_nombre(consulta, opciones):
    """La opción ({'nombre': …}) que mejor encaja con lo escrito: igual, empieza igual, contiene o parecida."""
    buscado = normalizar(consulta or '').strip(' .,«»"\'')
    if not buscado:
        return None
    nombres = [(normalizar(o['nombre']).strip(), o) for o in opciones]
    for prueba in (lambda n: n == buscado, lambda n: n.startswith(buscado) or buscado.startswith(n),
                   lambda n: buscado in n or n in buscado):
        encajan = [o for n, o in nombres if prueba(n)]
        if len(encajan) == 1:
            return encajan[0]
        if encajan:
            return None  # ambiguo: mejor preguntar que elegir mal
    puntuadas = sorted(((parecido(consulta, o['nombre']), o) for o in opciones), key=lambda par: par[0], reverse=True)
    elegidas = elegir(puntuadas, umbral=0.6)  # solo si una destaca claramente
    return elegidas[0][1] if len(elegidas) == 1 else None


def carpeta_por_nombre(nombre):
    return _por_nombre(nombre, db.listar_carpetas())


def grupos_para_tareas():
    """Grupos del usuario actual que comparten tareas."""
    usuario = db.id_dueno()
    return db.grupos_de(usuario, tipo='tareas') if usuario else []


def grupo_por_nombre(nombre):
    return _por_nombre(re.sub(r'(?i)^(?:el\s+)?grupo\s+', '', nombre or ''), grupos_para_tareas())


def _lista_nombres(opciones, icono):
    return ', '.join(f'{icono} {o["nombre"]}' for o in opciones) or 'ninguno todavía'


def resolver_carpeta(nombre):
    """Id de la carpeta con ese nombre ('' -> None, sin carpeta). Si no existe, error con las que hay."""
    if not (nombre or '').strip():
        return None
    carpeta = carpeta_por_nombre(nombre)
    if carpeta is None:
        raise db.DatosNoValidos(f'No encuentro la carpeta «{nombre}». Tus carpetas: '
                                f'{_lista_nombres(db.listar_carpetas(), "📁")}')
    return carpeta['id']


def resolver_grupo(nombre):
    """Id del grupo con ese nombre ('' -> None, solo para ti). Si no existe, error con los que hay."""
    if not (nombre or '').strip():
        return None
    grupo = grupo_por_nombre(nombre)
    if grupo is None:
        raise db.DatosNoValidos(f'No encuentro el grupo «{nombre}» (o no comparte tareas). Tus grupos: '
                                f'{_lista_nombres(grupos_para_tareas(), "👨‍👩‍👧")}')
    return grupo['id']


# --- Ejecución (formato "herramienta" que también usa el LLM) ---------------------

def crear_tarea(nombre, importancia='Media', fecha_limite='', persona='', status='Sin Empezar', hora_limite='',
                carpeta=None, grupo=None, carpeta_id=None, grupo_id=None):
    """carpeta y grupo por su nombre (los usa el LLM) o directamente por id."""
    datos = {'nombre': nombre, 'importancia': importancia, 'fecha_limite': fecha_limite or '',
             'hora_limite': hora_limite or '', 'persona': persona, 'status': status or 'Sin Empezar'}
    validar_campos(datos)
    datos['fecha'] = date.today().strftime('%d/%m/%Y')
    carpeta_id = resolver_carpeta(carpeta) if carpeta else carpeta_id
    grupo_id = resolver_grupo(grupo) if grupo else grupo_id
    if carpeta_id:
        datos['carpeta_id'] = carpeta_id
    if grupo_id:
        datos['grupo_id'] = grupo_id
    tarea = db.insert_task(datos)
    _avisar_encargado(None, tarea)
    return tarea


def _avisar_encargado(antes, tarea):
    """Si la tarea es de un grupo y su encargado es otro miembro, se le avisa; 'aviso' dice a quién y si se pudo."""
    import asignaciones
    aviso = asignaciones.al_guardar(antes, tarea)
    if aviso:
        tarea['aviso'] = aviso


def actualizar_tarea(id, **cambios):
    # Por nombre (LLM): "carpeta": "Universidad" o "" para sacarla; "grupo": "Familia" o "" para dejar de compartir
    if 'carpeta' in cambios:
        cambios['carpeta_id'] = resolver_carpeta(cambios.pop('carpeta'))
    if 'grupo' in cambios:
        cambios['grupo_id'] = resolver_grupo(cambios.pop('grupo'))
    validar_campos(cambios)
    antes = db.fetch_task(id)
    tarea = db.update_task(id, cambios)
    if tarea is None:
        raise ValueError(f'No existe ninguna tarea con id {id}')
    _avisar_encargado(antes, tarea)
    return tarea


def eliminar_tarea(id):
    tarea = db.fetch_task(id)
    if tarea is None or not db.delete_task(id):
        raise ValueError(f'No existe ninguna tarea con id {id}')
    return {'borrada': tarea['nombre']}


HERRAMIENTAS = {
    'listar_tareas': lambda **kw: {'tareas': listar_tareas(**kw)},
    'crear_tarea': crear_tarea,
    'actualizar_tarea': actualizar_tarea,
    'eliminar_tarea': eliminar_tarea,
}


def ejecutar(nombre, argumentos):
    if nombre not in HERRAMIENTAS:
        raise ValueError(f'Herramienta desconocida: {nombre}')
    try:
        return HERRAMIENTAS[nombre](**argumentos)
    except TypeError as error:  # argumentos que sobran o faltan
        raise ValueError(f'Argumentos no válidos para {nombre}: {error}') from error
