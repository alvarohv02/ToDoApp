"""Aviso al encargado de una tarea de grupo: si alguien del grupo pone a otro miembro como encargado,
el bot se lo dice por WhatsApp (o por Telegram si WhatsApp no deja).

El encargado se reconoce por el nombre con el que se registró o por su nombre de usuario (sin mirar
mayúsculas ni tildes), o solo por el nombre de pila si no hay dos miembros que se llamen igual.
"""
from datetime import date
import logging
import os
import threading

import db
from fechas import formatear, normalizar

log = logging.getLogger(__name__)

EMOJI_IMPORTANCIA = {'Alta': '🔴', 'Media': '🟡', 'Baja': '🟢'}


def _igual(a, b):
    return normalizar(a or '').strip() == normalizar(b or '').strip()


def encargado_del_grupo(tarea):
    """El miembro del grupo de la tarea que es su encargado, o None."""
    if not tarea or not tarea.get('grupo_id') or not (tarea.get('persona') or '').strip():
        return None
    miembros = db.miembros_de(tarea['grupo_id'])
    persona = tarea['persona']
    exactos = [m for m in miembros if _igual(persona, m['nombre']) or _igual(persona, m['usuario'])]
    if len(exactos) == 1:
        return exactos[0]
    if exactos:
        return None  # dos miembros con ese nombre: mejor no avisar a quien no es
    de_pila = [m for m in miembros if (normalizar(m['nombre']).split() or [''])[0] == normalizar(persona).strip()]
    return de_pila[0] if len(de_pila) == 1 else None


def _detalles(tarea, hoy):
    partes = []
    if tarea.get('fecha_limite'):
        cuando = formatear(tarea['fecha_limite'], hoy)
        partes.append(f'para {cuando}' + (f' a las {tarea["hora_limite"]}' if tarea.get('hora_limite') else ''))
    partes.append(f'{EMOJI_IMPORTANCIA.get(tarea["importancia"], "")} importancia {tarea["importancia"].lower()}'.strip())
    carpeta = _carpeta_del_grupo(tarea)
    if carpeta:
        partes.append(f'📁 {carpeta}')
    return partes


def _carpeta_del_grupo(tarea):
    """Nombre de la carpeta de la tarea solo si es del grupo (las personales no le dicen nada al otro)."""
    if not tarea.get('carpeta_id'):
        return ''
    with db.get_db_connection() as connection:
        fila = connection.execute('SELECT nombre, grupo_id FROM carpetas WHERE id = ?', (tarea['carpeta_id'],)).fetchone()
    return fila['nombre'] if fila and fila['grupo_id'] == tarea['grupo_id'] else ''


def textos_aviso(tarea, autor, grupo, hoy=None):
    """(mensaje completo, versión de una línea para la plantilla de WhatsApp)."""
    hoy = hoy or date.today()
    detalles = _detalles(tarea, hoy)
    completo = (f'👋 *{autor}* te ha puesto como encargado de una tarea del grupo *{grupo}*:\n'
                f'📝 *{tarea["nombre"]}*\n{" · ".join(detalles)}\n\n'
                f'Cuando la acabes, dímelo: «he terminado {tarea["nombre"][:1].lower() + tarea["nombre"][1:]}».')
    # Meta no deja saltos de línea en los parámetros de una plantilla
    fecha = f', {detalles[0]}' if tarea.get('fecha_limite') else ''
    linea = f'{autor} te ha puesto como encargado de «{tarea["nombre"]}» (grupo {grupo}){fecha}'
    return completo, linea


def _plantilla():
    """(nombre, idioma) de la plantilla de WhatsApp para estos avisos, o None. Sin una propia, la de recordatorios."""
    if os.getenv('WHATSAPP_TAREA_TEMPLATE'):
        return os.getenv('WHATSAPP_TAREA_TEMPLATE'), os.getenv('WHATSAPP_TAREA_TEMPLATE_LANG') or 'es'
    if os.getenv('WHATSAPP_REMINDER_TEMPLATE'):
        return os.getenv('WHATSAPP_REMINDER_TEMPLATE'), os.getenv('WHATSAPP_REMINDER_TEMPLATE_LANG') or 'es'
    return None


