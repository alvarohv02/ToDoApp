"""Asistente híbrido: reglas para lo habitual y LLM local (Ollama) para el resto.

Todo se ejecuta en tu servidor; no se envía nada a servicios de IA externos.
"""
from datetime import date, datetime, timedelta
import logging
import re
import os

import db
import eventos
import herramientas
import llm_local
import reglas
from fechas import (DIAS_SEMANA_BONITOS, extraer_fecha, extraer_momento, formatear, normalizar, numeros_a_digitos,
                    rango_periodo)

log = logging.getLogger(__name__)

EMOJI_IMPORTANCIA = {'Alta': '🔴', 'Media': '🟡', 'Baja': '🟢'}

AYUDA = """Puedes escribirme cosas como:
- *Apunta* entregar la práctica el viernes a las 14:00, importancia alta
- *Tengo que* comprar pan mañana
- *¿Qué tengo* hoy / esta semana / el viernes? (eventos, tareas y recordatorios)
- *Mis clases* / *cumpleaños este mes* / *eventos*
- *Añade al calendario* la cena el sábado a las 21
- *Resérvame* el viernes de 9 a 11 para la reunión con Juan
- *Tengo clase* de Cálculo los lunes y miércoles de 9 a 11 hasta el 18/12
- *Añade al calendario* el gimnasio todos los días a las 7 / pagar el alquiler el día 1 de cada mes
- *El cumple de* Marta es el 23 de octubre
- *Borra el evento* de la cena

🎙️ También puedes mandarme *notas de voz*, incluso con varias cosas a la vez:
«apunta comprar pan y recuérdame a las cinco llamar a Marta»
- *Tareas* sin fecha / importantes / en curso / atrasadas / de Marta
  (se pueden combinar: *tareas importantes sin fecha*)
- *He terminado* lo del dentista
- *Empiezo con* el informe
- *Mueve* la compra al lunes / *quita la fecha* de la compra
- *Cambia la importancia* del informe a alta
- *Asigna* el informe a Marta / *¿Qué tiene* Marta?
- *Borra* la tarea del gimnasio
- *Recuérdame* mañana a las 10 que tengo reunión
- *Avísame* en 20 minutos de sacar la ropa
- *Mis recordatorios* / *cancela el recordatorio* de la reunión
- *Deshaz* (o «me he equivocado»): vuelve atrás lo último que hice"""

VERBOS = {
    'completar': 'Marcada como hecha ✅',
    'empezar': 'En curso ▶️',
    'borrar': 'Borrada 🗑️',
    'mover': 'Movida 📅',
    'importancia': 'Importancia cambiada',
    'asignar': 'Asignada 👤',
}


# --- Formato ---------------------------------------------------------------------

def _fecha_tarea(tarea, hoy):
    """'vie 23/10' o 'vie 23/10 a las 14:00'."""
    texto = formatear(tarea['fecha_limite'], hoy)
    return f'{texto} a las {tarea["hora_limite"]}' if tarea.get('hora_limite') else texto


def _linea(tarea, hoy):
    partes = [f'{EMOJI_IMPORTANCIA.get(tarea["importancia"], "")} *{tarea["nombre"]}*'.strip()]
    if tarea['fecha_limite']:
        vencida = tarea['fecha_limite'] < hoy.isoformat() and tarea['status'] != 'Terminado'
        partes.append(_fecha_tarea(tarea, hoy) + (' ⚠️' if vencida else ''))
    if tarea['status'] == 'En Curso':
        partes.append('en curso')
    if not db.es_persona_por_defecto(tarea['persona']):
        partes.append(tarea['persona'])
    return '- ' + ' · '.join(partes)


def _bloque(titulo, tareas, hoy):
    if not tareas:
        return ''
    return f'*{titulo}* ({len(tareas)})\n' + '\n'.join(_linea(t, hoy) for t in tareas)


def _atrasadas(hoy):
    ayer = date.fromordinal(hoy.toordinal() - 1).isoformat()
    return herramientas.listar_tareas(fecha_limite_hasta=ayer)


# --- Intenciones -----------------------------------------------------------------

def _linea_evento(evento, hoy, con_fecha=True):
    partes = [formatear(evento['fecha'], hoy)] if con_fecha else []
    if eventos.horario(evento):
        partes.append(eventos.horario(evento))
    emoji = eventos.EMOJI_CATEGORIA.get(evento['categoria'], '📌')
    return f'- {emoji} *{evento["titulo"]}*' + (f' · {" · ".join(partes)}' if partes else '')


def _lineas_eventos(lista, hoy, con_fecha=True):
    """Líneas de una lista de ocurrencias; con varios días, lo diario sale una sola vez ("cada día")."""
    if not con_fecha:
        return [_linea_evento(e, hoy, False) for e in lista]
    dias = {}
    for e in lista:
        if e['repeticion'] == 'diaria':
            dias.setdefault(e['id'], []).append(e['fecha'])
    lineas, puestos = [], set()
    for e in lista:
        if len(dias.get(e['id'], [])) < 2:
            lineas.append(_linea_evento(e, hoy))
        elif e['id'] not in puestos:
            puestos.add(e['id'])
            fechas = dias[e['id']]
            partes = [f'cada día ({formatear(fechas[0], hoy)} – {formatear(fechas[-1], hoy)})']
            if eventos.horario(e):
                partes.append(eventos.horario(e))
            emoji = eventos.EMOJI_CATEGORIA.get(e['categoria'], '📌')
            lineas.append(f'- {emoji} *{e["titulo"]}* · {" · ".join(partes)}')
    return lineas


