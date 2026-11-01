"""Sincronización en los dos sentidos con un calendario "Mi Notion" de Google Calendar.

- Los eventos de la web/bot y las tareas con fecha límite se copian a Google.
- Lo que se cree, cambie o borre en Google (p. ej. desde el iPhone) en ese calendario vuelve a la web.

El permiso pedido a Google (calendar.app.created) solo da acceso a los calendarios que crea esta app,
nunca al resto del Google Calendar del usuario.

Cada elemento sincronizado tiene un vínculo (tipo, id local, id de Google) con:
  - firma: el contenido local tal y como se sincronizó por última vez -> detecta cambios locales;
  - google_updated: la marca 'updated' de Google -> detecta cambios en Google y descarta los ecos propios.
Si algo cambia en los dos sitios entre dos sincronizaciones, gana la versión de la web.
"""
from datetime import date, datetime, timedelta
import hashlib
import json
import logging
import os
import re
import threading
import time
from urllib.parse import quote

import requests

import db
import eventos

log = logging.getLogger(__name__)

API = 'https://www.googleapis.com/calendar/v3'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
SCOPE = 'https://www.googleapis.com/auth/calendar.app.created'
ZONA = 'Europe/Madrid'
# El iPhone colorea cada evento con el color de su calendario (no admite colores por evento),
# así que hay un calendario por categoría, con el mismo color que en la web.
CALENDARIOS = {
    'Clase': ('Mi Notion · Clases', '#3e7ff0'),
    'Cumpleaños': ('Mi Notion · Cumpleaños', '#d6409f'),
    'Reunión': ('Mi Notion · Reuniones', '#11998e'),
    'Examen': ('Mi Notion · Exámenes', '#e5484d'),
    'Otro': ('Mi Notion · Otros', '#8a90a6'),
    'tarea': ('Mi Notion · Tareas', '#e2930f'),
}
INTERVALO = int(os.getenv('GOOGLE_SYNC_SEGUNDOS', '120'))

# Colores de evento de Google (solo se ven en Google, no en el iPhone): 2 salvia, 5 plátano, 6 mandarina, 8 grafito
COLOR_IMPORTANCIA = {'Alta': '6', 'Media': '5', 'Baja': '2'}
PREFIJO_TAREA, PREFIJO_HECHA = '☑ ', '✅ '

_cerrojo = threading.Lock()
_token = {'valor': None, 'caduca': 0}
estado = {'ultima': None, 'error': None, 'omitidos': 0}


class GoogleError(Exception):
    def __init__(self, codigo, mensaje):
        super().__init__(f'{codigo}: {mensaje}')
        self.codigo = codigo


