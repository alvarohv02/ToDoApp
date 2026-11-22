# Instalación en el servidor (Ubuntu 24.04)

El bot corre con un usuario propio, `notion_bot`, sin sudo y con Docker en modo *rootless*:
su Docker es independiente del sistema y no tiene ningún privilegio de administrador.

Los comandos marcados **[admin]** se ejecutan con tu usuario normal (el que tiene sudo).
Los marcados **[notion_bot]** se ejecutan dentro de la sesión de `notion_bot`.

## 1. Instalar Docker y lo necesario para el modo rootless [admin]

```bash
sudo apt-get update
sudo apt-get install -y uidmap dbus-user-session systemd-container
curl -fsSL https://get.docker.com | sudo sh

# No usamos el Docker del sistema (el que corre como root): lo desactivamos
sudo systemctl disable --now docker.service docker.socket
sudo rm -f /var/run/docker.sock
```

Ubuntu 24.04 bloquea por defecto los *user namespaces* que usa el modo rootless.
Este perfil de AppArmor los permite solo para `rootlesskit`:

```bash
cat <<'EOF' | sudo tee /etc/apparmor.d/usr.bin.rootlesskit
abi <abi/4.0>,
include <tunables/global>

/usr/bin/rootlesskit flags=(unconfined) {
  userns,

  include if exists <local/usr.bin.rootlesskit>
}
EOF
sudo systemctl restart apparmor.service
```

## 2. Crear el usuario `notion_bot` [admin]

```bash
sudo useradd --create-home --shell /bin/bash notion_bot
sudo passwd -l notion_bot                  # sin contraseña: no se puede entrar por SSH ni con login
grep notion_bot /etc/subuid /etc/subgid    # deben salir 2 líneas (rangos de uid para los contenedores)
sudo loginctl enable-linger notion_bot     # su Docker arranca al encender el servidor, sin iniciar sesión
```

Si el `grep` no muestra nada, añade los rangos a mano:

```bash
echo "notion_bot:231072:65536" | sudo tee -a /etc/subuid /etc/subgid
```

## 3. Activar el Docker de `notion_bot` [notion_bot]

Entra en su sesión (usa `machinectl`, no `sudo su`: hace falta una sesión de systemd completa):

```bash
sudo machinectl shell notion_bot@
```

Ya dentro, como `notion_bot`:

```bash
dockerd-rootless-setuptool.sh install
echo 'export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock' >> ~/.bashrc
source ~/.bashrc
systemctl --user enable docker
docker run --rm hello-world                # debe imprimir "Hello from Docker!"
exit
```

## 4. Copiar el proyecto

Primero, **para el bot que esté corriendo en el PC** (solo puede haber uno leyendo Telegram).
En PowerShell, en el PC:

```powershell
cd C:\Users\alvar\Desktop\vs\Proy_Notion
docker compose down
scp -r C:\Users\alvar\Desktop\vs\Proy_Notion TU_USUARIO@IP_DEL_SERVIDOR:/tmp/notion
```

En el servidor [admin]:

```bash
sudo mv /tmp/notion /opt/notion
sudo rm -rf /opt/notion/.git /opt/notion/.vscode /opt/notion/web/__pycache__ /opt/notion/web/data
sudo chown -R notion_bot:notion_bot /opt/notion
sudo chmod 700 /opt/notion
sudo chmod 600 /opt/notion/.env            # el .env tiene los tokens: solo notion_bot puede leerlo
```

## 5. Arrancar el bot [notion_bot]

```bash
sudo machinectl shell notion_bot@
cd /opt/notion
docker compose build
# Da permiso de escritura sobre data/ al usuario del contenedor
docker compose run --rm --no-deps --user 0 --entrypoint chown notion -R 1000:1000 /app/web/data
docker compose up -d
docker compose ps                          # debe salir "Up ... (healthy)" al cabo de unos segundos
docker compose logs -f                     # Ctrl+C para salir
exit
```

Comprueba que funciona escribiendo `hola` al bot de Telegram.

## 6. Publicar el webhook de WhatsApp [admin]

```bash
sudo apt-get install -y nginx
sudo cp /opt/notion/deploy/nginx-notion.conf /etc/nginx/sites-available/notion
sudo ln -s /etc/nginx/sites-available/notion /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d bot.tudominio.es
curl "https://bot.tudominio.es/webhook/?hub.mode=subscribe&hub.verify_token=$(sudo grep -oP '^WHATSAPP_VERIFY_TOKEN=\K.*' /opt/notion/.env)&hub.challenge=funciona"
```

