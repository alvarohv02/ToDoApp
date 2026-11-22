from datetime import date, datetime
from pathlib import Path
import contextvars
import json
import os
import sqlite3
import uuid

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'tareas.sqlite3'

class DatosNoValidos(ValueError):
    """Error con un mensaje escrito para el usuario: se puede enseñar tal cual en la web o en el bot.

    Cualquier otra excepción puede llevar detalles internos y no debe llegar a la web.
    """

    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


ESTADOS = ['Sin Empezar', 'En Curso', 'Terminado']
IMPORTANCIAS = ['Alta', 'Media', 'Baja']
CAMPOS = ('id', 'nombre', 'importancia', 'fecha_limite', 'hora_limite', 'status', 'fecha', 'persona')


def get_db_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_db_connection() as connection:
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS tareas (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                importancia TEXT NOT NULL,
                fecha_limite TEXT,
                status TEXT NOT NULL,
                fecha TEXT NOT NULL,
                persona TEXT NOT NULL
            )
            '''
        )
        # Bases de datos anteriores no tenían hora límite: se añade la columna si falta
        columnas = {fila['name'] for fila in connection.execute('PRAGMA table_info(tareas)')}
        if 'hora_limite' not in columnas:
            connection.execute("ALTER TABLE tareas ADD COLUMN hora_limite TEXT NOT NULL DEFAULT ''")
        # Cada tarea es de un usuario. Las de antes de haber usuarios (sin dueño) son del administrador
        if 'usuario_id' not in columnas:
            connection.execute('ALTER TABLE tareas ADD COLUMN usuario_id INTEGER')
        # Tarea compartida con un grupo (familia): la ven y la cambian todos sus miembros
        if 'grupo_id' not in columnas:
            connection.execute('ALTER TABLE tareas ADD COLUMN grupo_id INTEGER')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_tareas_fecha_limite ON tareas (fecha_limite)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_tareas_status ON tareas (status)')

        # Historial de la conversación por WhatsApp (memoria del asistente)
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS whatsapp_mensajes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telefono TEXT NOT NULL,
                rol TEXT NOT NULL,
                contenido TEXT NOT NULL,
                creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        connection.execute('CREATE INDEX IF NOT EXISTS idx_wa_telefono ON whatsapp_mensajes (telefono, id)')

        # IDs de mensajes ya procesados: Meta reintenta los webhooks y no queremos duplicar tareas
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS whatsapp_procesados (
                wa_id TEXT PRIMARY KEY,
                creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )

        # Recordatorios: destino es "tg:<chat_id>" (Telegram) o el número de WhatsApp
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS recordatorios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                destino TEXT NOT NULL,
                texto TEXT NOT NULL,
                cuando TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                intentos INTEGER NOT NULL DEFAULT 0,
                creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        connection.execute('CREATE INDEX IF NOT EXISTS idx_recordatorios_cuando ON recordatorios (estado, cuando)')

        # Eventos del calendario (clases, cumpleaños...): no generan avisos
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                categoria TEXT NOT NULL DEFAULT 'Otro',
                fecha TEXT NOT NULL,
                hora_inicio TEXT NOT NULL DEFAULT '',
                hora_fin TEXT NOT NULL DEFAULT '',
                repeticion TEXT NOT NULL DEFAULT '',
                hasta TEXT NOT NULL DEFAULT ''
            )
            '''
        )
        # Cada evento es de un usuario. Los de antes de haber usuarios (sin dueño) son del administrador
        columnas = {fila['name'] for fila in connection.execute('PRAGMA table_info(eventos)')}
        if 'usuario_id' not in columnas:
            connection.execute('ALTER TABLE eventos ADD COLUMN usuario_id INTEGER')
        if 'grupo_id' not in columnas:
            connection.execute('ALTER TABLE eventos ADD COLUMN grupo_id INTEGER')
        columnas = {fila['name'] for fila in connection.execute('PRAGMA table_info(recordatorios)')}
        if 'grupo_id' not in columnas:
            connection.execute('ALTER TABLE recordatorios ADD COLUMN grupo_id INTEGER')

        # Grupos (familias): qué tipos de cosas se pueden compartir en él y quién está dentro.
        # Un miembro 'invitado' aún no ha aceptado: no ve nada del grupo
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS grupos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                comparte TEXT NOT NULL DEFAULT 'tareas,eventos,recordatorios',
                creado_por INTEGER,
                creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS grupo_miembros (
                grupo_id INTEGER NOT NULL,
                usuario_id INTEGER NOT NULL,
                estado TEXT NOT NULL DEFAULT 'invitado',
                invitado_por INTEGER,
                PRIMARY KEY (grupo_id, usuario_id)
            )
            '''
        )

        # Usuarios de la web. La contraseña se guarda solo como hash (scrypt con sal, de Werkzeug).
        # chats: sus chats del bot ("34600111222,tg:123456789"), para saber de quién es cada mensaje.
        # version_sesion: al cambiarla se cierran todas sus sesiones abiertas
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
                nombre TEXT NOT NULL,
                clave_hash TEXT NOT NULL,
                es_admin INTEGER NOT NULL DEFAULT 0,
                chats TEXT NOT NULL DEFAULT '',
                version_sesion INTEGER NOT NULL DEFAULT 1,
                estado TEXT NOT NULL DEFAULT 'activo',
                creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        # estado: 'activo' o 'pendiente' (registrado desde la web, a falta de que lo apruebe el administrador)
        columnas = {fila['name'] for fila in connection.execute('PRAGMA table_info(usuarios)')}
        if 'estado' not in columnas:
            connection.execute("ALTER TABLE usuarios ADD COLUMN estado TEXT NOT NULL DEFAULT 'activo'")

        # Días concretos que se han quitado (o cambiado) de un evento que se repite
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS evento_excepciones (
                evento_id INTEGER NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,
                fecha TEXT NOT NULL,
                PRIMARY KEY (evento_id, fecha)
            )
            '''
        )

        # Sincronización con Google Calendar
        # Lo que ha cambiado cada mensaje del bot, para poder deshacerlo ("deshaz")
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS deshacer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telefono TEXT NOT NULL,
                resumen TEXT NOT NULL,
                cambios TEXT NOT NULL,
                creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        connection.execute('''CREATE TABLE IF NOT EXISTS ajustes (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)''')
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS google_vinculos (
                tipo TEXT NOT NULL,              -- 'evento' o 'tarea'
                local_id TEXT NOT NULL,
                google_id TEXT NOT NULL UNIQUE,
                firma TEXT NOT NULL,             -- contenido local en la última sincronización
                google_updated TEXT NOT NULL,    -- marca 'updated' de Google en la última sincronización
                PRIMARY KEY (tipo, local_id)
            )
            '''
        )
        # Calendario de Google en el que está cada elemento (uno por categoría); los antiguos estaban en "Otro"
        columnas = {fila['name'] for fila in connection.execute('PRAGMA table_info(google_vinculos)')}
        if 'cal' not in columnas:
            connection.execute("ALTER TABLE google_vinculos ADD COLUMN cal TEXT NOT NULL DEFAULT 'Otro'")

        # Pregunta pendiente ("¿cuál de estas?") a la espera de que el usuario elija
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS whatsapp_pendiente (
                telefono TEXT PRIMARY KEY,
                accion TEXT NOT NULL,
                creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )


def row_to_task(row):
    return {
        'id': row['id'],
        'nombre': row['nombre'],
        'importancia': row['importancia'],
        'fecha_limite': row['fecha_limite'] or '',
        'hora_limite': row['hora_limite'] or '',
        'status': row['status'],
        'fecha': row['fecha'],
        'persona': row['persona'],
        'grupo_id': row['grupo_id'],
        'usuario_id': row['usuario_id'],
    }


def fetch_all_tasks():
    condicion, parametros = _filtro_dueno('tareas')
    with get_db_connection() as connection:
        rows = connection.execute(
            f'''
            SELECT id, nombre, importancia, fecha_limite, hora_limite, status, fecha, persona, grupo_id, usuario_id
            FROM tareas
            WHERE {condicion}
            ORDER BY
                CASE WHEN fecha_limite IS NULL OR fecha_limite = '' THEN 1 ELSE 0 END,
                fecha_limite,
                CASE WHEN hora_limite = '' THEN 1 ELSE 0 END,
                hora_limite,
                fecha DESC,
                nombre COLLATE NOCASE
            ''',
            parametros,
        ).fetchall()

    return [row_to_task(row) for row in rows]


def fetch_task(task_id):
    condicion, parametros = _filtro_dueno('tareas')
    with get_db_connection() as connection:
        row = connection.execute(
            f'''
            SELECT id, nombre, importancia, fecha_limite, hora_limite, status, fecha, persona, grupo_id, usuario_id
            FROM tareas
            WHERE id = ? AND {condicion}
            ''',
            (task_id, *parametros),
        ).fetchone()

    return row_to_task(row) if row else None


def persona_por_defecto():
    """A quién se asigna una tarea si no se indica nadie.

    Para el administrador, PERSONA_POR_DEFECTO del .env; para los demás usuarios, su propio nombre.
    """
    usuario = _usuario.get()
    if usuario and usuario['id'] != id_admin_principal():
        return usuario['nombre']
    return os.getenv('PERSONA_POR_DEFECTO', '').strip() or 'Sin asignar'


def es_persona_por_defecto(persona):
    """True si no merece la pena mostrar la persona (sin asignar o la de por defecto)."""
    return not persona or persona in ('Sin asignar', persona_por_defecto())


def build_task_payload(data, existing=None):
    existing = existing or {}

    nombre = (data.get('nombre') or existing.get('nombre') or '').strip()
    importancia = (data.get('importancia') or existing.get('importancia') or '').strip()
    fecha_limite = data.get('fecha_limite') if 'fecha_limite' in data else existing.get('fecha_limite') or ''
    fecha_limite = fecha_limite or ''
    hora_limite = data.get('hora_limite') if 'hora_limite' in data else existing.get('hora_limite') or ''
    hora_limite = (hora_limite or '')[:5] if fecha_limite else ''  # sin fecha no tiene sentido una hora
    status = (data.get('status') or existing.get('status') or 'Sin Empezar').strip() or 'Sin Empezar'
    fecha = (data.get('fecha') or existing.get('fecha') or date.today().strftime('%d/%m/%Y')).strip()
    persona = (data.get('persona') or existing.get('persona') or persona_por_defecto()).strip() or persona_por_defecto()

    if not nombre:
        raise DatosNoValidos('El nombre de la tarea es obligatorio')

    if 'grupo_id' in data:
        grupo_id = comprobar_grupo('tareas', data.get('grupo_id'), existing or None)
    else:
        grupo_id = existing.get('grupo_id')

    if not importancia:
        raise DatosNoValidos('La importancia de la tarea es obligatoria')

    if hora_limite:
        try:
            datetime.strptime(hora_limite, '%H:%M')
        except ValueError as error:
            raise DatosNoValidos('Hora límite no válida (usa HH:MM)') from error

    return {
        'id': data.get('id') or existing.get('id') or uuid.uuid4().hex,
        'nombre': nombre,
        'importancia': importancia,
        'fecha_limite': fecha_limite,
        'hora_limite': hora_limite,
        'status': status,
        'fecha': fecha,
        'persona': persona,
        'grupo_id': grupo_id,
    }


def insert_task(data):
    task = build_task_payload(data)

    with get_db_connection() as connection:
        connection.execute(
            '''
            INSERT INTO tareas (id, nombre, importancia, fecha_limite, hora_limite, status, fecha, persona, usuario_id,
                                grupo_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (*(task[campo] for campo in CAMPOS), id_dueno(), task['grupo_id']),
        )
        connection.commit()

    _anotar({'accion': 'borrar', 'tabla': 'tareas', 'id': task['id']})
    return fetch_task(task['id']) or task


