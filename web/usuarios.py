"""Usuarios de Mi Notion: a qué chats del bot pertenece cada uno y gestión desde la terminal.

Uso (en el servidor, dentro del contenedor):
    python usuarios.py crear              crea un usuario (el primero es el administrador)
    python usuarios.py listar             muestra los usuarios y sus chats
    python usuarios.py aprobar USUARIO    aprueba a alguien que se ha registrado desde la web
    python usuarios.py clave USUARIO      le pone una contraseña nueva (y cierra sus sesiones)
    python usuarios.py chats USUARIO "34600111222,tg:123456789"
                                          sus chats de WhatsApp/Telegram (vacío "" para quitarlos)
    python usuarios.py borrar USUARIO

Las contraseñas se piden sin que se vean al escribir y solo se guarda su hash.
"""
from getpass import getpass
from pathlib import Path
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

import db


def chats_configurados():
    """Todos los chats que pueden usar el bot (los del .env), en el formato de los recordatorios."""
    chats = []
    if os.getenv('TOKEN') and os.getenv('WHATSAPP_PHONE_NUMBER_ID'):
        chats += [n.strip() for n in os.getenv('WHATSAPP_ALLOWED_NUMBERS', '').split(',') if n.strip()]
    if os.getenv('TELEGRAM_TOKEN'):
        chats += [f'tg:{u.strip()}' for u in os.getenv('TELEGRAM_ALLOWED_USERS', '').split(',') if u.strip().isdigit()]
    return chats


def chats_de(usuario):
    """Chats del bot de un usuario.

    Los que tenga apuntados; el administrador sin chats apuntados se queda con todos los del .env
    que no sean de otro usuario (así todo sigue como antes de que hubiera usuarios).
    """
    if usuario is None:
        return chats_configurados()
    if usuario['chats']:
        return list(usuario['chats'])
    if usuario['es_admin']:
        ajenos = db.chats_ajenos(usuario['id'])
        return [c for c in chats_configurados() if c not in ajenos]
    return []


def chats_en_uso(excepto_id=None):
    """Chats que ya son de algún usuario (también los del .env que tiene el administrador)."""
    return {c for u in db.listar_usuarios() if u['id'] != excepto_id for c in chats_de(u)}


def chats_del_bot():
    """Chats de los usuarios ya aprobados: el bot les contesta aunque no estén en el .env."""
    return {c for u in db.listar_usuarios() if u['estado'] == 'activo' for c in u['chats']}


def leer_whatsapp(texto):
    """'+34 600 11 12 22' -> '34600111222'. None si no parece un número; '' si está vacío."""
    numero = re.sub(r'[\s().-]', '', texto or '').lstrip('+')
    if numero.startswith('00'):
        numero = numero[2:]
    if not numero:
        return ''
    if len(numero) == 9 and numero[0] in '67':
        numero = '34' + numero  # móvil español sin prefijo
    return numero if re.fullmatch(r'\d{8,15}', numero) else None


def leer_telegram(texto):
    """'123456789' o 'tg:123456789' -> 'tg:123456789'. None si no es un id; '' si está vacío."""
    valor = (texto or '').strip().removeprefix('tg:')
    if not valor:
        return ''
    return f'tg:{valor}' if re.fullmatch(r'\d{3,15}', valor) else None


# --- Terminal ---------------------------------------------------------------------------

def _pedir_clave():
    import sesiones

    while True:
        clave = getpass('Contraseña (no se ve al escribir): ')
        error = sesiones.clave_valida(clave)
        if error:
            print(f'  {error}')
            continue
        if getpass('Repítela: ') != clave:
            print('  No coinciden, vuelve a probar')
            continue
        return sesiones.hash_clave(clave)


def _leer_chats(texto):
    chats = [c.strip() for c in (texto or '').split(',') if c.strip()]
    malos = [c for c in chats if not re.fullmatch(r'\d{6,15}|tg:\d{3,15}', c)]
    if malos:
        raise SystemExit(f'Chats no válidos: {", ".join(malos)}. WhatsApp: 34600111222 · Telegram: tg:123456789')
    return chats