def _destinos(telefono):
    """Todos los chats de la misma persona, según CUENTAS_VINCULADAS en el .env.

    Formato: grupos separados por ';' y chats de cada grupo por ','. Ejemplo:
    CUENTAS_VINCULADAS=34600111222,tg:123456789;34600333444,tg:987654321
    """
    for grupo in os.getenv('CUENTAS_VINCULADAS', '').split(';'):
        chats = [c.strip() for c in grupo.split(',') if c.strip()]
        if telefono in chats:
            return chats
    return [telefono]


def _linea_recordatorio(recordatorio, hoy, con_fecha=True, con_canal=False):
    cuando = datetime.strptime(recordatorio['cuando'], '%Y-%m-%d %H:%M')
    momento = _momento_bonito(cuando, hoy) if con_fecha else f'a las {cuando:%H:%M}'
    canal = ''
    if con_canal:
        canal = ' (Telegram)' if recordatorio['destino'].startswith('tg:') else ' (WhatsApp)'
    return f'- {momento} · {recordatorio["texto"]}{canal}'


def _agenda(telefono, titulo, desde, hasta, hoy, con_atrasadas=False):
    """Eventos, tareas que vencen y recordatorios entre dos fechas, por categorías. None si no hay nada."""
    un_dia = desde == hasta
    secciones = [
        ('📅 Eventos', _lineas_eventos(eventos.en_rango(desde, hasta), hoy, not un_dia)),
        ('✅ Tareas que vencen', [_linea(t, hoy) for t in herramientas.listar_tareas(
            fecha_limite_desde=desde.isoformat(), fecha_limite_hasta=hasta.isoformat())]),
        ('⏰ Recordatorios', [_linea_recordatorio(r, hoy, not un_dia, len(_destinos(telefono)) > 1)
                             for r in db.recordatorios_en_rango(_destinos(telefono), desde, hasta)]),
    ]
    if con_atrasadas:
        secciones.append(('⚠️ Tareas atrasadas', [_linea(t, hoy) for t in _atrasadas(hoy)]))

    bloques = [f'*{nombre}* ({len(lineas)})\n' + '\n'.join(lineas) for nombre, lineas in secciones if lineas]
    if not bloques:
        return None
    return f'*{titulo}*\n\n' + '\n\n'.join(bloques)


def _titulo_periodo(periodo, desde=None, hasta=None):
    if periodo in ('hoy', 'manana', 'pasado manana') or desde is None:
        return periodo.replace('manana', 'mañana').capitalize()
    if desde == hasta:
        return f'{DIAS_SEMANA_BONITOS[desde.weekday()].capitalize()} {desde:%d/%m}'
    return periodo.replace('proxima', 'próxima').capitalize()


def _saludo(telefono, hoy):
    agenda = _agenda(telefono, 'Hoy', hoy, hoy, hoy, con_atrasadas=True)
    if agenda is None:
        return '¡Hola! 👋 Hoy no tienes nada en la agenda. ¿Apunto algo?' + _aviso_sin_fecha()
    return f'¡Hola! 👋\n\n{agenda}' + _aviso_sin_fecha()


def _listar_eventos(periodo, categoria, hoy):
    if not periodo and categoria == 'Clase':
        periodo = 'esta semana'  # las clases se repiten cada semana: 30 días serían demasiadas
    desde, hasta = rango_periodo(periodo, hoy)
    titulo = _titulo_periodo(periodo, desde, hasta)
    if desde is None:
        desde, hasta, titulo = hoy, hoy + timedelta(days=30), 'Próximos 30 días'
    lista = [e for e in eventos.en_rango(desde, hasta) if categoria is None or e['categoria'] == categoria]
    nombre = {'Clase': 'clases', 'Cumpleaños': 'cumpleaños', 'Examen': 'exámenes'}.get(categoria, 'eventos')
    if not lista:
        return f'No hay {nombre} en ese periodo.'
    lineas = _lineas_eventos(lista, hoy, desde != hasta)
    return f'*{nombre.capitalize()} · {titulo.lower()}* ({len(lineas)})\n' + '\n'.join(lineas)


def _listar_tareas_filtradas(filtros, hoy):
    """'tareas importantes sin fecha', 'tareas en curso de Marta'... Sin filtros: separadas por con/sin fecha."""
    status = filtros.get('status')
    tareas = herramientas.listar_tareas(status=status, incluir_terminadas=status == 'Terminado',
                                        importancia=filtros.get('importancia'), persona=filtros.get('persona'))
    descripcion = []
    if filtros.get('periodo'):
        desde, hasta = rango_periodo(filtros['periodo'], hoy)
        if desde:
            tareas = [t for t in tareas if t['fecha_limite'] and desde.isoformat() <= t['fecha_limite'] <= hasta.isoformat()]
            descripcion.append(f'para {filtros["periodo"].replace("manana", "mañana")}')
    if filtros.get('atrasadas'):
        tareas = [t for t in tareas if t['fecha_limite'] and t['fecha_limite'] < hoy.isoformat()]
        descripcion.append('atrasadas')
    if filtros.get('sin_fecha'):
        tareas = [t for t in tareas if not t['fecha_limite']]
        descripcion.append('sin fecha')
    if filtros.get('con_fecha'):
        tareas = [t for t in tareas if t['fecha_limite']]
        descripcion.append('con fecha')
    if filtros.get('importancia'):
        descripcion.append(f'de importancia {filtros["importancia"].lower()}')
    if status:
        descripcion.append({'En Curso': 'en curso', 'Sin Empezar': 'sin empezar', 'Terminado': 'terminadas'}[status])
    if filtros.get('persona'):
        descripcion.append(f'de {filtros["persona"]}')

    texto_filtros = ' '.join(descripcion)
    if not tareas:
        return f'No hay tareas {texto_filtros} 🎉' if texto_filtros else 'No tienes tareas pendientes 🎉'
    if texto_filtros:
        return _bloque(f'Tareas {texto_filtros}', tareas, hoy)

    # Sin filtros: primero las que tienen fecha (por orden) y luego las que no
    con_fecha = [t for t in tareas if t['fecha_limite']]
    sin_fecha = [t for t in tareas if not t['fecha_limite']]
    bloques = [_bloque('📅 Con fecha', con_fecha, hoy), _bloque('📝 Sin fecha', sin_fecha, hoy)]
    return f'*Tareas pendientes* ({len(tareas)})\n\n' + '\n\n'.join(b for b in bloques if b)