def update_task(task_id, data):
    """Devuelve la tarea actualizada o None si no existe."""
    existing = fetch_task(task_id)
    if existing is None:
        return None

    task = build_task_payload(data, existing)
    _anotar_estado('tareas', task_id)
    condicion, parametros = _filtro_dueno('tareas')

    with get_db_connection() as connection:
        connection.execute(
            f'''
            UPDATE tareas
            SET nombre = ?, importancia = ?, fecha_limite = ?, hora_limite = ?, status = ?, fecha = ?, persona = ?,
                grupo_id = ?
            WHERE id = ? AND {condicion}
            ''',
            (
                task['nombre'],
                task['importancia'],
                task['fecha_limite'],
                task['hora_limite'],
                task['status'],
                task['fecha'],
                task['persona'],
                task['grupo_id'],
                task['id'],
                *parametros,
            ),
        )
        connection.commit()

    return fetch_task(task_id)


def delete_task(task_id):
    """Devuelve True si se ha borrado algo."""
    if fetch_task(task_id) is None:
        return False  # no existe o es de otro usuario
    _anotar_estado('tareas', task_id)
    condicion, parametros = _filtro_dueno('tareas')
    with get_db_connection() as connection:
        cursor = connection.execute(f'DELETE FROM tareas WHERE id = ? AND {condicion}', (task_id, *parametros))
        connection.commit()

    return cursor.rowcount > 0