El último comando debe imprimir `funciona`. Después, en Meta: WhatsApp → Configuración → Webhook,
URL `https://bot.tudominio.es/webhook/`, el identificador de verificación de tu `.env`,
*Verificar y guardar* y suscríbete a `messages`.

## Uso diario [notion_bot]

Entra siempre con `sudo machinectl shell notion_bot@` y `cd /opt/notion`.

| Acción | Comando |
|---|---|
| Ver estado | `docker compose ps` |
| Ver logs | `docker compose logs -f` |
| Reiniciar tras cambiar el `.env` | `docker compose up -d --force-recreate` |
| Actualizar tras cambiar el código | `docker compose up -d --build` |
| Ver las copias de seguridad | `ls -lh data/copias` (se hacen solas cada noche, ver abajo) |

## Actualizar el código

Cuando cambie el código en el PC, copia solo `web/`, `deploy/`, el `Dockerfile`, `requirements.txt` y `docker-compose.yml` (el `.env` y `data/` del servidor no se tocan).
En PowerShell, en el PC:

```powershell
cd C:\Users\alvar\Desktop\vs\Proy_Notion
scp -r web deploy Dockerfile requirements.txt docker-compose.yml TU_USUARIO@IP_DEL_SERVIDOR:/tmp/notion-update
```

En el servidor [admin]:

```bash
sudo cp -r /tmp/notion-update/web/. /opt/notion/web/
sudo cp -r /tmp/notion-update/deploy/. /opt/notion/deploy/
sudo cp /tmp/notion-update/Dockerfile /tmp/notion-update/requirements.txt /tmp/notion-update/docker-compose.yml /opt/notion/
sudo rm -rf /tmp/notion-update /opt/notion/web/data /opt/notion/web/__pycache__
# Ojo: no hacer chown de toda /opt/notion, cambiaría el dueño de data/ y el contenedor no podría escribir
sudo chown -R notion_bot:notion_bot /opt/notion/web /opt/notion/deploy /opt/notion/Dockerfile /opt/notion/requirements.txt /opt/notion/docker-compose.yml
```

Y como `notion_bot` (`sudo machinectl shell notion_bot@`, y **después** de entrar, escribe los comandos):

```bash
cd /opt/notion && docker compose up -d --build
```

## Copias de seguridad

La app hace sola una copia de la base de datos cada día, a partir de las 4:00 (`COPIA_HORA`), en
`/opt/notion/data/copias/tareas-AAAA-MM-DD.sqlite3.gz`, y conserva las últimas 14 (`COPIA_DIAS`).
Si el servidor está apagado a esa hora, la copia se hace en cuanto vuelva a arrancar.

Esas copias están en el mismo disco que el original: sirven si se estropea la base de datos o si
borras algo sin querer, pero no si se rompe el disco. Para tener otra copia fuera del servidor, pon
`COPIA_TELEGRAM=true` en el `.env` y el bot te enviará el archivo cada noche por Telegram (en silencio).

### Restaurar una copia [notion_bot]

Cambia la fecha por la de la copia que quieras. Lo que haya en la base de datos ahora se guarda antes
en `data/tareas-antes-de-restaurar.sqlite3`, por si acaso:

```bash
cd /opt/notion && docker compose stop notion
docker compose run --rm --no-deps --entrypoint sh notion -c 'cp /app/web/data/tareas.sqlite3 /app/web/data/tareas-antes-de-restaurar.sqlite3 && gunzip -c /app/web/data/copias/tareas-2026-11-01.sqlite3.gz > /app/web/data/tareas.sqlite3'
docker compose up -d
```

Con Google Calendar activado, revisa después el calendario: lo que cambiaste en Google desde el día de la copia
se vuelve a traer, pero lo que hiciste en la web o el bot desde entonces se ha perdido.

### Bajar una copia al PC

En el servidor [admin]: `sudo cp /opt/notion/data/copias/tareas-2026-11-01.sqlite3.gz /tmp/ && sudo chmod a+r /tmp/tareas-2026-11-01.sqlite3.gz`
y en el PC: `scp TU_USUARIO@IP_DEL_SERVIDOR:/tmp/tareas-2026-11-01.sqlite3.gz .`

## Ver la web desde Tailscale en http://notion.tudominio.es