def _aviso_sin_fecha():
    """Recordatorio, al consultar la agenda, de que hay tareas que no salen por no tener fecha."""
    sin_fecha = [t for t in herramientas.listar_tareas() if not t['fecha_limite']]
    if not sin_fecha:
        return ''
    cuantas = '1 tarea' if len(sin_fecha) == 1 else f'{len(sin_fecha)} tareas'
    return f'\n\n📝 Además tienes {cuantas} sin fecha: escribe *tareas sin fecha* para verlas.'


def _listar(telefono, periodo, filtro, persona, solo_tareas, hoy):
    filtro = filtro.replace('  ', ' ')
    if persona:
        return _bloque(f'Tareas de {persona}', herramientas.listar_tareas(persona=persona), hoy) or \
            f'{persona} no tiene tareas pendientes.'
    if filtro in ('atrasadas', 'vencidas', 'retrasadas'):
        return _bloque('Atrasadas', _atrasadas(hoy), hoy) or 'No tienes nada atrasado 🎉'
    if filtro in ('urgentes', 'importantes'):
        return _bloque('Importancia alta', herramientas.listar_tareas(importancia='Alta'), hoy) or \
            'No tienes tareas de importancia alta pendientes.'
    if filtro == 'en curso':
        return _bloque('En curso', herramientas.listar_tareas(status='En Curso'), hoy) or 'No tienes nada en curso.'

    desde, hasta = rango_periodo(periodo, hoy)
    if desde is None:
        return _bloque('Pendientes', herramientas.listar_tareas(), hoy) or 'No tienes tareas pendientes 🎉'

    titulo = _titulo_periodo(periodo, desde, hasta)
    if not solo_tareas:
        agenda = _agenda(telefono, titulo, desde, hasta, hoy, con_atrasadas=desde == hoy)
        return (agenda or f'Nada en la agenda para {periodo.replace("manana", "mañana")} 🙌') + _aviso_sin_fecha()

    tareas = herramientas.listar_tareas(fecha_limite_desde=desde.isoformat(), fecha_limite_hasta=hasta.isoformat())
    bloques = [_bloque(titulo, tareas, hoy)]
    if desde == hoy:
        bloques.append(_bloque('Atrasadas', _atrasadas(hoy), hoy))
    texto = '\n\n'.join(b for b in bloques if b)
    return texto or f'Nada con fecha límite para {periodo.replace("manana", "mañana")} 🙌'


def _crear(accion, hoy):
    tarea = herramientas.crear_tarea(accion['nombre'], accion['importancia'], accion['fecha_limite'],
                                     accion['persona'], hora_limite=accion.get('hora_limite', ''))
    detalles = [f'{EMOJI_IMPORTANCIA[tarea["importancia"]]} importancia {tarea["importancia"].lower()}']
    if tarea['fecha_limite']:
        detalles.insert(0, f'para {_fecha_tarea(tarea, hoy)}')
    if not db.es_persona_por_defecto(tarea['persona']):
        detalles.append(f'encargado: {tarea["persona"]}')
    return f'📝 Apuntada: *{tarea["nombre"]}*\n{" · ".join(detalles)}'


def _aplicar(intencion, tarea, extra, hoy):
    if intencion == 'completar':
        herramientas.actualizar_tarea(tarea['id'], status='Terminado')
    elif intencion == 'empezar':
        herramientas.actualizar_tarea(tarea['id'], status='En Curso')
    elif intencion == 'borrar':
        herramientas.eliminar_tarea(tarea['id'])
    elif intencion == 'mover':
        # Si solo se da el día ("mueve X al lunes"), se conserva la hora que tuviera
        cambios = {k: extra[k] for k in ('fecha_limite', 'hora_limite') if k in extra}
        movida = herramientas.actualizar_tarea(tarea['id'], **cambios)
        if not extra['fecha_limite']:
            return f'Quitada la fecha límite de *{tarea["nombre"]}*'
        return f'{VERBOS[intencion]}: *{tarea["nombre"]}* → {_fecha_tarea(movida, hoy)}'
    elif intencion == 'importancia':
        herramientas.actualizar_tarea(tarea['id'], importancia=extra['importancia'])
        return f'{VERBOS[intencion]}: *{tarea["nombre"]}* → {EMOJI_IMPORTANCIA[extra["importancia"]]} {extra["importancia"]}'
    elif intencion == 'asignar':
        herramientas.actualizar_tarea(tarea['id'], persona=extra['persona'])
        return f'{VERBOS[intencion]}: *{tarea["nombre"]}* → {extra["persona"]}'
    return f'{VERBOS[intencion]}: *{tarea["nombre"]}*'