# --- WhatsApp -----------------------------------------------------------------

def marcar_procesado(wa_id):
    """Registra el ID del mensaje. Devuelve False si ya se había procesado."""
    with get_db_connection() as connection:
        try:
            connection.execute('INSERT INTO whatsapp_procesados (wa_id) VALUES (?)', (wa_id,))
            connection.commit()
        except sqlite3.IntegrityError:
            return False

    return True


def guardar_mensaje(telefono, rol, contenido):
    with get_db_connection() as connection:
        connection.execute(
            'INSERT INTO whatsapp_mensajes (telefono, rol, contenido) VALUES (?, ?, ?)',
            (telefono, rol, contenido),
        )
        connection.commit()


def historial(telefono, limite=20):
    """Últimos mensajes de la conversación, del más antiguo al más reciente."""
    with get_db_connection() as connection:
        rows = connection.execute(
            '''
            SELECT rol, contenido FROM whatsapp_mensajes
            WHERE telefono = ?
            ORDER BY id DESC
            LIMIT ?
            ''',
            (telefono, limite),
        ).fetchall()

    mensajes = [{'role': row['rol'], 'content': row['contenido']} for row in reversed(rows)]

    # La API exige que la conversación empiece por un mensaje del usuario
    while mensajes and mensajes[0]['role'] != 'user':
        mensajes.pop(0)

    return mensajes


def guardar_pendiente(telefono, accion):
    with get_db_connection() as connection:
        connection.execute(
            'INSERT OR REPLACE INTO whatsapp_pendiente (telefono, accion) VALUES (?, ?)',
            (telefono, json.dumps(accion, ensure_ascii=False)),
        )
        connection.commit()


def recuperar_pendiente(telefono, minutos=15):
    """Devuelve y borra la acción pendiente, si no ha caducado."""
    with get_db_connection() as connection:
        row = connection.execute(
            '''
            SELECT accion FROM whatsapp_pendiente
            WHERE telefono = ? AND creado_en >= datetime('now', ?)
            ''',
            (telefono, f'-{minutos} minutes'),
        ).fetchone()
        connection.execute('DELETE FROM whatsapp_pendiente WHERE telefono = ?', (telefono,))
        connection.commit()

    return json.loads(row['accion']) if row else None


# --- Recordatorios --------------------------------------------------------------
# "cuando" se guarda como hora local 'AAAA-MM-DD HH:MM' (el contenedor usa TZ=Europe/Madrid)

def crear_recordatorio(destino, texto, cuando, grupo_id=None):
    with get_db_connection() as connection:
        cursor = connection.execute(
            'INSERT INTO recordatorios (destino, texto, cuando, grupo_id) VALUES (?, ?, ?, ?)',
            (destino, texto, cuando.strftime('%Y-%m-%d %H:%M'), grupo_id),
        )
        connection.commit()
    _anotar({'accion': 'borrar', 'tabla': 'recordatorios', 'id': cursor.lastrowid})
    return cursor.lastrowid


def _de_estos_chats(destinos):
    """(condición, parámetros): recordatorios de esos chats o de los grupos del usuario actual."""
    destinos = [destinos] if isinstance(destinos, str) else list(destinos)
    condiciones = [f'destino IN ({", ".join("?" * len(destinos))})'] if destinos else []
    parametros = list(destinos)
    grupos, de_grupos = _de_mis_grupos('recordatorios')
    if de_grupos:
        condiciones.append(grupos)
        parametros += de_grupos
    return '(' + (' OR '.join(condiciones) or '0') + ')', parametros


def recordatorios_pendientes(destinos):
    """Recordatorios pendientes de uno o varios chats (p. ej. el WhatsApp y el Telegram de una persona)
    y los de sus grupos."""
    condicion, parametros = _de_estos_chats(destinos)
    with get_db_connection() as connection:
        rows = connection.execute(
            f"SELECT id, destino, texto, cuando, grupo_id FROM recordatorios WHERE {condicion} "
            "AND estado = 'pendiente' ORDER BY cuando",
            parametros,
        ).fetchall()
    return [dict(row) for row in rows]