def _buscar(nombre):
    usuario = db.usuario_por_nombre(nombre)
    if usuario is None:
        raise SystemExit(f'No existe el usuario «{nombre}»')
    return usuario


def crear():
    primero = not db.hay_usuarios()
    if primero:
        print('Primer usuario: será el administrador (ve tu correo, Google Calendar y el estado del bot).')
    usuario = input('Usuario para entrar (p. ej. alvaro): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9._-]{2,40}', usuario):
        raise SystemExit('Usa entre 2 y 40 letras sin tildes, números, puntos, guiones o guiones bajos')
    if db.usuario_por_nombre(usuario):
        raise SystemExit('Ese usuario ya existe')
    nombre = input('Nombre para el saludo (p. ej. Álvaro): ').strip() or usuario
    clave_hash = _pedir_clave()
    es_admin = primero or input('¿Administrador? (s/N): ').strip().lower() == 's'
    print('Sus chats del bot, separados por comas (WhatsApp: 34600111222 · Telegram: tg:123456789).')
    if primero:
        print('Si lo dejas vacío, el administrador se queda con todos los del .env que no sean de otro.')
    chats = _leer_chats(input('Chats: '))
    ajenos = chats_en_uso() & set(chats)
    if ajenos:
        raise SystemExit(f'Estos chats ya son de otro usuario: {", ".join(sorted(ajenos))}')
    db.crear_usuario(usuario, nombre, clave_hash, es_admin, chats)
    print(f'✓ Usuario «{usuario}» creado' + (' (administrador)' if es_admin else ''))


def listar():
    usuarios = db.listar_usuarios()
    if not usuarios:
        print('No hay usuarios. Crea el primero con: python usuarios.py crear')
    for u in usuarios:
        chats = ', '.join(chats_de(u)) or '(ninguno)'
        extra = ' (todos los del .env)' if u['es_admin'] and not u['chats'] else ''
        papel = 'admin' if u['es_admin'] else ('PENDIENTE' if u['estado'] == 'pendiente' else '')
        print(f'{u["id"]:>3}  {u["usuario"]:<16} {u["nombre"]:<16} {papel:<9}  chats: {chats}{extra}')


def main(argumentos):
    db.init_db()
    if not argumentos or argumentos[0] in ('-h', '--help', 'ayuda'):
        print(__doc__)
        return
    orden = argumentos[0]
    if orden == 'crear':
        crear()
    elif orden == 'listar':
        listar()
    elif orden == 'aprobar' and len(argumentos) == 2:
        usuario = _buscar(argumentos[1])
        db.aprobar_usuario(usuario['id'])
        print(f'✓ {usuario["usuario"]} aprobado: ya puede entrar')
    elif orden == 'clave' and len(argumentos) == 2:
        usuario = _buscar(argumentos[1])
        db.cambiar_clave(usuario['id'], _pedir_clave())
        print('✓ Contraseña cambiada; sus sesiones abiertas se han cerrado')
    elif orden == 'chats' and len(argumentos) == 3:
        usuario = _buscar(argumentos[1])
        chats = _leer_chats(argumentos[2])
        ajenos = chats_en_uso(usuario['id']) & set(chats)
        if ajenos:
            raise SystemExit(f'Estos chats ya son de otro usuario: {", ".join(sorted(ajenos))}')
        db.fijar_chats(usuario['id'], chats)
        print(f'✓ Chats de {usuario["usuario"]}: {", ".join(chats) or "(ninguno)"}')
    elif orden == 'borrar' and len(argumentos) == 2:
        usuario = _buscar(argumentos[1])
        if usuario['es_admin'] and sum(u['es_admin'] for u in db.listar_usuarios()) == 1:
            raise SystemExit('Es el único administrador: no se puede borrar')
        if input(f'¿Borrar a «{usuario["usuario"]}» con sus tareas, eventos y recordatorios? (s/N): ').lower() == 's':
            db.borrar_usuario(usuario['id'])
            print('✓ Borrado')
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main(sys.argv[1:])