def _sobre_tarea(telefono, accion, hoy):
    intencion = accion['intencion']
    extra = {k: v for k, v in accion.items() if k not in ('intencion', 'objeto')}
    if intencion == 'borrar':
        return _borrar(telefono, accion['objeto'], hoy)
    candidatas = herramientas.buscar_por_nombre(accion['objeto'])

    if not candidatas:
        return f'No encuentro ninguna tarea parecida a «{accion["objeto"]}». Escribe *tareas* para ver la lista.'
    if len(candidatas) == 1:
        return _aplicar(intencion, candidatas[0], extra, hoy)

    db.guardar_pendiente(telefono, {'intencion': intencion, 'ids': [t['id'] for t in candidatas], 'extra': extra})
    opciones = '\n'.join(f'{i}. {t["nombre"]}' for i, t in enumerate(candidatas, 1))
    return f'Hay varias que encajan, ¿cuál?\n{opciones}\n\nResponde con el número (o *no* para cancelar).'


# --- Recordatorios ----------------------------------------------------------------

def _momento_bonito(cuando, hoy):
    return f'{formatear(cuando.date().isoformat(), hoy)} a las {cuando:%H:%M}'


def _recordatorio(telefono, accion, ahora):
    cuando = datetime.strptime(accion['cuando'], '%Y-%m-%d %H:%M')
    if cuando <= ahora:
        return 'Esa hora ya ha pasado 🤔 Dime otra.'
    db.crear_recordatorio(telefono, accion['texto'], cuando)
    respuesta = f'⏰ Te avisaré {_momento_bonito(cuando, ahora.date())}:\n{accion["texto"]}'
    respuesta += _aviso_solapes_recordatorio(telefono, cuando, ahora.date())
    if accion.get('hora_por_defecto'):
        respuesta += '\n\n_(No me dijiste la hora: te aviso a las 9:00. Puedes cambiarla en la web.)_'

    # WhatsApp solo deja escribir libremente en las 24 h siguientes a tu último mensaje
    fuera_de_ventana = cuando - ahora > timedelta(hours=23, minutes=50)
    if not telefono.startswith('tg:') and fuera_de_ventana and not os.getenv('WHATSAPP_REMINDER_TEMPLATE'):
        respuesta += ('\n\n⚠️ Ojo: WhatsApp solo me deja escribirte si me has hablado en las últimas 24 h. '
                      'Si no me escribes antes, este aviso no te llegará por aquí (por Telegram no hay límite).')
    return respuesta


def _pedir_hora(telefono, accion):
    """'recuérdame llamar a Marta' sin hora: se pregunta y se guarda a la espera de la respuesta."""
    db.guardar_pendiente(telefono, {'tipo': 'pedir_hora', 'texto': accion['texto'], 'fecha': accion['fecha'],
                                    'ids': [], 'extra': {}})
    return (f'¿Cuándo te aviso de «{accion["texto"]}»?\n'
            'Dime, por ejemplo, "a las 18", "mañana a las 10" o "en 30 minutos".')


def _completar_hora(telefono, pendiente, texto, ahora):
    """Respuesta a "¿cuándo te aviso?". None si el mensaje no es solo una hora."""
    momento, sobrante = extraer_momento(texto, ahora)
    if momento is None or sobrante.strip(' .!?'):
        return None
    # Si el día ya se había dicho ("recuérdame hoy llamar a Marta" -> "a las 6"), se respeta
    if pendiente.get('fecha') and extraer_fecha(texto, ahora.date())[0] is None:
        momento = datetime.combine(date.fromisoformat(pendiente['fecha']), momento.time())
    return _recordatorio(telefono, {'cuando': f'{momento:%Y-%m-%d %H:%M}', 'texto': pendiente['texto']}, ahora)


def _listar_recordatorios(telefono, hoy):
    destinos = _destinos(telefono)
    pendientes = db.recordatorios_pendientes(destinos)
    if not pendientes:
        return 'No tienes recordatorios pendientes.'
    lineas = [_linea_recordatorio(r, hoy, con_canal=len(destinos) > 1) for r in pendientes]
    return f'*Recordatorios* ({len(pendientes)})\n' + '\n'.join(lineas)


def _cancelar_recordatorio(telefono, objeto):
    pendientes = db.recordatorios_pendientes(_destinos(telefono))
    if objeto:
        consulta = normalizar(objeto)
        pendientes = [r for r in pendientes if consulta in normalizar(r['texto'])] or \
            [r for r in pendientes if herramientas.parecido(objeto, r['texto']) >= 0.5]
    if not pendientes:
        return 'No encuentro ese recordatorio. Escribe *mis recordatorios* para verlos.'
    if len(pendientes) == 1:
        db.actualizar_recordatorio(pendientes[0]['id'], 'cancelado')
        return f'🔕 Cancelado: {pendientes[0]["texto"]}'

    db.guardar_pendiente(telefono, {'intencion': 'cancelar_recordatorio', 'ids': [r['id'] for r in pendientes][:5],
                                    'extra': {}, 'tipo': 'recordatorio'})
    opciones = '\n'.join(f'{i}. {r["texto"]}' for i, r in enumerate(pendientes[:5], 1))
    return f'¿Cuál cancelo?\n{opciones}\n\nResponde con el número (o *no*).'


# --- Eventos del calendario ---------------------------------------------------------

REPETICION_BONITA = {'diaria': 'cada día', 'semanal': 'cada semana', 'mensual': 'cada mes', 'anual': 'cada año'}


# --- Solapes: avisar si lo nuevo choca con algo que ya había --------------------------------

SEMANAS_A_REVISAR = 8
MAX_SOLAPES = 5