La web solo se abre con Tailscale conectado: el subdominio apunta a la IP de Tailscale del servidor,
que no es alcanzable desde Internet, y nginx además rechaza cualquier otra procedencia.

1. En IONOS → Dominios → tudominio.es → DNS → Añadir registro: tipo **A**, nombre de host
   `notion`, valor `IP_TAILSCALE_DEL_SERVIDOR` (la IP de Tailscale del servidor: `tailscale ip -4`).
2. En el servidor [admin]:

```bash
sudo cp /opt/notion/deploy/nginx-notion-web.conf /etc/nginx/sites-available/notion-web
sudo ln -s /etc/nginx/sites-available/notion-web /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo tailscale serve reset 2>/dev/null   # por si llegaste a activar tailscale serve
```

3. Con Tailscale conectado, abre `http://notion.tudominio.es`.

El navegador mostrará "No seguro" porque la URL es http://, pero el tráfico va cifrado dentro
del túnel de Tailscale. El certificado de Let's Encrypt no se puede sacar como el del webhook,
porque Let's Encrypt no llega a una IP de Tailscale.

## Usuarios e inicio de sesión [notion_bot]

La web pide usuario y contraseña. Las contraseñas se guardan solo como hash (scrypt con sal).
Cada usuario tiene sus **tareas**, su **calendario** y sus **recordatorios**, que nadie más ve; el
**correo**, Google Calendar y el estado del bot solo los ve el administrador (el primer usuario que
se crea). Lo que había antes de crear usuarios pasa a ser del administrador.

El administrador se crea desde la terminal. Los demás se **registran desde la web** (enlace
*Regístrate* en la página de inicio de sesión, o `/registro`): ponen su nombre, usuario, contraseña
y, si quieren, su WhatsApp y su id de Telegram. La cuenta queda **pendiente** hasta que el
administrador la aprueba en su página *Cuenta* (le llega un aviso por el bot y un número rojo junto
a su nombre). Empiezan con todo vacío. Para desactivar el registro: `REGISTRO=no` en el `.env`.

Desde la terminal, dentro del contenedor (la contraseña no se ve al escribir):

```bash
docker exec -it notion-bot python usuarios.py crear     # el primero es el administrador
docker exec -it notion-bot python usuarios.py listar
docker exec -it notion-bot python usuarios.py aprobar USUARIO         # igual que el botón de la web
docker exec -it notion-bot python usuarios.py clave USUARIO           # contraseña nueva
docker exec -it notion-bot python usuarios.py chats USUARIO "34600333444,tg:987654321"
docker exec -it notion-bot python usuarios.py borrar USUARIO
```

**Chats del bot**: cada usuario tiene sus chats de WhatsApp y Telegram (los pone al registrarse o
después en *Cuenta*); lo que cree desde ellos es suyo y el resumen de buenos días le llega con lo
suyo. El bot contesta a los usuarios aprobados sin tocar el `.env`. El administrador sin chats
apuntados se queda con todos los del `.env` que no sean de otro usuario. Con WhatsApp Cloud API en
modo de pruebas, Meta solo deja escribir a los números añadidos como destinatarios de prueba.

**No volver a iniciar sesión**: al entrar, deja marcado *Mantener la sesión iniciada*. La cookie
de sesión dura `SESION_DIAS` días (90 por defecto) y se renueva con cada visita: mientras uses la
web al menos una vez en ese plazo, no te la vuelve a pedir. Desde *Cuenta* se cambia la contraseña
y se puede cerrar la sesión en todos los dispositivos.

La clave que firma las cookies se crea sola en `data/clave_sesiones` (o se toma de `SECRET_KEY` en
el `.env`). Si se borra o se cambia, todas las sesiones se cierran.

## Instalar la web como app en el móvil [admin]

La web es una *app instalable* (PWA): desde Safari o Chrome se añade a la pantalla de inicio y se
abre a pantalla completa, con su icono, como cualquier otra app. No pasa por la App Store ni hay
que pagar nada. Hace falta HTTPS, y como Let's Encrypt no llega a una IP de Tailscale, se usa el
certificado que Tailscale emite para el nombre de la máquina (`tailscale status` lo muestra,
tiene la forma `NOMBRE_TAILSCALE.ts.net`). Si ya tienes Nextcloud con ese certificado, el primer
comando solo lo renueva.