def canal(usuario):
    """Por dónde se le puede escribir ahora: ('whatsapp', chat), ('telegram', chat), ('plantilla', chat) o None.

    WhatsApp si esa persona habló al bot en las últimas 24 h (si no, Meta no deja escribirle libremente);
    si no, Telegram; si no, WhatsApp con una plantilla aprobada.
    """
    import avisos
    import usuarios

    chats = usuarios.chats_de(usuario)
    de_whatsapp = [c for c in chats if not c.startswith('tg:')]
    for chat in de_whatsapp:
        if avisos._dentro_de_ventana(chat):
            return 'whatsapp', chat
    for chat in chats:
        if chat.startswith('tg:'):
            return 'telegram', chat
    if de_whatsapp and _plantilla():
        return 'plantilla', de_whatsapp[0]
    return None


def _enviar(usuario, por_donde, completo, linea):
    import telegram_bot
    import whatsapp

    tipo, chat = por_donde
    try:
        if tipo == 'whatsapp':
            whatsapp.enviar_mensaje(chat, completo)
        elif tipo == 'telegram':
            telegram_bot.enviar_mensaje(int(chat[3:]), completo)
        else:
            nombre, idioma = _plantilla()
            whatsapp.enviar_plantilla(chat, nombre, idioma, [linea])
    except Exception as error:  # noqa: BLE001 - el aviso es opcional: nunca debe impedir guardar la tarea
        log.warning('No se pudo avisar a %s de una tarea asignada: %s', usuario['usuario'], error)


def motivo_sin_canal(usuario):
    """Por qué no se le puede avisar, para decírselo a quien asigna la tarea."""
    import usuarios
    if not usuarios.chats_de(usuario):
        return f'{usuario["nombre"]} no tiene WhatsApp ni Telegram en su cuenta'
    return (f'{usuario["nombre"]} no ha hablado con el bot en las últimas 24 h y WhatsApp no deja escribirle '
            'hasta que lo haga')


# Se puede cambiar en las pruebas para enviar sin hilos
enviar_en_segundo_plano = True


def al_guardar(antes, despues):
    """Tras crear (antes=None) o cambiar una tarea: avisa a su encargado si es otro miembro del grupo y
    acaba de serlo (tarea nueva, encargado nuevo o tarea que pasa a ese grupo).

    Devuelve None si no hay a quién avisar, o {'nombre': …, 'avisado': True} / {'nombre': …, 'avisado': False,
    'motivo': …} para decírselo a quien la ha creado.
    """
    if not despues or despues.get('status') == 'Terminado':
        return None
    if antes and _igual(antes.get('persona'), despues.get('persona')) and antes.get('grupo_id') == despues.get('grupo_id'):
        return None
    miembro = encargado_del_grupo(despues)
    autor = db.usuario_actual()
    if miembro is None or (autor and miembro['id'] == autor['id']):
        return None
    usuario = db.obtener_usuario(miembro['id'])
    grupo = db.obtener_grupo(despues['grupo_id'])
    if usuario is None or grupo is None or usuario['estado'] != 'activo':
        return None

    por_donde = canal(usuario)
    if por_donde is None:
        log.info('Sin forma de avisar a %s de una tarea asignada', usuario['usuario'])
        return {'nombre': usuario['nombre'], 'avisado': False, 'motivo': motivo_sin_canal(usuario)}

    completo, linea = textos_aviso(despues, autor['nombre'] if autor else 'Alguien', grupo['nombre'])
    if enviar_en_segundo_plano:
        threading.Thread(target=_enviar, args=(usuario, por_donde, completo, linea), daemon=True).start()
    else:
        _enviar(usuario, por_donde, completo, linea)
    return {'nombre': usuario['nombre'], 'avisado': True}