def _tramo(evento):
    """(inicio, fin) en minutos del día de un evento con hora; sin hora de fin se cuenta 1 hora."""
    inicio = int(evento['hora_inicio'][:2]) * 60 + int(evento['hora_inicio'][3:5])
    if evento['hora_fin']:
        fin = int(evento['hora_fin'][:2]) * 60 + int(evento['hora_fin'][3:5])
    else:
        fin = inicio + 60
    return inicio, max(fin, inicio + 1)


def _linea_solape(evento, hoy):
    emoji = eventos.EMOJI_CATEGORIA.get(evento['categoria'], '📌')
    return f'- {emoji} *{evento["titulo"]}* · {formatear(evento["fecha"], hoy)} · {eventos.horario(evento)}'


def _solapes_eventos(nuevos, hoy):
    """Eventos (con hora) que coinciden en el tiempo con alguno de los recién creados."""
    nuevos = [e for e in nuevos if e['hora_inicio']]
    if not nuevos:
        return []
    ids_nuevos = {e['id'] for e in nuevos}
    desde = max(hoy, min(date.fromisoformat(e['fecha']) for e in nuevos))
    hasta = desde
    for e in nuevos:
        fin = date.fromisoformat(e['fecha']) if not e['repeticion'] else desde + timedelta(weeks=SEMANAS_A_REVISAR)
        if e['hasta']:
            fin = min(fin, date.fromisoformat(e['hasta']))
        hasta = max(hasta, fin)
    if hasta < desde:
        return []

    ocurrencias = [o for o in eventos.en_rango(desde, hasta) if o['hora_inicio']]
    mias = [o for o in ocurrencias if o['id'] in ids_nuevos]
    otras = [o for o in ocurrencias if o['id'] not in ids_nuevos]
    choques, vistos = [], set()
    for mia in mias:
        a_inicio, a_fin = _tramo(mia)
        for otra in otras:
            clave = (otra['id'], otra['fecha'])
            if otra['fecha'] != mia['fecha'] or clave in vistos:
                continue
            b_inicio, b_fin = _tramo(otra)
            if a_inicio < b_fin and b_inicio < a_fin:
                vistos.add(clave)
                choques.append(otra)
    return sorted(choques, key=lambda o: (o['fecha'], o['hora_inicio']))


def _aviso_solapes(choques, hoy):
    if not choques:
        return ''
    # Un evento que se repite y choca varias semanas sale una sola vez: "hoy · 09:00–11:00 (y 8 veces más)"
    por_evento = {}
    for o in choques:
        por_evento.setdefault(o['id'], []).append(o)
    lineas = []
    for repeticiones in list(por_evento.values())[:MAX_SOLAPES]:
        linea = _linea_solape(repeticiones[0], hoy)
        if len(repeticiones) > 1:
            linea += f' (y {len(repeticiones) - 1} {"vez" if len(repeticiones) == 2 else "veces"} más)'
        lineas.append(linea)
    if len(por_evento) > MAX_SOLAPES:
        lineas.append(f'- …y {len(por_evento) - MAX_SOLAPES} eventos más')
    return '\n\n⚠️ *Se solapa con:*\n' + '\n'.join(lineas)


def _aviso_solapes_recordatorio(telefono, cuando, hoy):
    """Al crear un aviso: eventos en marcha a esa hora y otros avisos a la misma hora."""
    minuto = cuando.hour * 60 + cuando.minute
    en_marcha = [o for o in eventos.en_rango(cuando.date(), cuando.date())
                 if o['hora_inicio'] and _tramo(o)[0] <= minuto < _tramo(o)[1]]
    misma_hora = [r for r in db.recordatorios_pendientes(_destinos(telefono))
                  if r['cuando'] == cuando.strftime('%Y-%m-%d %H:%M')]
    lineas = [_linea_solape(o, hoy) for o in en_marcha]
    # El aviso recién creado también está en la lista: los demás son los que coinciden
    lineas += [f'- ⏰ {r["texto"]} (otro aviso a la misma hora)' for r in misma_hora[:-1]]
    if not lineas:
        return ''
    return '\n\n⚠️ *A esa hora ya tienes:*\n' + '\n'.join(lineas[:MAX_SOLAPES])


def _crear_evento(accion, hoy):
    guardados = []
    for datos in accion['eventos']:
        guardados.append(db.obtener_evento(db.guardar_evento(eventos.validar(datos))))

    primero = guardados[0]
    emoji = eventos.EMOJI_CATEGORIA.get(primero['categoria'], '📌')
    if primero['repeticion'] == 'semanal':
        dias = ' y '.join(DIAS_SEMANA_BONITOS[date.fromisoformat(e['fecha']).weekday()] for e in guardados)
        cuando = [f'los {dias}', 'cada semana']
        if primero['hasta']:
            cuando[-1] += f' hasta el {date.fromisoformat(primero["hasta"]):%d/%m}'
    elif primero['repeticion'] in ('diaria', 'mensual'):
        cuando = [_cuando_evento(primero)]
        if date.fromisoformat(primero['fecha']) > hoy:
            cuando[0] += f', desde el {formatear(primero["fecha"], hoy)}'
        if primero['hasta']:
            cuando[0] += f' hasta el {date.fromisoformat(primero["hasta"]):%d/%m}'
    else:
        cuando = [formatear(primero['fecha'], hoy)]
        if primero['repeticion']:
            cuando.append(REPETICION_BONITA[primero['repeticion']])
    if eventos.horario(primero):
        cuando.insert(1, eventos.horario(primero))
    return (f'📅 Añadido al calendario: *{primero["titulo"]}*\n'
            f'{emoji} {primero["categoria"]} · {" · ".join(cuando)}' + _aviso_solapes(_solapes_eventos(guardados, hoy), hoy))