```bash
sudo mkdir -p /etc/nginx/ts-certs
sudo tailscale cert --cert-file /etc/nginx/ts-certs/nextcloud.crt --key-file /etc/nginx/ts-certs/nextcloud.key NOMBRE_TAILSCALE.ts.net
sudo cp /opt/notion/deploy/nginx-notion-app.conf /etc/nginx/sites-available/notion-app
sudo sed -i 's/NOMBRE_TAILSCALE/mi-servidor.tailXXXX/' /etc/nginx/sites-available/notion-app   # tu nombre, sin ".ts.net"
sudo ln -s /etc/nginx/sites-available/notion-app /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Comprueba que abre `https://NOMBRE_TAILSCALE.ts.net:8443` con Tailscale conectado (candado y sin avisos).

En el iPhone (iOS 16.4 o posterior): abre esa dirección en **Safari** (tiene que ser Safari, no
Chrome) → botón Compartir → **Añadir a pantalla de inicio** → Añadir. En Android, en Chrome:
menú ⋮ → **Instalar aplicación**.

La app necesita Tailscale conectado en el móvil (en el iPhone, Tailscale se queda activo como
VPN). Si no hay conexión, muestra un aviso y las últimas páginas que cargó.

## Limitar SSH a Tailscale y a la red de casa [admin]

Hazlo conectado por Tailscale o desde casa, y **no cierres la sesión actual** hasta comprobar
que puedes abrir otra nueva.

```bash
sudo ufw allow in on tailscale0 to any port 22 proto tcp
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp
sudo ufw delete allow 22/tcp          # quita la regla que lo abría a todo Internet
sudo ufw status
```

Comprueba desde otra terminal: `ssh TU_USUARIO@IP_TAILSCALE_DEL_SERVIDOR` (IP de Tailscale del servidor).
Si el router tuviera redirigido el puerto 22, quita también esa redirección.

## Recordatorios por WhatsApp sin límite de 24 h (opcional)

WhatsApp solo deja al bot escribirte libremente en las 24 h siguientes a tu último mensaje.
Para que los recordatorios lleguen siempre, crea una plantilla en Meta:

1. business.facebook.com → WhatsApp Manager → **Plantillas de mensajes** → Crear plantilla.
2. Categoría **Utilidad**, nombre `recordatorio`, idioma **Español**.
3. Cuerpo: `⏰ Recordatorio: {{1}}` (el `{{1}}` es donde va el texto del recordatorio).
4. Cuando Meta la apruebe, añade al `.env`:
   `WHATSAPP_REMINDER_TEMPLATE=recordatorio` y `WHATSAPP_REMINDER_TEMPLATE_LANG=es`,
   y reinicia: `docker compose up -d --force-recreate`.

Fuera de la ventana de 24 h, cada plantilla de utilidad puede tener coste según las tarifas de Meta.
Por Telegram los recordatorios llegan siempre y gratis.

## Sincronizar con Google Calendar (opcional)

Los eventos y las tareas con fecha límite se copian a un calendario **"Mi Notion"** de tu cuenta de
Google, y lo que crees, cambies o borres en ese calendario (por ejemplo desde el iPhone) vuelve a la web
en 1-2 minutos. La app solo tiene permiso sobre los calendarios que crea ella, no sobre el resto.

### 1. Crear las credenciales en Google Cloud (una vez)

1. Entra en https://console.cloud.google.com con tu cuenta de Google y crea un proyecto ("Mi Notion").
2. *APIs y servicios → Biblioteca* → busca **Google Calendar API** → **Habilitar**.
3. *Pantalla de consentimiento de OAuth* (o *Google Auth Platform*): tipo **Externo**, nombre "Mi Notion",
   tu correo como soporte y contacto; añádete como usuario de prueba.
4. **Publica la app** (*Público* → *Publicar aplicación* → **En producción**). Si se queda en "Prueba",
   Google caduca el permiso cada 7 días y la sincronización se corta.
5. *Credenciales* → *Crear credenciales* → **ID de cliente de OAuth** → tipo **Aplicación de escritorio**.
   Apunta el **ID de cliente** y el **secreto de cliente**.

### 2. Dar permiso (una vez, en tu PC)

```powershell
cd C:\Users\alvar\Desktop\vs\Proy_Notion
python deploy\autorizar_google.py
```