def recordatorios_vencidos(ahora):
    with get_db_connection() as connection:
        rows = connection.execute(
            "SELECT id, destino, texto, cuando, intentos, grupo_id FROM recordatorios "
            "WHERE estado = 'pendiente' AND cuando <= ? ORDER BY cuando",
            (ahora.strftime('%Y-%m-%d %H:%M'),),
        ).fetchall()
    return [dict(row) for row in rows]


def actualizar_recordatorio(recordatorio_id, estado, intentos=None):
    _anotar_estado('recordatorios', recordatorio_id)
    with get_db_connection() as connection:
        if intentos is None:
            connection.execute('UPDATE recordatorios SET estado = ? WHERE id = ?', (estado, recordatorio_id))
        else:
            connection.execute('UPDATE recordatorios SET estado = ?, intentos = ? WHERE id = ?',
                               (estado, intentos, recordatorio_id))
        connection.commit()


def ultimo_mensaje_usuario(telefono):
    """Fecha (UTC, texto) del último mensaje que escribió el usuario, o None."""
    with get_db_connection() as connection:
        row = connection.execute(
            "SELECT MAX(creado_en) AS ultimo FROM whatsapp_mensajes WHERE telefono = ? AND rol = 'user'",
            (telefono,),
        ).fetchone()
    return row['ultimo'] if row else None


def listar_recordatorios(destinos=None, dias_historial=30):
    """Pendientes primero (por fecha) y después los enviados o fallidos de los últimos días.

    Con destinos, solo los de esos chats (los de un usuario) y los de sus grupos.
    """
    filtro, parametros = '', []
    if destinos is not None:
        condicion, parametros = _de_estos_chats(destinos)
        filtro = f'AND {condicion}'
    with get_db_connection() as connection:
        rows = connection.execute(
            f'''
            SELECT id, destino, texto, cuando, estado, grupo_id FROM recordatorios
            WHERE (estado = 'pendiente'
               OR (estado IN ('enviado', 'error') AND cuando >= strftime('%Y-%m-%d %H:%M', 'now', 'localtime', ?)))
               {filtro}
            ORDER BY CASE estado WHEN 'pendiente' THEN 0 ELSE 1 END,
                     CASE estado WHEN 'pendiente' THEN cuando END ASC,
                     cuando DESC
            ''',
            (f'-{dias_historial} days', *parametros),
        ).fetchall()
    return [dict(row) for row in rows]


def obtener_recordatorio(recordatorio_id):
    with get_db_connection() as connection:
        row = connection.execute(
            'SELECT id, destino, texto, cuando, estado, grupo_id FROM recordatorios WHERE id = ?',
            (recordatorio_id,),
        ).fetchone()
    return dict(row) if row else None


_SIN_CAMBIO = object()


def editar_recordatorio(recordatorio_id, texto, cuando, destino=None, grupo_id=_SIN_CAMBIO):
    """Cambia texto, hora y (si se indican) el chat y el grupo; vuelve a dejarlo pendiente para la nueva hora."""
    _anotar_estado('recordatorios', recordatorio_id)
    with get_db_connection() as connection:
        connection.execute(
            "UPDATE recordatorios SET texto = ?, cuando = ?, destino = COALESCE(?, destino), estado = 'pendiente', "
            'intentos = 0 WHERE id = ?',
            (texto, cuando.strftime('%Y-%m-%d %H:%M'), destino, recordatorio_id),
        )
        if grupo_id is not _SIN_CAMBIO:
            connection.execute('UPDATE recordatorios SET grupo_id = ? WHERE id = ?', (grupo_id, recordatorio_id))
        connection.commit()


# --- Eventos ----------------------------------------------------------------------

CAMPOS_EVENTO = ('titulo', 'categoria', 'fecha', 'hora_inicio', 'hora_fin', 'repeticion', 'hasta')


def _filtro_dueno(tipo):
    """(condición SQL, parámetros) para quedarse con las tareas o eventos que ve el usuario actual:
    los suyos y los compartidos en sus grupos que comparten ese tipo ('tareas' o 'eventos').

    Sin usuarios creados todavía no se filtra nada (como antes de existir el inicio de sesión).
    Lo que no tiene dueño es del administrador principal.
    """
    dueno = id_dueno()
    if dueno is None:
        return '1', ()
    if dueno == id_admin_principal():
        propio, parametros = '(usuario_id = ? OR usuario_id IS NULL)', [dueno]
    else:
        propio, parametros = 'usuario_id = ?', [dueno]
    grupos, de_grupos = _de_mis_grupos(tipo, dueno)
    return f'({propio} OR {grupos})', [*parametros, *de_grupos]


def listar_eventos():
    condicion, parametros = _filtro_dueno('eventos')
    with get_db_connection() as connection:
        rows = connection.execute(
            f'SELECT id, {", ".join(CAMPOS_EVENTO)}, grupo_id, usuario_id FROM eventos WHERE {condicion} ORDER BY fecha, hora_inicio',
            parametros,
        ).fetchall()
    return [dict(row) for row in rows]


def obtener_evento(evento_id):
    condicion, parametros = _filtro_dueno('eventos')
    with get_db_connection() as connection:
        row = connection.execute(
            f'SELECT id, {", ".join(CAMPOS_EVENTO)}, grupo_id, usuario_id FROM eventos WHERE id = ? AND {condicion}',
            (evento_id, *parametros),
        ).fetchone()
    return dict(row) if row else None