def configurado():
    return all(os.getenv(v) for v in ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REFRESH_TOKEN'))


# --- Peticiones a Google ---------------------------------------------------------------

def _access_token():
    if _token['valor'] and time.time() < _token['caduca'] - 60:
        return _token['valor']
    r = requests.post(TOKEN_URL, timeout=20, data={
        'client_id': os.getenv('GOOGLE_CLIENT_ID'),
        'client_secret': os.getenv('GOOGLE_CLIENT_SECRET'),
        'refresh_token': os.getenv('GOOGLE_REFRESH_TOKEN'),
        'grant_type': 'refresh_token',
    })
    if not r.ok:
        raise GoogleError(r.status_code, f'No se pudo renovar el acceso a Google: {r.text[:200]}')
    datos = r.json()
    _token.update(valor=datos['access_token'], caduca=time.time() + datos.get('expires_in', 3600))
    return _token['valor']


def _peticion(metodo, ruta, **kwargs):
    r = requests.request(metodo, API + ruta, timeout=30,
                         headers={'Authorization': f'Bearer {_access_token()}'}, **kwargs)
    if r.status_code == 204 or (metodo == 'DELETE' and r.ok):
        return None
    if not r.ok:
        try:
            mensaje = r.json().get('error', {}).get('message', r.text)
        except ValueError:
            mensaje = r.text
        raise GoogleError(r.status_code, mensaje[:300])
    return r.json()


def _colorear(cal_id, color):
    """Pone el color del calendario (el que usa el iPhone). Si Google no lo permite, se sigue sin color."""
    try:
        _peticion('PATCH', f'/users/me/calendarList/{quote(cal_id)}', params={'colorRgbFormat': 'true'},
                  json={'backgroundColor': color, 'foregroundColor': '#ffffff', 'selected': True})
    except GoogleError as error:
        log.warning('No se pudo poner el color al calendario: %s', error)


def _calendarios():
    """{categoría: id del calendario de Google}. Crea los que falten; el antiguo "Mi Notion" pasa a ser "Otros"."""
    ids = {}
    for clave, (nombre, color) in CALENDARIOS.items():
        ajuste = f'google_cal:{clave}'
        cal_id = db.leer_ajuste(ajuste)
        if not cal_id and clave == 'Otro':
            cal_id = os.getenv('GOOGLE_CALENDAR_ID') or db.leer_ajuste('google_calendar_id')  # calendario antiguo
            if cal_id:
                try:
                    _peticion('PATCH', f'/calendars/{quote(cal_id)}', json={'summary': nombre})
                except GoogleError as error:
                    log.warning('No se pudo renombrar el calendario antiguo (sigue funcionando igual): %s', error)
                db.guardar_ajuste(ajuste, cal_id)
                _colorear(cal_id, color)
        if not cal_id:
            creado = _peticion('POST', '/calendars', json={'summary': nombre, 'timeZone': ZONA,
                                                           'description': 'Sincronizado con Mi Notion'})
            cal_id = creado['id']
            db.guardar_ajuste(ajuste, cal_id)
            _colorear(cal_id, color)
            log.info('Creado el calendario de Google "%s"', nombre)
        ids[clave] = cal_id
    return ids


def _clave(tipo, elemento):
    """Calendario en el que debe estar un elemento de la app."""
    if tipo == 'tarea':
        return 'tarea'
    return elemento['categoria'] if elemento['categoria'] in CALENDARIOS else 'Otro'


# --- De la app a Google ------------------------------------------------------------------

def _firma(datos):
    return hashlib.sha1(json.dumps(datos, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def firma_evento(evento):
    campos = {k: evento[k] for k in db.CAMPOS_EVENTO}
    return _firma({**campos, 'excepciones': sorted(db.excepciones_de(evento['id']))})


def firma_tarea(tarea):
    return _firma({k: tarea[k] for k in ('nombre', 'importancia', 'fecha_limite', 'hora_limite', 'status', 'persona')})


def _sumar_minutos(fecha, hora, minutos):
    momento = datetime.fromisoformat(f'{fecha}T{hora}') + timedelta(minutes=minutos)
    return min(momento, datetime.fromisoformat(f'{fecha}T23:59'))


def _inicio_fin(fecha, hora_inicio, hora_fin, minutos_por_defecto):
    if not hora_inicio:
        siguiente = (date.fromisoformat(fecha) + timedelta(days=1)).isoformat()
        return {'date': fecha}, {'date': siguiente}
    fin = f'{fecha}T{hora_fin}:00' if hora_fin else \
        _sumar_minutos(fecha, hora_inicio, minutos_por_defecto).strftime('%Y-%m-%dT%H:%M:00')
    return {'dateTime': f'{fecha}T{hora_inicio}:00', 'timeZone': ZONA}, {'dateTime': fin, 'timeZone': ZONA}


def _fechas_con_instancia_propia(google_id):
    """Días de una serie que en Google tienen una repetición modificada aparte (no se deben excluir)."""
    dias = set()
    for v in db.vinculos('evento'):
        if v['google_id'].startswith(google_id + '_'):
            sufijo = v['google_id'][len(google_id) + 1:]
            if re.match(r'\d{8}', sufijo):
                dias.add(f'{sufijo[:4]}-{sufijo[4:6]}-{sufijo[6:8]}')
    return dias


def cuerpo_evento(evento, google_id=None):
    inicio, fin = _inicio_fin(evento['fecha'], evento['hora_inicio'], evento['hora_fin'], 60)
    cuerpo = {
        'summary': evento['titulo'],
        'description': f'{eventos.EMOJI_CATEGORIA.get(evento["categoria"], "📌")} {evento["categoria"]} · creado en Mi Notion',
        'start': inicio,
        'end': fin,
        'extendedProperties': {'private': {'miNotion': 'evento', 'categoria': evento['categoria']}},
        'recurrence': [],
    }
    if evento['repeticion'] == 'semanal':
        regla = 'RRULE:FREQ=WEEKLY'
        if evento['hasta']:
            hasta = date.fromisoformat(evento['hasta'])
            regla += f';UNTIL={hasta:%Y%m%d}' if not evento['hora_inicio'] else f';UNTIL={hasta:%Y%m%d}T235959Z'
        cuerpo['recurrence'].append(regla)
    elif evento['repeticion'] == 'anual':
        cuerpo['recurrence'].append('RRULE:FREQ=YEARLY')
    if evento['repeticion']:
        excluir = sorted(db.excepciones_de(evento['id']) - (_fechas_con_instancia_propia(google_id) if google_id else set()))
        if excluir:
            if evento['hora_inicio']:
                hora = evento['hora_inicio'].replace(':', '')
                cuerpo['recurrence'].append(f'EXDATE;TZID={ZONA}:' + ','.join(f'{d.replace("-", "")}T{hora}00' for d in excluir))
            else:
                cuerpo['recurrence'].append('EXDATE;VALUE=DATE:' + ','.join(d.replace('-', '') for d in excluir))
    return cuerpo


def cuerpo_tarea(tarea):
    inicio, fin = _inicio_fin(tarea['fecha_limite'], tarea['hora_limite'], '', 30)
    hecha = tarea['status'] == 'Terminado'
    detalles = [f'Tarea · importancia {tarea["importancia"].lower()} · {tarea["status"]}']
    if not db.es_persona_por_defecto(tarea['persona']):
        detalles.append(f'Encargado: {tarea["persona"]}')
    return {
        'summary': (PREFIJO_HECHA if hecha else PREFIJO_TAREA) + tarea['nombre'],
        'description': '\n'.join(detalles) + '\nCreada en Mi Notion',
        'start': inicio,
        'end': fin,
        'colorId': '8' if hecha else COLOR_IMPORTANCIA.get(tarea['importancia'], '5'),
        'extendedProperties': {'private': {'miNotion': 'tarea'}},
        'transparency': 'transparent',  # una tarea no ocupa ese hueco del día
    }


# --- De Google a la app ------------------------------------------------------------------

def _local(valor):
    """Fecha/hora de Google -> (fecha 'AAAA-MM-DD', hora 'HH:MM' o '')."""
    if 'date' in valor:
        return valor['date'], ''
    momento = datetime.fromisoformat(valor['dateTime'].replace('Z', '+00:00'))
    try:
        from zoneinfo import ZoneInfo
        momento = momento.astimezone(ZoneInfo(ZONA))
    except Exception:
        momento = momento.astimezone()
    return momento.date().isoformat(), momento.strftime('%H:%M')


def leer_evento_google(item, categoria_calendario=None):
    """Evento de Google -> datos de un evento de la app. Devuelve (datos, excepciones) o (None, None) si no se admite."""
    fecha, hora_inicio = _local(item['start'])
    fecha_fin, hora_fin = _local(item['end'])
    if not hora_inicio or fecha_fin != fecha:
        hora_fin = ''
    datos = {'titulo': (item.get('summary') or '(sin título)').strip(), 'fecha': fecha, 'hora_inicio': hora_inicio,
             'hora_fin': hora_fin, 'repeticion': '', 'hasta': ''}
    excepciones = set()
    for linea in item.get('recurrence', []):
        if linea.startswith('RRULE:'):
            reglas = dict(p.split('=', 1) for p in linea[6:].split(';') if '=' in p)
            frecuencia = reglas.get('FREQ')
            if frecuencia == 'WEEKLY' and int(reglas.get('INTERVAL', '1')) == 1 and len(reglas.get('BYDAY', 'X').split(',')) == 1:
                datos['repeticion'] = 'semanal'
                if 'UNTIL' in reglas:
                    u = reglas['UNTIL']
                    datos['hasta'] = f'{u[:4]}-{u[4:6]}-{u[6:8]}'
                elif 'COUNT' in reglas:
                    datos['hasta'] = (date.fromisoformat(fecha) + timedelta(weeks=int(reglas['COUNT']) - 1)).isoformat()
            elif frecuencia == 'YEARLY' and int(reglas.get('INTERVAL', '1')) == 1 and 'COUNT' not in reglas:
                datos['repeticion'] = 'anual'
            else:
                return None, None  # repetición que la app no sabe representar (diaria, varios días por semana...)
        elif linea.startswith('EXDATE'):
            for valor in linea.split(':', 1)[1].split(','):
                excepciones.add(f'{valor[:4]}-{valor[4:6]}-{valor[6:8]}')
    categoria = categoria_calendario or item.get('extendedProperties', {}).get('private', {}).get('categoria')
    if categoria not in eventos.CATEGORIAS:
        import reglas  # se importa aquí para no cargar el motor de reglas si no hace falta
        normal = reglas.normalizar(datos['titulo'])
        categoria = next((c for patron, c in reglas.CATEGORIA_EVENTO if patron.search(normal)), 'Otro')
    datos['categoria'] = categoria
    return datos, excepciones


def _es_tarea(item):
    return item.get('extendedProperties', {}).get('private', {}).get('miNotion') == 'tarea'


def _aplicar_cambio(item, clave):
    """Lleva a la app un cambio que viene del calendario de Google `clave` (categoría o 'tarea')."""
    vinculo = db.vinculo_por_google(item['id'])
    if vinculo and vinculo['google_updated'] == item.get('updated') and vinculo['cal'] == clave:
        return  # es el eco de un cambio que hicimos nosotros
    categoria = clave if clave in eventos.CATEGORIAS else None

    # Repetición concreta de una serie (borrada o modificada en el móvil)
    if item.get('recurringEventId'):
        maestro = db.vinculo_por_google(item['recurringEventId'])
        dia, _ = _local(item['originalStartTime'])
        if maestro and maestro['tipo'] == 'evento':
            evento = db.obtener_evento(int(maestro['local_id']))
            if evento:
                db.anadir_excepcion(evento['id'], date.fromisoformat(dia))
                db.guardar_vinculo('evento', evento['id'], maestro['google_id'], firma_evento(evento), maestro['google_updated'])
        if item.get('status') == 'cancelled':
            if vinculo:
                db.borrar_evento(int(vinculo['local_id']))
                db.borrar_vinculo('evento', vinculo['local_id'])
            return
        datos, _ = leer_evento_google({**item, 'recurrence': []}, categoria)
        datos = eventos.validar(datos)
        if vinculo:
            evento_id = db.guardar_evento(datos, int(vinculo['local_id']))
        else:
            evento_id = db.guardar_evento(datos)
        db.guardar_vinculo('evento', evento_id, item['id'], firma_evento(db.obtener_evento(evento_id)),
                           item.get('updated', ''), clave)
        return

    if item.get('status') == 'cancelled':
        # Si se movió a otro calendario, en este aparece como borrado: no es un borrado de verdad
        if not vinculo or vinculo['cal'] != clave:
            return
        if vinculo['tipo'] == 'evento':
            db.borrar_evento(int(vinculo['local_id']))
        else:
            # Quitarla del calendario de Google = quitarle la fecha límite (la tarea sigue existiendo)
            tarea = db.fetch_task(vinculo['local_id'])
            if tarea:
                db.update_task(tarea['id'], {'fecha_limite': '', 'hora_limite': ''})
        db.borrar_vinculo(vinculo['tipo'], vinculo['local_id'])
        return

    if (vinculo and vinculo['tipo'] == 'tarea') or (not vinculo and (clave == 'tarea' or _es_tarea(item))):
        fecha, hora = _local(item['start'])
        nombre = re.sub(r'^(?:☑|✅)\s*', '', item.get('summary') or '').strip()
        if not vinculo:
            # Creada en el móvil dentro de "Mi Notion · Tareas": es una tarea nueva
            if not nombre:
                return
            tarea = herramientas_crear(nombre, fecha, hora)
        else:
            tarea = db.fetch_task(vinculo['local_id'])
            if tarea is None or firma_tarea(tarea) != vinculo['firma']:
                return  # ya no existe, o también cambió en la web: gana la web (se subirá después)
            tarea = db.update_task(tarea['id'], {'nombre': nombre or tarea['nombre'], 'fecha_limite': fecha, 'hora_limite': hora})
        db.guardar_vinculo('tarea', tarea['id'], item['id'], firma_tarea(tarea), item.get('updated', ''), clave)
        return

    datos, excepciones = leer_evento_google(item, categoria)
    if datos is None:
        estado['omitidos'] += 1
        log.info('Evento de Google con una repetición no compatible, se omite: %s', item.get('summary'))
        return
    datos = eventos.validar(datos)
    if vinculo:
        evento = db.obtener_evento(int(vinculo['local_id']))
        if evento and firma_evento(evento) != vinculo['firma']:
            return  # también cambió en la web: gana la web
        evento_id = db.guardar_evento(datos, int(vinculo['local_id'])) if evento else db.guardar_evento(datos)
    else:
        evento_id = db.guardar_evento(datos)
    db.fijar_excepciones(evento_id, excepciones)
    db.guardar_vinculo('evento', evento_id, item['id'], firma_evento(db.obtener_evento(evento_id)),
                       item.get('updated', ''), clave)


def herramientas_crear(nombre, fecha, hora):
    import herramientas  # se importa aquí para no crear un ciclo de importaciones
    return herramientas.crear_tarea(nombre, 'Media', fecha, '', hora_limite=hora)


def _traer_cambios(cal_id, clave):
    """Pide a Google lo que ha cambiado en un calendario desde la última vez (todo, la primera vez)."""
    ajuste = f'google_sync_token:{clave}'
    token = db.leer_ajuste(ajuste)
    # Sin filtros de fecha: Google solo da el punto de sincronización (nextSyncToken) en listados completos.
    # El calendario es solo de esta app, así que nunca es muy grande.
    params = {'showDeleted': 'true', 'maxResults': 250}
    if token:
        params['syncToken'] = token
    cambios = []
    while True:
        try:
            pagina = _peticion('GET', f'/calendars/{quote(cal_id)}/events', params=params)
        except GoogleError as error:
            if error.codigo == 410 and token:  # el punto de sincronización caducó: se empieza de nuevo
                db.guardar_ajuste(ajuste, None)
                return _traer_cambios(cal_id, clave)
            raise
        cambios.extend(pagina.get('items', []))
        if pagina.get('nextPageToken'):
            params['pageToken'] = pagina['nextPageToken']
            continue
        # Primero las series y después sus repeticiones sueltas
        cambios.sort(key=lambda i: bool(i.get('recurringEventId')))
        return cambios, pagina.get('nextSyncToken')


# --- Subir los cambios de la app ---------------------------------------------------------

def _subir(ids, clave, tipo, local_id, cuerpo, firma, vinculo):
    destino = ids[clave]
    if vinculo:
        origen = ids.get(vinculo['cal'], destino)
        google_id = vinculo['google_id']
        if '_' in google_id:
            destino, clave = origen, vinculo['cal']  # una repetición suelta se queda con su serie
        try:
            resultado = _peticion('PUT', f'/calendars/{quote(destino)}/events/{quote(google_id)}', json=cuerpo)
        except GoogleError as error:
            if error.codigo not in (404, 410):
                raise
            resultado = _peticion('POST', f'/calendars/{quote(destino)}/events', json=cuerpo)  # lo borraron en Google
    else:
        resultado = _peticion('POST', f'/calendars/{quote(destino)}/events', json=cuerpo)
    db.guardar_vinculo(tipo, local_id, resultado['id'], firma, resultado.get('updated', ''), clave)


def _borrar_en_google(ids, vinculo):
    cal_id = ids.get(vinculo['cal'], ids['Otro'])
    try:
        _peticion('DELETE', f'/calendars/{quote(cal_id)}/events/{quote(vinculo["google_id"])}')
    except GoogleError as error:
        if error.codigo not in (404, 410):
            raise
    db.borrar_vinculo(vinculo['tipo'], vinculo['local_id'])


def _subir_cambios(ids):
    por_clave = {(v['tipo'], v['local_id']): v for v in db.vinculos()}

    locales = {}
    for evento in db.listar_eventos():
        locales[('evento', str(evento['id']))] = ('evento', evento)
    for tarea in db.fetch_all_tasks():
        if tarea['fecha_limite']:
            locales[('tarea', str(tarea['id']))] = ('tarea', tarea)

    for clave, (tipo, elemento) in locales.items():
        vinculo = por_clave.get(clave)
        firma = firma_evento(elemento) if tipo == 'evento' else firma_tarea(elemento)
        clave_cal = _clave(tipo, elemento)
        en_su_sitio = vinculo and (vinculo['cal'] == clave_cal or '_' in vinculo['google_id'])
        if vinculo and vinculo['firma'] == firma and en_su_sitio:
            continue
        if vinculo and not en_su_sitio:
            # Cambió de calendario. Con el permiso limitado Google no deja "mover" eventos, así que se borra
            # del calendario antiguo y se crea en el nuevo. Las repeticiones modificadas sueltas de la serie
            # se desvinculan para subirse como eventos propios (si no, se perderían al borrar la serie).
            for suelta in db.vinculos('evento'):
                if suelta['google_id'].startswith(vinculo['google_id'] + '_'):
                    db.borrar_vinculo('evento', suelta['local_id'])
            _borrar_en_google(ids, vinculo)
            vinculo = None
        cuerpo = cuerpo_evento(elemento, vinculo and vinculo['google_id']) if tipo == 'evento' else cuerpo_tarea(elemento)
        if vinculo and tipo == 'evento' and '_' in vinculo['google_id'] and elemento['repeticion'] == '':
            cuerpo.pop('recurrence', None)  # repetición suelta de una serie de Google: no lleva reglas propias
        _subir(ids, clave_cal, tipo, elemento['id'], cuerpo, firma, vinculo)

    # Lo que ya no existe en la app (o la tarea perdió su fecha) se borra de Google
    for clave, vinculo in por_clave.items():
        if clave not in locales:
            _borrar_en_google(ids, vinculo)


# --- Ciclo de sincronización -----------------------------------------------------------

def sincronizar():
    """Una vuelta completa: primero se traen los cambios de Google y luego se suben los de la app."""
    if not configurado():
        raise GoogleError(0, 'Google Calendar no está configurado')
    with _cerrojo:
        estado['omitidos'] = 0
        try:
            ids = _calendarios()
            cambios, tokens = [], {}
            for clave, cal_id in ids.items():
                items, tokens[clave] = _traer_cambios(cal_id, clave)
                cambios.extend((clave, item) for item in items)
            # Lo borrado al final: un evento movido de calendario aparece borrado en uno y nuevo en otro
            cambios.sort(key=lambda par: par[1].get('status') == 'cancelled')
            for clave, item in cambios:
                try:
                    _aplicar_cambio(item, clave)
                except (ValueError, KeyError) as error:
                    estado['omitidos'] += 1
                    log.warning('No se pudo aplicar un cambio de Google (%s): %s', item.get('summary'), error)
            _subir_cambios(ids)
            # Los puntos de sincronización se guardan al final: si algo falla, la próxima vuelta lo reintenta
            for clave, token in tokens.items():
                if token:
                    db.guardar_ajuste(f'google_sync_token:{clave}', token)
            estado.update(ultima=datetime.now().isoformat(timespec='seconds'), error=None)
        except (GoogleError, requests.RequestException) as error:
            estado['error'] = str(error)
            log.warning('Error sincronizando con Google Calendar: %s', error)
            raise
    return dict(estado)


def _bucle():
    log.info('Sincronización con Google Calendar cada %d s', INTERVALO)
    while True:
        try:
            sincronizar()
        except Exception:
            pass  # ya está en estado['error'] y en el log
        time.sleep(INTERVALO)


def arrancar_en_segundo_plano():
    if configurado():
        threading.Thread(target=_bucle, name='google-calendar', daemon=True).start()
    else:
        log.info('Google Calendar sin configurar: no se sincroniza')