Te pide el ID y el secreto de cliente (el secreto no se ve al escribirlo). Se abre el navegador:
entra con tu cuenta, acepta el aviso de "app no verificada" (*Configuración avanzada → Ir a Mi Notion*)
y da permiso. Las tres líneas `GOOGLE_...` quedan en el archivo `.env.google` de la carpeta del
proyecto (no se muestran en pantalla, y git lo ignora).

### 3. Añadirlas al servidor [admin]

```bash
sudo nano /opt/notion/.env          # pega las tres líneas de .env.google al final y guarda
sudo machinectl shell notion_bot@ /bin/bash -c 'export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock; cd /opt/notion && docker compose up -d --force-recreate'
```

Después borra `.env.google` de tu PC: ya no hace falta.

En 1-2 minutos aparecen en Google seis calendarios, uno por tipo y con el color de la web:
"Mi Notion · Clases", "· Cumpleaños", "· Reuniones", "· Exámenes", "· Otros" y "· Tareas"
(el iPhone colorea por calendario, no por evento). En el iPhone: app Calendario → *Calendarios* →
comprueba que están marcados; si alguno sale con otro color, se cambia con la (i) de su derecha.
Crear un evento en el iPhone dentro de uno de ellos le da esa categoría en la web (en "Tareas", crea una tarea),
y moverlo de calendario le cambia la categoría. En la página Calendario de la web verás
"Sincronizado con Google Calendar hace X min" y un botón para sincronizar al momento.

Detalles:
- Las tareas salen como "☑ nombre" (y "✅" cuando están terminadas). Si cambias su fecha en el móvil,
  cambia en la web; si la borras del calendario en el móvil, la tarea pierde la fecha (no se borra).
- Si cambias lo mismo en la web y en el móvil antes de que se sincronice, gana lo de la web.
- Las repeticiones que la app no admite (diarias, varios días por semana en un solo evento...) no se importan.

## Conectar el correo (opcional)

El panel de inicio, la página **Correos** y el bot («correos», «lee 2», «archiva 1»…) leen los no leídos
de la bandeja de entrada por IMAP. Cada cuenta necesita una **contraseña de aplicación**: una clave aparte
que solo sirve para esto y se puede revocar sin cambiar tu contraseña normal.

### Gmail

1. Activa la verificación en dos pasos, si no la tienes: https://myaccount.google.com/signinoptions/twosv
2. Crea una contraseña de aplicación en https://myaccount.google.com/apppasswords (nombre: «Mi Notion»).
   Google muestra 16 letras en grupos de 4: cópialas tal cual (los espacios dan igual).

### Universidad o trabajo

Necesitas el **servidor IMAP** (pregúntalo o búscalo en la ayuda del correo; suele ser `imap.<dominio>`)
y una contraseña que permita IMAP:
- Si el correo es de **Google** (Gmail con el dominio de la universidad): como Gmail, si el centro permite
  las contraseñas de aplicación. Servidor `imap.gmail.com`.
- Si es de **Microsoft 365 / Outlook**: Microsoft ya no deja entrar por IMAP con contraseña, así que esa
  cuenta no se puede conectar de esta forma.
- Si es un servidor propio: normalmente sirve tu usuario y contraseña de siempre.

### Añadirlas al servidor [admin]

En `/opt/notion/.env` (`sudo nano /opt/notion/.env`), por ejemplo con una cuenta de Gmail y una de la universidad:

```
NOMBRE_USUARIO=Álvaro
CORREO_CUENTAS=personal,uni
CORREO_PERSONAL_NOMBRE=Personal
CORREO_PERSONAL_USUARIO=tu.correo@gmail.com
CORREO_PERSONAL_CLAVE=abcd efgh ijkl mnop
CORREO_UNI_NOMBRE=Universidad
CORREO_UNI_USUARIO=tu.usuario@universidad.es
CORREO_UNI_CLAVE=...
CORREO_UNI_SERVIDOR=imap.universidad.es
```

Reinicia con `docker compose up -d --force-recreate` [notion_bot]. En el panel, la tarjeta «Herramientas
conectadas» muestra cada cuenta en verde o, si algo falla, el motivo (por ejemplo, contraseña incorrecta).

Qué hace con tus correos: cada `CORREO_MINUTOS` (5 por defecto) mira los no leídos de la bandeja de
entrada sin marcarlos como leídos; no guarda los correos en la base de datos ni los envía a ningún sitio.
Archivar mueve el correo al archivo («Todos» en Gmail) y borrar lo manda a la papelera.