def guardar_evento(datos, evento_id=None):
    """Crea el evento (sin id) o lo sobrescribe. Devuelve su id.

    Con 'grupo_id' en los datos también cambia el grupo; sin él, lo deja como estaba (o sin grupo, si es nuevo).
    """
    campos = CAMPOS_EVENTO + (('grupo_id',) if 'grupo_id' in datos else ())
    valores = tuple(datos[campo] for campo in campos)
    if evento_id is not None:
        _anotar_estado('eventos', evento_id)
    condicion, parametros = _filtro_dueno('eventos')
    with get_db_connection() as connection:
        if evento_id is None:
            cursor = connection.execute(
                f'INSERT INTO eventos ({", ".join(campos)}, usuario_id) '
                f'VALUES ({", ".join("?" * len(campos))}, ?)',
                (*valores, id_dueno()),
            )
            evento_id = cursor.lastrowid
            _anotar({'accion': 'borrar', 'tabla': 'eventos', 'id': evento_id})
        else:
            connection.execute(
                f'UPDATE eventos SET {", ".join(f"{c} = ?" for c in campos)} WHERE id = ? AND {condicion}',
                (*valores, evento_id, *parametros),
            )
        connection.commit()
    return evento_id


def borrar_evento(evento_id):
    if obtener_evento(evento_id) is None:
        return False  # no existe o es de otro usuario
    _anotar_estado('eventos', evento_id)
    condicion, parametros = _filtro_dueno('eventos')
    with get_db_connection() as connection:
        cursor = connection.execute(f'DELETE FROM eventos WHERE id = ? AND {condicion}', (evento_id, *parametros))
        connection.commit()
    return cursor.rowcount > 0


def recordatorios_en_rango(destinos, desde, hasta):
    """Recordatorios pendientes de uno o varios chats entre dos fechas (ambas incluidas)."""
    return [r for r in recordatorios_pendientes(destinos) if desde.isoformat() <= r['cuando'][:10] <= hasta.isoformat()]


def anadir_excepcion(evento_id, fecha):
    """Quita un día concreto de un evento que se repite."""
    _anotar_estado('eventos', evento_id)
    with get_db_connection() as connection:
        connection.execute('INSERT OR IGNORE INTO evento_excepciones (evento_id, fecha) VALUES (?, ?)',
                           (evento_id, fecha.isoformat()))
        connection.commit()


def excepciones_por_evento():
    """{evento_id: {'AAAA-MM-DD', ...}} con los días quitados de cada serie."""
    with get_db_connection() as connection:
        rows = connection.execute('SELECT evento_id, fecha FROM evento_excepciones').fetchall()
    resultado = {}
    for row in rows:
        resultado.setdefault(row['evento_id'], set()).add(row['fecha'])
    return resultado


# --- Ajustes y vínculos con Google Calendar ------------------------------------------

def leer_ajuste(clave, defecto=None):
    with get_db_connection() as connection:
        row = connection.execute('SELECT valor FROM ajustes WHERE clave = ?', (clave,)).fetchone()
    return row['valor'] if row else defecto


def guardar_ajuste(clave, valor):
    with get_db_connection() as connection:
        if valor is None:
            connection.execute('DELETE FROM ajustes WHERE clave = ?', (clave,))
        else:
            connection.execute('INSERT OR REPLACE INTO ajustes (clave, valor) VALUES (?, ?)', (clave, str(valor)))
        connection.commit()


def vinculos(tipo=None):
    with get_db_connection() as connection:
        if tipo:
            rows = connection.execute('SELECT * FROM google_vinculos WHERE tipo = ?', (tipo,)).fetchall()
        else:
            rows = connection.execute('SELECT * FROM google_vinculos').fetchall()
    return [dict(row) for row in rows]


def vinculo_por_google(google_id):
    with get_db_connection() as connection:
        row = connection.execute('SELECT * FROM google_vinculos WHERE google_id = ?', (google_id,)).fetchone()
    return dict(row) if row else None


def guardar_vinculo(tipo, local_id, google_id, firma, google_updated, cal=None):
    """Guarda el vínculo. Sin `cal` se conserva el calendario que ya tuviera (o 'Otro')."""
    with get_db_connection() as connection:
        if cal is None:
            fila = connection.execute('SELECT cal FROM google_vinculos WHERE google_id = ? OR (tipo = ? AND local_id = ?)',
                                      (google_id, tipo, str(local_id))).fetchone()
            cal = fila['cal'] if fila else 'Otro'
        connection.execute('DELETE FROM google_vinculos WHERE google_id = ? AND NOT (tipo = ? AND local_id = ?)',
                           (google_id, tipo, str(local_id)))
        connection.execute(
            'INSERT OR REPLACE INTO google_vinculos (tipo, local_id, google_id, firma, google_updated, cal) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (tipo, str(local_id), google_id, firma, google_updated, cal),
        )
        connection.commit()


def borrar_vinculo(tipo, local_id):
    with get_db_connection() as connection:
        connection.execute('DELETE FROM google_vinculos WHERE tipo = ? AND local_id = ?', (tipo, str(local_id)))
        connection.commit()


def excepciones_de(evento_id):
    return excepciones_por_evento().get(evento_id, set())


def fijar_excepciones(evento_id, fechas):
    """Sustituye los días quitados de una serie (fechas en 'AAAA-MM-DD')."""
    _anotar_estado('eventos', evento_id)
    with get_db_connection() as connection:
        connection.execute('DELETE FROM evento_excepciones WHERE evento_id = ?', (evento_id,))
        connection.executemany('INSERT INTO evento_excepciones (evento_id, fecha) VALUES (?, ?)',
                               [(evento_id, f) for f in sorted(fechas)])
        connection.commit()


# --- Deshacer ------------------------------------------------------------------------
# Mientras el bot procesa un mensaje, cada cambio en tareas, eventos y recordatorios apunta en
# un "diario" cómo volver atrás: borrar lo que se ha creado o reponer la fila tal como estaba.
# Fuera de un mensaje del bot (la web, la sincronización con Google...) no se apunta nada.

MAX_DESHACER = 10
TABLAS_DESHACER = ('tareas', 'eventos', 'recordatorios')
_diario = contextvars.ContextVar('diario', default=None)


