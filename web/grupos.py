"""Grupos (familias) desde la página Cuenta: crear, invitar, aceptar invitaciones, salir y elegir qué se comparte.

Cualquier usuario puede crear un grupo e invitar a otros por su nombre de usuario; el invitado acepta o
rechaza desde su página Cuenta. Lo que se comparte en un grupo lo ven y lo pueden cambiar todos sus miembros.
"""
import db
import usuarios

MAX_GRUPOS = 20  # grupos (e invitaciones) por usuario
MAX_MIEMBROS = 30


def _nombre(formulario):
    nombre = (formulario.get('nombre') or '').strip()
    if not 1 <= len(nombre) <= 40:
        raise db.DatosNoValidos('Ponle al grupo un nombre de hasta 40 caracteres')
    return nombre


def _comparte(formulario):
    return [tipo for tipo in db.TIPOS_GRUPO if formulario.get(f'comparte_{tipo}') == '1']


def accion(usuario, formulario):
    """Hace la acción del formulario sobre un grupo. Devuelve (mensaje, error)."""
    que = formulario.get('accion')
    try:
        if que == 'grupo_crear':
            if len(db.grupos_de(usuario['id'], estado=None)) >= MAX_GRUPOS:
                return None, f'Como mucho puedes estar en {MAX_GRUPOS} grupos'
            nombre = _nombre(formulario)
            db.crear_grupo(nombre, _comparte(formulario), usuario['id'])
            return f'Grupo «{nombre}» creado. Ahora invita a quien quieras.', None

        valor = formulario.get('grupo') or ''
        grupo = db.obtener_grupo(int(valor)) if valor.isdigit() else None
        mio = next((g for g in db.grupos_de(usuario['id'], estado=None) if grupo and g['id'] == grupo['id']), None)
        if grupo is None or mio is None:
            return None, 'Ese grupo no existe o no estás en él'

        if que == 'grupo_aceptar' and mio['estado'] == 'invitado':
            db.aceptar_invitacion(grupo['id'], usuario['id'])
            return f'Ya estás en «{grupo["nombre"]}».', None
        if que == 'grupo_rechazar' and mio['estado'] == 'invitado':
            db.salir_de_grupo(grupo['id'], usuario['id'])
            return f'Invitación a «{grupo["nombre"]}» rechazada.', None
        if mio['estado'] != 'miembro':
            return None, 'Primero acepta la invitación a ese grupo'

        if que == 'grupo_guardar':
            db.cambiar_grupo(grupo['id'], _nombre(formulario), _comparte(formulario))
            return 'Cambios del grupo guardados.', None
        if que == 'grupo_invitar':
            return _invitar(usuario, grupo, formulario.get('invitado'))
        if que == 'grupo_quitar_invitacion':
            otro = (formulario.get('usuario_id') or '')
            invitado = next((m for m in db.miembros_de(grupo['id'], estado='invitado') if str(m['id']) == otro), None)
            if invitado is None:
                return None, 'Esa invitación ya no existe'
            db.salir_de_grupo(grupo['id'], invitado['id'])
            return f'Invitación a {invitado["nombre"]} retirada.', None
        if que == 'grupo_salir':
            db.salir_de_grupo(grupo['id'], usuario['id'])
            return f'Has salido de «{grupo["nombre"]}». Lo que compartiste sigue en el grupo.', None
    except db.DatosNoValidos as error:
        return None, error.mensaje
    return None, 'Acción no válida'


def _invitar(usuario, grupo, nombre_usuario):
    otro = db.usuario_por_nombre((nombre_usuario or '').strip()) if (nombre_usuario or '').strip() else None
    if otro is None or otro['estado'] != 'activo':
        return None, 'No hay ningún usuario con ese nombre'
    if otro['id'] == usuario['id']:
        return None, 'Ya estás en el grupo'
    if len(db.miembros_de(grupo['id'], estado=None)) >= MAX_MIEMBROS:
        return None, f'Un grupo puede tener como mucho {MAX_MIEMBROS} personas'
    if len(db.grupos_de(otro['id'], estado=None)) >= MAX_GRUPOS:
        return None, f'{otro["nombre"]} ya está en demasiados grupos'
    if not db.invitar_a_grupo(grupo['id'], otro['id'], usuario['id']):
        return None, f'{otro["nombre"]} ya está en el grupo o tiene la invitación pendiente'
    usuarios.avisar(otro, f'👨‍👩‍👧 {usuario["nombre"]} te ha invitado al grupo «{grupo["nombre"]}» de Mi Notion. '
                          'Acéptalo en la web, en tu página Cuenta.')
    return f'Invitación enviada a {otro["nombre"]}: tiene que aceptarla desde su página Cuenta.', None


def datos(usuario):
    """Lo que necesita la página Cuenta: sus grupos (con sus miembros) y sus invitaciones pendientes."""
    grupos = db.grupos_de(usuario['id'])
    for grupo in grupos:
        grupo['miembros'] = db.miembros_de(grupo['id'], estado=None)
    invitaciones = db.grupos_de(usuario['id'], estado='invitado')
    for invitacion in invitaciones:
        quien = db.obtener_usuario(invitacion['invitado_por']) if invitacion['invitado_por'] else None
        invitacion['de'] = quien['nombre'] if quien else ''
        invitacion['miembros'] = db.miembros_de(invitacion['id'])
    return {'grupos': grupos, 'invitaciones': invitaciones, 'tipos_grupo': db.TIPOS_GRUPO}
