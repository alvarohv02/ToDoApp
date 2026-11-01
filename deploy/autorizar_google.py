"""Autoriza a Mi Notion a usar Google Calendar (se ejecuta UNA vez, en tu PC, no en el servidor).

Uso (PowerShell, desde la carpeta del proyecto):
    python deploy\\autorizar_google.py TU_ID_DE_CLIENTE TU_SECRETO_DE_CLIENTE

Se abre el navegador, entras con tu cuenta de Google y das permiso. El script imprime las líneas
que hay que añadir al .env del servidor. El permiso pedido solo deja a la app gestionar los
calendarios que ella misma crea ("Mi Notion"), no el resto de tu Google Calendar.
"""
import base64
import hashlib
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import requests

SCOPE = 'https://www.googleapis.com/auth/calendar.app.created'
PUERTO = 8765

if len(sys.argv) != 3:
    sys.exit(__doc__)
client_id, client_secret = sys.argv[1], sys.argv[2]
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
            f'Google ha devuelto un error: {parametros.get("error")}'
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

print('\n✅ Autorizado. Añade estas líneas al .env del servidor (y no las compartas):\n')
print(f'GOOGLE_CLIENT_ID={client_id}')
print(f'GOOGLE_CLIENT_SECRET={client_secret}')
print(f'GOOGLE_REFRESH_TOKEN={datos["refresh_token"]}')