def empezar_diario():
    return _diario.set([])


def terminar_diario(marca):
    cambios = _diario.get()
    _diario.reset(marca)
    return cambios or []


def _anotar(cambio):
    diario = _diario.get()
    if diario is not None:
        diario.append(cambio)


def _anotar_estado(tabla, fila_id):
    """Apunta cómo está ahora una fila (antes de cambiarla o borrarla) para poder reponerla."""
    if _diario.get() is None:
        return
    with get_db_connection() as connection:
        fila = connection.execute(f'SELECT * FROM {tabla} WHERE id = ?', (fila_id,)).fetchone()
        dias = []
        if fila and tabla == 'eventos':
            dias = [r['fecha'] for r in connection.execute(
                'SELECT fecha FROM evento_excepciones WHERE evento_id = ?', (fila_id,))]
    if fila:
        _anotar({'accion': 'reponer', 'tabla': tabla, 'fila': dict(fila), 'excepciones': dias})


def guardar_deshacer(telefono, resumen, cambios):
    with get_db_connection() as connection:
        connection.execute('INSERT INTO deshacer (telefono, resumen, cambios) VALUES (?, ?, ?)',
                           (telefono, resumen, json.dumps(cambios, ensure_ascii=False)))
        # Solo se guardan los últimos mensajes de cada chat
        connection.execute(
            'DELETE FROM deshacer WHERE telefono = ? AND id NOT IN '
            '(SELECT id FROM deshacer WHERE telefono = ? ORDER BY id DESC LIMIT ?)',
            (telefono, telefono, MAX_DESHACER))
        connection.commit()


def hay_para_deshacer(telefono, horas=24):
    with get_db_connection() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM deshacer WHERE telefono = ? AND creado_en >= datetime('now', ?)",
            (telefono, f'-{horas} hours')).fetchone()[0]


def deshacer_ultimo(telefono, horas=24):
    """Revierte los cambios del último mensaje de ese chat. Devuelve su resumen, o None si no hay nada."""
    with get_db_connection() as connection:
        fila = connection.execute(
            "SELECT id, resumen, cambios FROM deshacer WHERE telefono = ? AND creado_en >= datetime('now', ?) "
            'ORDER BY id DESC LIMIT 1', (telefono, f'-{horas} hours')).fetchone()
        if fila is None:
            return None
        # Al revés de como se hicieron: si algo cambió dos veces, queda como estaba al principio
        for cambio in reversed(json.loads(fila['cambios'])):
            tabla = cambio['tabla']
            if tabla not in TABLAS_DESHACER:
                continue
            if cambio['accion'] == 'borrar':
                connection.execute(f'DELETE FROM {tabla} WHERE id = ?', (cambio['id'],))
            elif cambio['accion'] == 'reponer':
                columnas = list(cambio['fila'])
                connection.execute(
                    f'INSERT OR REPLACE INTO {tabla} ({", ".join(columnas)}) VALUES ({", ".join("?" * len(columnas))})',
                    [cambio['fila'][c] for c in columnas])
                if tabla == 'eventos':
                    connection.execute('DELETE FROM evento_excepciones WHERE evento_id = ?', (cambio['fila']['id'],))
                    connection.executemany('INSERT INTO evento_excepciones (evento_id, fecha) VALUES (?, ?)',
                                           [(cambio['fila']['id'], dia) for dia in cambio['excepciones']])
        connection.execute('DELETE FROM deshacer WHERE id = ?', (fila['id'],))
        connection.commit()
    return fila['resumen']


# --- Usuarios -----------------------------------------------------------------------
# El usuario "actual" (el que ha iniciado sesión en la web, o el dueño del chat que escribe al bot)
# se guarda en una variable de contexto, igual que el diario de deshacer: así las funciones de
# eventos no necesitan recibirlo y cada hilo o petición tiene el suyo.

CAMPOS_USUARIO = 'id, usuario, nombre, es_admin, chats, version_sesion, estado, creado_en'
_usuario = contextvars.ContextVar('usuario', default=None)


def usar_usuario(usuario):
    """Fija el usuario actual. Devuelve una marca para volver al anterior con soltar_usuario()."""
    return _usuario.set(usuario)


def soltar_usuario(marca):
    _usuario.reset(marca)


def usuario_actual():
    return _usuario.get()


def _usuario_a_dict(fila):
    if fila is None:
        return None
    usuario = dict(fila)
    usuario['es_admin'] = bool(usuario['es_admin'])
    usuario['chats'] = [c.strip() for c in usuario['chats'].split(',') if c.strip()]
    return usuario


def listar_usuarios():
    with get_db_connection() as connection:
        rows = connection.execute(f'SELECT {CAMPOS_USUARIO} FROM usuarios ORDER BY id').fetchall()
    return [_usuario_a_dict(r) for r in rows]


def hay_usuarios():
    with get_db_connection() as connection:
        return connection.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0] > 0


