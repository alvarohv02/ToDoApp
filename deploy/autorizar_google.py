"""Autoriza a Mi Notion a usar Google Calendar (se ejecuta UNA vez, en tu PC, no en el servidor).

Uso (PowerShell, desde la carpeta del proyecto):
    python deploy\\autorizar_google.py

Te pide el ID y el secreto de cliente (el secreto se escribe sin que se vea, para que no quede en
pantalla ni en el historial de la terminal). Se abre el navegador, entras con tu cuenta de Google
y das permiso. Las credenciales se guardan en el archivo .env.google (no se muestran): copia su
contenido al .env del servidor y bórralo. El permiso pedido solo deja a la app gestionar los
calendarios que ella misma crea ("Mi Notion"), no el resto de tu Google Calendar.
"""
import base64
import getpass
import hashlib
import html
import http.server
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import requests

SCOPE = 'https://www.googleapis.com/auth/calendar.app.created'
PUERTO = 8765

ARCHIVO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env.google')

if len(sys.argv) > 1:
    sys.exit('Ya no se pasan las credenciales al ejecutarlo (quedarían en el historial): ejecuta el '
             'script sin nada más y te las pedirá.\n' + __doc__)
client_id = input('ID de cliente: ').strip()
client_secret = getpass.getpass('Secreto de cliente (no se verá al escribir): ').strip()
if not (client_id and client_secret):
    sys.exit('Hacen falta el ID y el secreto de cliente.')
redirect_uri = f'http://127.0.0.1:{PUERTO}/'

# PKCE: el código que devuelve Google solo sirve junto con este secreto de un solo uso
verificador = secrets.token_urlsafe(64)
reto = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b'=').decode()
estado = secrets.token_urlsafe(16)

url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode({
    'client_id': client_id,
    'redirect_uri': redirect_uri,
    'response_type': 'code',
    'scope': SCOPE,
    'access_type': 'offline',   # para obtener un token permanente (refresh token)
    'prompt': 'consent',
    'code_challenge': reto,
    'code_challenge_method': 'S256',
    'state': estado,
})

recibido = {}


class Respuesta(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parametros = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        if 'code' not in parametros and 'error' not in parametros:
            self.send_response(404)
            self.end_headers()
            return
        recibido.update(parametros)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        texto = 'Listo. Ya puedes cerrar esta pestaña y volver a la terminal.' if 'code' in parametros else \
            f'Google ha devuelto un error: {html.escape(parametros.get("error", ""))}'
        self.wfile.write(f'<h2 style="font-family:sans-serif">{texto}</h2>'.encode())
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *args):
        pass


servidor = http.server.HTTPServer(('127.0.0.1', PUERTO), Respuesta)
print('Abriendo el navegador para que des permiso a Mi Notion...')
print('Si no se abre solo, copia esta dirección en el navegador:\n\n' + url + '\n')
print('Google avisará de que la app "no está verificada": pulsa "Configuración avanzada" -> "Ir a ..." (es tu propia app).')
webbrowser.open(url)
servidor.serve_forever()

if 'error' in recibido:
    sys.exit(f'Google ha rechazado la autorización: {recibido["error"]}')
if recibido.get('state') != estado:
    sys.exit('La respuesta no coincide con la petición (state distinto). Vuelve a intentarlo.')

r = requests.post('https://oauth2.googleapis.com/token', timeout=30, data={
    'client_id': client_id,
    'client_secret': client_secret,
    'code': recibido['code'],
    'code_verifier': verificador,
    'redirect_uri': redirect_uri,
    'grant_type': 'authorization_code',
})
if not r.ok:
    sys.exit(f'No se pudo obtener el token: {r.status_code} {r.text}')
datos = r.json()
if 'refresh_token' not in datos:
    sys.exit('Google no ha devuelto un token permanente. Quita el acceso de la app en '
             'https://myaccount.google.com/permissions y vuelve a ejecutar el script.')

# Las credenciales van a un archivo, no a la pantalla: así no quedan en el historial de la terminal
with open(ARCHIVO, 'w', encoding='utf-8') as archivo:
    archivo.write(f'GOOGLE_CLIENT_ID={client_id}\n'
                  f'GOOGLE_CLIENT_SECRET={client_secret}\n'
                  f'GOOGLE_REFRESH_TOKEN={datos["refresh_token"]}\n')
try:
    os.chmod(ARCHIVO, 0o600)  # solo tú puedes leerlo (en Windows apenas tiene efecto)
except OSError:
    pass
print(f'\n✅ Autorizado. Las credenciales están en {ARCHIVO}')
print('Copia esas 3 líneas al .env del servidor (ver deploy/INSTALAR.md) y después borra el archivo.')
