"""Prueba qué usuario acepta un servidor de correo, con las cuentas del .env y sin mostrar contraseñas.

Se ejecuta dentro del contenedor (allí están las variables del .env), pasando cada cuenta con su dominio:

    docker compose exec -T notion python - upm=upm.es alumnos=alumnos.upm.es < deploy/probar_correo.py

Por cada cuenta prueba como mucho dos usuarios: el del .env y la otra forma (con o sin "@dominio"),
para no provocar un bloqueo por demasiados intentos fallidos.
"""
import imaplib
import os
import ssl
import sys

for argumento in sys.argv[1:]:
    ident, _, dominio = argumento.partition('=')
    clave_env = f'CORREO_{ident.upper()}_'
    usuario = os.getenv(clave_env + 'USUARIO', '').strip()
    clave = os.getenv(clave_env + 'CLAVE', '').replace(' ', '')
    servidor = os.getenv(clave_env + 'SERVIDOR', '').strip() or 'imap.gmail.com'
    if not (usuario and clave):
        print(f'{ident}: faltan {clave_env}USUARIO o {clave_env}CLAVE en el .env')
        continue
    if '@' in usuario:
        variantes = [usuario, usuario.split('@')[0]]
    else:
        variantes = [usuario] + ([f'{usuario}@{dominio}'] if dominio else [])
    print(f'{ident} ({servidor}):')
    for variante in variantes:
        forma = 'con @' + variante.split('@')[1] if '@' in variante else 'sin dominio'
        try:
            conexion = imaplib.IMAP4_SSL(servidor, 993, ssl_context=ssl.create_default_context(), timeout=20)
            conexion.login(variante, clave)
            conexion.logout()
            print(f'  ✔ entra con el usuario {forma}: pon CORREO_{ident.upper()}_USUARIO así en el .env')
            break
        except imaplib.IMAP4.error as error:
            print(f'  ✘ usuario {forma}: {error}')
        except OSError as error:
            print(f'  ✘ no se pudo conectar con {servidor}: {error}')
            break