def _de_dia(fecha_iso, hoy):
    """'de mañana', 'de hoy' o 'del lun 09/11', para frases como «solo el de mañana»."""
    texto = formatear(fecha_iso, hoy)
    return f'de {texto}' if texto in ('hoy', 'mañana') else f'del {texto}'


def _borrar(telefono, objeto, hoy, con_tareas=True):
    """«borra X»: busca X entre las tareas y los eventos, aunque no se escriba el nombre exacto.

    Nunca borra a la primera: si hay una que encaja claramente pregunta «¿Borro…?», y si hay
    varias parecidas las enumera para elegir.
    """
    # "la clase de Cálculo del lunes": el día indica qué repetición borrar (y no forma parte del nombre)
    dia, resto = extraer_fecha(objeto, hoy)
    sin_dia = re.sub(r'(?i)\s+(?:del|de|el|la)$', '', resto.strip(' ,.')) if dia else ''

    def nota(nombre):
        return max(herramientas.parecido(objeto, nombre), herramientas.parecido(sin_dia, nombre) if sin_dia else 0)

    puntuados = [(nota(e['titulo']), 'evento', e) for e in db.listar_eventos()]
    if con_tareas:
        puntuados += [(nota(t['nombre']), 'tarea', t) for t in herramientas.listar_tareas(incluir_terminadas=True)]
    puntuados.sort(key=lambda p: p[0], reverse=True)
    elegidos = [(tipo, cosa) for _, tipo, cosa in herramientas.elegir(puntuados)]

    buscado = sin_dia or objeto
    if not elegidos:
        if not con_tareas:
            return f'No encuentro ningún evento parecido a «{buscado}».'
        return (f'No encuentro ninguna tarea ni evento parecido a «{buscado}». '
                'Escribe *tareas* o *qué tengo esta semana* para ver lo que hay.')
    if len(elegidos) == 1:
        tipo, cosa = elegidos[0]
        if tipo == 'evento':
            return _preguntar_borrar_evento(telefono, cosa, dia, hoy)
        db.guardar_pendiente(telefono, {'intencion': 'borrar', 'ids': [cosa['id']], 'extra': {}, 'confirmar': True})
        return f'¿Borro la tarea *{cosa["nombre"]}*? Responde *sí* o *no*.'

    db.guardar_pendiente(telefono, {'intencion': 'borrar', 'tipo': 'mixto', 'ids': [[t, c['id']] for t, c in elegidos],
                                    'extra': {'fecha': dia.isoformat() if dia else ''}})
    opciones = '\n'.join(f'{i}. 📝 {c["nombre"]} (tarea)' if t == 'tarea' else
                         f'{i}. {eventos.EMOJI_CATEGORIA.get(c["categoria"], "📅")} {c["titulo"]} ({_cuando_evento(c)})'
                         for i, (t, c) in enumerate(elegidos, 1))
    return f'Hay varias cosas que encajan, ¿cuál borro?\n{opciones}\n\nResponde con el número, *todos* o *no*.'


def _borrar_evento(telefono, objeto, hoy):
    return _borrar(telefono, objeto, hoy, con_tareas=False)


def _preguntar_borrar_evento(telefono, evento, dia, hoy):
    """Pregunta antes de borrar un evento; si se repite, si solo una vez o toda la serie."""
    if evento['repeticion'] and dia:
        if not eventos.ocurre_el(evento, dia):
            return f'*{evento["titulo"]}* no tiene repetición el {formatear(dia.isoformat(), hoy)} 🤔'
        db.guardar_pendiente(telefono, {'intencion': 'borrar_evento', 'ids': [evento['id']], 'tipo': 'evento',
                                        'confirmar': True, 'extra': {'alcance': 'uno', 'fecha': dia.isoformat()}})
        return (f'¿Borro solo *{evento["titulo"]}* {_de_dia(dia.isoformat(), hoy)}? '
                'El resto de repeticiones se mantiene. Responde *sí* o *no*.')
    if evento['repeticion']:
        proxima = eventos.proxima_ocurrencia(evento, hoy)
        db.guardar_pendiente(telefono, {'intencion': 'borrar_evento', 'ids': [evento['id'], evento['id']],
                                        'tipo': 'evento_serie',
                                        'extra': {'fecha': proxima.isoformat() if proxima else ''}})
        primera = f'Solo el próximo ({formatear(proxima.isoformat(), hoy)})' if proxima else 'Solo el próximo'
        return (f'*{evento["titulo"]}* se repite {REPETICION_BONITA[evento["repeticion"]]}. ¿Qué borro?\n'
                f'1. {primera}\n2. Toda la serie\n\nResponde con el número (o *no*).')
    db.guardar_pendiente(telefono, {'intencion': 'borrar_evento', 'ids': [evento['id']], 'extra': {},
                                    'tipo': 'evento', 'confirmar': True})
    return f'¿Borro *{evento["titulo"]}* del calendario? Responde *sí* o *no*.'


def _cuando_evento(evento):
    """'los lunes', 'todos los días', 'el día 5 de cada mes', 'cada año, el 23/10' o 'el 24/10'."""
    fecha = date.fromisoformat(evento['fecha'])
    if evento['repeticion'] == 'diaria':
        return 'todos los días'
    if evento['repeticion'] == 'mensual':
        return f'el día {fecha.day} de cada mes'
    if evento['repeticion'] == 'semanal':
        return f'los {DIAS_SEMANA_BONITOS[fecha.weekday()]}'
    if evento['repeticion'] == 'anual':
        return f'cada año, el {fecha:%d/%m}'
    return f'el {fecha:%d/%m}'