def obtener_usuario(usuario_id):
    with get_db_connection() as connection:
        fila = connection.execute(f'SELECT {CAMPOS_USUARIO} FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
    return _usuario_a_dict(fila)


def usuario_por_nombre(usuario):
    """El usuario con su hash (solo para comprobar la contraseña al iniciar sesión)."""
    with get_db_connection() as connection:
        fila = connection.execute(f'SELECT {CAMPOS_USUARIO}, clave_hash FROM usuarios WHERE usuario = ?',
                                  ((usuario or '').strip(),)).fetchone()
    if fila is None:
        return None
    datos = _usuario_a_dict({k: fila[k] for k in fila.keys() if k != 'clave_hash'})
    datos['clave_hash'] = fila['clave_hash']
    return datos


def crear_usuario(usuario, nombre, clave_hash, es_admin=False, chats=(), estado='activo'):
    with get_db_connection() as connection:
        cursor = connection.execute(
            'INSERT INTO usuarios (usuario, nombre, clave_hash, es_admin, chats, estado) VALUES (?, ?, ?, ?, ?, ?)',
            (usuario.strip(), nombre.strip(), clave_hash, int(es_admin), ','.join(chats), estado))
        connection.commit()
    return cursor.lastrowid


def cambiar_clave(usuario_id, clave_hash):
    """Cambia la contraseña y cierra todas las sesiones abiertas de ese usuario."""
    with get_db_connection() as connection:
        connection.execute('UPDATE usuarios SET clave_hash = ?, version_sesion = version_sesion + 1 WHERE id = ?',
                           (clave_hash, usuario_id))
        connection.commit()


def cerrar_sesiones(usuario_id):
    with get_db_connection() as connection:
        connection.execute('UPDATE usuarios SET version_sesion = version_sesion + 1 WHERE id = ?', (usuario_id,))
        connection.commit()


def fijar_chats(usuario_id, chats):
    with get_db_connection() as connection:
        connection.execute('UPDATE usuarios SET chats = ? WHERE id = ?', (','.join(chats), usuario_id))
        connection.commit()


def aprobar_usuario(usuario_id):
    with get_db_connection() as connection:
        connection.execute("UPDATE usuarios SET estado = 'activo' WHERE id = ?", (usuario_id,))
        connection.commit()


def contar_pendientes():
    with get_db_connection() as connection:
        return connection.execute("SELECT COUNT(*) FROM usuarios WHERE estado = 'pendiente'").fetchone()[0]


def borrar_usuario(usuario_id):
    """Borra el usuario junto con sus tareas, sus eventos y los recordatorios de sus chats.

    Lo que tenía compartido en un grupo se queda en el grupo.
    """
    usuario = obtener_usuario(usuario_id)
    if usuario is None:
        return
    for grupo in grupos_de(usuario_id, estado=None):
        salir_de_grupo(grupo['id'], usuario_id)
    with get_db_connection() as connection:
        eventos = [(f[0],) for f in connection.execute(
            'SELECT id FROM eventos WHERE usuario_id = ? AND grupo_id IS NULL', (usuario_id,))]
        connection.executemany('DELETE FROM evento_excepciones WHERE evento_id = ?', eventos)
        connection.execute('DELETE FROM eventos WHERE usuario_id = ? AND grupo_id IS NULL', (usuario_id,))
        connection.execute('DELETE FROM tareas WHERE usuario_id = ? AND grupo_id IS NULL', (usuario_id,))
        connection.executemany('DELETE FROM recordatorios WHERE destino = ?', [(c,) for c in usuario['chats']])
        connection.execute('DELETE FROM usuarios WHERE id = ?', (usuario_id,))
        connection.commit()


def id_admin_principal():
    """El primer administrador: dueño de lo que había antes de los usuarios (eventos, correo, Google)."""
    with get_db_connection() as connection:
        fila = connection.execute('SELECT MIN(id) FROM usuarios WHERE es_admin = 1').fetchone()
    return fila[0] if fila else None


def id_dueno():
    """Id del usuario actual; sin ninguno fijado (procesos de fondo), el administrador principal."""
    usuario = _usuario.get()
    return usuario['id'] if usuario else id_admin_principal()


def usuario_por_chat(chat):
    """El usuario dueño de un chat del bot. Un chat que no es de nadie se trata como del administrador."""
    for usuario in listar_usuarios():
        if usuario['estado'] == 'activo' and chat in usuario['chats']:
            return usuario
    admin = id_admin_principal()
    return obtener_usuario(admin) if admin else None


def chats_ajenos(usuario_id):
    """Chats que pertenecen a otros usuarios."""
    return {c for u in listar_usuarios() if u['id'] != usuario_id for c in u['chats']}


# --- Grupos (familias) ----------------------------------------------------------------------
# Cada tarea, evento o recordatorio puede pertenecer a un grupo: entonces lo ven y lo cambian
# todos sus miembros, siempre que el grupo comparta ese tipo de cosas.

TIPOS_GRUPO = {'tareas': 'Tareas', 'eventos': 'Calendario', 'recordatorios': 'Recordatorios'}
_SUBCONSULTA_GRUPOS = (
    "grupo_id IN (SELECT m.grupo_id FROM grupo_miembros m JOIN grupos g ON g.id = m.grupo_id "
    "WHERE m.usuario_id = ? AND m.estado = 'miembro' AND (',' || g.comparte || ',') LIKE ?)"
)


def _de_mis_grupos(tipo, usuario_id=None):
    """(condición, parámetros) para lo compartido en los grupos del usuario que comparten ese tipo.

    Sin usuario (procesos de fondo sin nadie fijado) no hay grupos: ('0', []).
    """
    if usuario_id is None:
        usuario = _usuario.get()
        usuario_id = usuario['id'] if usuario else None
    if usuario_id is None:
        return '0', []
    return _SUBCONSULTA_GRUPOS, [usuario_id, f'%,{tipo},%']


def _grupo_a_dict(fila):
    grupo = dict(fila)
    grupo['comparte'] = [t for t in grupo['comparte'].split(',') if t in TIPOS_GRUPO]
    return grupo


def grupos_de(usuario_id, estado='miembro', tipo=None):
    """Grupos de un usuario ('miembro': en los que está; 'invitado': invitaciones sin responder; None: ambos).

    Con tipo, solo los que comparten ese tipo de cosas.
    """
    filtro, parametros = '', [usuario_id]
    if estado:
        filtro += ' AND m.estado = ?'
        parametros.append(estado)
    with get_db_connection() as connection:
        filas = connection.execute(
            'SELECT g.id, g.nombre, g.comparte, m.estado, m.invitado_por FROM grupos g '
            f'JOIN grupo_miembros m ON m.grupo_id = g.id WHERE m.usuario_id = ?{filtro} ORDER BY g.nombre COLLATE NOCASE',
            parametros).fetchall()
    grupos = [_grupo_a_dict(f) for f in filas]
    return [g for g in grupos if tipo in g['comparte']] if tipo else grupos


def obtener_grupo(grupo_id):
    with get_db_connection() as connection:
        fila = connection.execute('SELECT id, nombre, comparte FROM grupos WHERE id = ?', (grupo_id,)).fetchone()
    return _grupo_a_dict(fila) if fila else None


def miembros_de(grupo_id, estado='miembro'):
    """Usuarios del grupo (con estado None, también los invitados), con su estado en el grupo."""
    filtro, parametros = '', [grupo_id]
    if estado:
        filtro, parametros = ' AND m.estado = ?', [grupo_id, estado]
    with get_db_connection() as connection:
        filas = connection.execute(
            f'SELECT u.id, u.usuario, u.nombre, m.estado FROM grupo_miembros m JOIN usuarios u ON u.id = m.usuario_id '
            f'WHERE m.grupo_id = ?{filtro} ORDER BY m.estado DESC, u.nombre COLLATE NOCASE', parametros).fetchall()
    return [dict(f) for f in filas]


def es_miembro(grupo_id, usuario_id):
    with get_db_connection() as connection:
        return connection.execute(
            "SELECT 1 FROM grupo_miembros WHERE grupo_id = ? AND usuario_id = ? AND estado = 'miembro'",
            (grupo_id, usuario_id)).fetchone() is not None


def _leer_comparte(comparte):
    return ','.join(t for t in TIPOS_GRUPO if t in comparte)


def crear_grupo(nombre, comparte, usuario_id):
    with get_db_connection() as connection:
        cursor = connection.execute('INSERT INTO grupos (nombre, comparte, creado_por) VALUES (?, ?, ?)',
                                    (nombre.strip(), _leer_comparte(comparte), usuario_id))
        connection.execute("INSERT INTO grupo_miembros (grupo_id, usuario_id, estado) VALUES (?, ?, 'miembro')",
                           (cursor.lastrowid, usuario_id))
        connection.commit()
    return cursor.lastrowid


def cambiar_grupo(grupo_id, nombre, comparte):
    with get_db_connection() as connection:
        connection.execute('UPDATE grupos SET nombre = ?, comparte = ? WHERE id = ?',
                           (nombre.strip(), _leer_comparte(comparte), grupo_id))
        connection.commit()


def invitar_a_grupo(grupo_id, usuario_id, invitado_por):
    """Devuelve False si ya estaba invitado o dentro."""
    with get_db_connection() as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO grupo_miembros (grupo_id, usuario_id, estado, invitado_por) VALUES (?, ?, 'invitado', ?)",
            (grupo_id, usuario_id, invitado_por))
        connection.commit()
    return cursor.rowcount > 0


def aceptar_invitacion(grupo_id, usuario_id):
    with get_db_connection() as connection:
        cursor = connection.execute(
            "UPDATE grupo_miembros SET estado = 'miembro' WHERE grupo_id = ? AND usuario_id = ? AND estado = 'invitado'",
            (grupo_id, usuario_id))
        connection.commit()
    return cursor.rowcount > 0


def salir_de_grupo(grupo_id, usuario_id):
    """Quita a alguien del grupo (o rechaza su invitación). Si ya no queda nadie dentro, el grupo se borra
    y lo que estaba compartido vuelve a ser solo de quien lo creó."""
    with get_db_connection() as connection:
        connection.execute('DELETE FROM grupo_miembros WHERE grupo_id = ? AND usuario_id = ?', (grupo_id, usuario_id))
        quedan = connection.execute("SELECT COUNT(*) FROM grupo_miembros WHERE grupo_id = ? AND estado = 'miembro'",
                                    (grupo_id,)).fetchone()[0]
        if not quedan:
            for tabla in ('tareas', 'eventos', 'recordatorios'):
                connection.execute(f'UPDATE {tabla} SET grupo_id = NULL WHERE grupo_id = ?', (grupo_id,))
            connection.execute('DELETE FROM grupo_miembros WHERE grupo_id = ?', (grupo_id,))
            connection.execute('DELETE FROM grupos WHERE id = ?', (grupo_id,))
        connection.commit()


def contar_invitaciones(usuario_id):
    with get_db_connection() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM grupo_miembros WHERE usuario_id = ? AND estado = 'invitado'", (usuario_id,)).fetchone()[0]


def comprobar_grupo(tipo, grupo_id, existente=None):
    """El grupo con el que se quiere compartir algo (o None, solo para quien lo crea). Lanza DatosNoValidos
    si el usuario actual no está en ese grupo o el grupo no comparte ese tipo de cosas.

    existente: lo que se está modificando (con su grupo_id y usuario_id), si no es nuevo.
    """
    grupo_id = int(grupo_id) if str(grupo_id or '').strip().isdigit() else None
    if existente is not None and grupo_id == existente.get('grupo_id'):
        return grupo_id  # sin cambios
    usuario = _usuario.get()
    if grupo_id is None:
        # Dejar de compartir algo lo esconde a los demás: solo puede hacerlo quien lo creó
        dueno = (existente or {}).get('usuario_id')
        if existente is not None and existente.get('grupo_id') and usuario and dueno not in (None, usuario['id']):
            raise DatosNoValidos('Solo quien lo creó puede dejar de compartirlo')
        return None
    if usuario is None or not es_miembro(grupo_id, usuario['id']):
        raise DatosNoValidos('No estás en ese grupo')
    grupo = obtener_grupo(grupo_id)
    if tipo not in grupo['comparte']:
        raise DatosNoValidos(f'El grupo «{grupo["nombre"]}» no comparte {TIPOS_GRUPO[tipo].lower()}')
    return grupo_id