def _borrar_varios(pendiente):
    """«todos» tras una lista de cosas para borrar."""
    borrados = 0
    for tipo, id_ in pendiente['ids']:
        if tipo == 'tarea':
            borrados += db.delete_task(id_)
        else:
            borrados += bool(db.borrar_evento(id_))
    return f'🗑️ Borradas {borrados} cosas (tareas y eventos).'


def _resolver_pendiente(telefono, pendiente, numero, hoy):
    ids = pendiente['ids']
    if not 1 <= numero <= len(ids):
        return f'Elige un número del 1 al {len(ids)}.'
    if pendiente.get('tipo') == 'mixto':
        tipo, id_ = ids[numero - 1]
        if tipo == 'evento':
            evento = db.obtener_evento(id_)
            if evento is None:
                return 'Ese evento ya no existe.'
            if not evento['repeticion']:
                db.borrar_evento(evento['id'])
                return f'🗑️ Borrado del calendario: *{evento["titulo"]}*'
            # Se repite: falta saber si solo una vez o toda la serie
            dia = pendiente['extra'].get('fecha')
            return _preguntar_borrar_evento(telefono, evento, date.fromisoformat(dia) if dia else None, hoy)
        tarea = db.fetch_task(id_)
        if tarea is None:
            return 'Esa tarea ya no existe.'
        return _aplicar('borrar', tarea, {}, hoy)
    if pendiente.get('tipo') in ('evento', 'evento_serie'):
        evento = db.obtener_evento(ids[numero - 1])
        if evento is None:
            return 'Ese evento ya no existe.'
        extra = pendiente.get('extra') or {}
        solo_uno = extra.get('alcance') == 'uno' or (pendiente['tipo'] == 'evento_serie' and numero == 1)
        if solo_uno and extra.get('fecha'):
            eventos.borrar(evento, 'uno', date.fromisoformat(extra['fecha']))
            return (f'🗑️ Borrado solo el {_de_dia(extra["fecha"], hoy)}: *{evento["titulo"]}* '
                    '(el resto de repeticiones se mantiene)')
        db.borrar_evento(evento['id'])
        aviso = ' y todas sus repeticiones' if evento['repeticion'] else ''
        return f'🗑️ Borrado del calendario: *{evento["titulo"]}*{aviso}'
    if pendiente.get('tipo') == 'recordatorio':
        db.actualizar_recordatorio(ids[numero - 1], 'cancelado')
        return '🔕 Recordatorio cancelado.'
    tarea = db.fetch_task(ids[numero - 1])
    if tarea is None:
        return 'Esa tarea ya no existe.'
    return _aplicar(pendiente['intencion'], tarea, pendiente['extra'], hoy)


def _por_reglas(telefono, accion, pendiente, hoy, ahora):
    """Devuelve la respuesta, o None si este mensaje debe ir al LLM."""
    intencion = accion['intencion']

    if intencion == 'afirmacion':
        if pendiente and pendiente.get('confirmar'):
            return _resolver_pendiente(telefono, pendiente, 1, hoy)
        if pendiente:
            db.guardar_pendiente(telefono, pendiente)
            return 'Dime el número de la tarea (o *no* para cancelar).'
        return '👍'
    if intencion == 'seleccion':
        if pendiente is None or pendiente.get('confirmar'):
            return None
        if not 1 <= accion['numero'] <= len(pendiente['ids']):
            db.guardar_pendiente(telefono, pendiente)  # seguimos esperando una respuesta válida
        return _resolver_pendiente(telefono, pendiente, accion['numero'], hoy)
    if intencion == 'negacion':
        return 'Vale, no toco nada 👍' if pendiente else 'Vale 👍'
    if intencion == 'saludo':
        return _saludo(telefono, hoy)
    if intencion == 'gracias':
        return '¡A mandar! 💪'
    if intencion == 'ayuda':
        return AYUDA
    if intencion == 'listar':
        return _listar(telefono, accion['periodo'], accion['filtro'], accion['persona'],
                       accion.get('solo_tareas', False), hoy)
    if intencion == 'evento_sin_fecha':
        titulo = accion['titulo'] or 'eso'
        return (f'¿Para cuándo pongo «{titulo}» en el calendario? Dime el día (y la hora si quieres), por ejemplo:\n'
                f'"resérvame el jueves de 17 a 19 para {titulo}" o "resérvame los martes de 18 a 19 para {titulo}"')
    if intencion == 'seleccion_todos':
        if pendiente and pendiente.get('tipo') == 'evento_serie':
            return _resolver_pendiente(telefono, pendiente, 2, hoy)  # "todos" = toda la serie
        if pendiente and pendiente.get('tipo') == 'mixto':
            return _borrar_varios(pendiente)
        if pendiente and pendiente.get('tipo') == 'evento' and not pendiente.get('confirmar'):
            borrados = [e for e in (db.obtener_evento(i) for i in pendiente['ids']) if e and db.borrar_evento(e['id'])]
            return f'🗑️ Borrados del calendario: {len(borrados)} eventos'
        if pendiente:
            db.guardar_pendiente(telefono, pendiente)
            return 'Dime el número (o *no* para cancelar).'
        return None
    if intencion == 'crear_evento':
        return _crear_evento(accion, hoy)
    if intencion == 'borrar_evento':
        return _borrar_evento(telefono, accion['objeto'], hoy)
    if intencion == 'listar_tareas':
        return _listar_tareas_filtradas(accion['filtros'], hoy)
    if intencion == 'listar_eventos':
        return _listar_eventos(accion['periodo'], accion['categoria'], hoy)
    if intencion == 'crear':
        return _crear(accion, hoy)
    if intencion == 'recordatorio':
        return _recordatorio(telefono, accion, ahora)
    if intencion == 'recordatorio_sin_hora':
        return _pedir_hora(telefono, accion)
    if intencion == 'listar_recordatorios':
        return _listar_recordatorios(telefono, hoy)
    if intencion == 'cancelar_recordatorio':
        return _cancelar_recordatorio(telefono, accion['objeto'])
    return _sobre_tarea(telefono, accion, hoy)


def _responder_una(telefono, texto, pendiente, hoy, ahora):
    """Respuesta a una sola petición, o None si no se ha entendido."""
    accion = reglas.interpretar(texto, hoy, ahora)

    respuesta = None
    if pendiente and pendiente.get('tipo') == 'pedir_hora':
        respuesta = _completar_hora(telefono, pendiente, texto, ahora)
        accion = None if respuesta else accion
    if accion:
        log.info('Regla: %s', accion)
        try:
            respuesta = _por_reglas(telefono, accion, pendiente, hoy, ahora)
        except ValueError as error:
            respuesta = f'No he podido hacerlo: {error}'

    if respuesta is None and llm_local.disponible():
        log.info('Sin regla, se pasa al LLM local')
        respuesta = llm_local.responder(telefono, texto)
    return respuesta


MAX_RESUMEN_DESHACER = 400


def _deshacer(telefono):
    resumen = db.deshacer_ultimo(telefono)
    if resumen is None:
        return 'No hay nada que deshacer 🤷 (puedo deshacer lo que hayas hecho por aquí en las últimas 24 horas).'
    if len(resumen) > MAX_RESUMEN_DESHACER:
        resumen = resumen[:MAX_RESUMEN_DESHACER].rsplit('\n', 1)[0] + '\n…'
    respuesta = f'↩️ Deshecho. Esto ya no cuenta:\n\n{resumen}'
    if db.hay_para_deshacer(telefono):
        respuesta += '\n\n(Escribe *deshaz* otra vez para volver más atrás.)'
    return respuesta


def responder(telefono, texto, hoy=None, ahora=None):
    """Procesa un mensaje del usuario (puede llevar varias peticiones) y devuelve el texto de respuesta."""
    if ahora is None:
        ahora = datetime.combine(hoy, datetime.now().time()) if hoy else datetime.now()
    hoy = ahora.date()
    pendiente = db.recuperar_pendiente(telefono)

    # "a las cinco y media" -> "a las 5 y media": los audios llegan con los números escritos en letra
    # "Jarvis, dime qué tengo hoy" -> "qué tengo hoy"; luego "a las cinco" -> "a las 5"
    texto_cifras = numeros_a_digitos(reglas.quitar_llamada(texto))
    peticiones = reglas.dividir_peticiones(texto_cifras)

    # Todo lo que cambie este mensaje queda apuntado para poder deshacerlo luego
    marca = db.empezar_diario()
    try:
        if reglas.es_deshacer(texto_cifras):
            respuesta = _deshacer(telefono)
        elif len(peticiones) == 1:
            respuesta = _responder_una(telefono, texto_cifras, pendiente, hoy, ahora) or \
                'No te he entendido 🤔 Escribe *ayuda* para ver qué puedo hacer.'
        else:
            log.info('Mensaje con %d peticiones: %s', len(peticiones), peticiones)
            partes = []
            for peticion in peticiones:
                # La pregunta pendiente solo puede responderla la primera parte del mensaje
                parte = _responder_una(telefono, peticion, pendiente if not partes else None, hoy, ahora)
                partes.append(parte or f'🤔 No he entendido: «{peticion}»')
            respuesta = f'He apuntado {len(peticiones)} cosas:\n\n' + '\n\n'.join(
                f'*{i}.* {parte}' for i, parte in enumerate(partes, 1))
    finally:
        cambios = db.terminar_diario(marca)
    if cambios:
        db.guardar_deshacer(telefono, respuesta, cambios)

    db.guardar_mensaje(telefono, 'user', texto)
    db.guardar_mensaje(telefono, 'assistant', respuesta)
    return respuesta


def responder_audio(telefono, audio):
    """Transcribe una nota de voz y la procesa como si fuera un mensaje escrito."""
    import transcripcion  # se importa aquí para no cargar el reconocedor de voz si nunca llega un audio

    try:
        texto = transcripcion.transcribir(audio)
    except transcripcion.TranscripcionNoDisponible as error:
        log.error('Reconocimiento de voz no disponible: %s', error)
        return 'Ahora mismo no puedo escuchar audios 🙉 Escríbemelo, por favor.'
    except ValueError as error:
        log.warning('Audio no válido: %s', error)
        return 'No he podido abrir ese audio. ¿Me lo mandas otra vez o me lo escribes?'

    if not texto:
        return 'No he entendido nada en el audio 🙉 ¿Puedes repetirlo más despacio o escribírmelo?'
    log.info('Audio transcrito: %s', texto)
    return f'🎙️ _He entendido: «{texto}»_\n\n{responder(telefono, texto)}'


if __name__ == '__main__':
    # Chat por terminal para probar el asistente sin pasar por WhatsApp
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    print('Escribe tu mensaje (Ctrl+C para salir)')
    while True:
        print('\n🤖', responder('terminal', input('\n> ')))
