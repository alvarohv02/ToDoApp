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
python deploy\autorizar_google.py TU_ID_DE_CLIENTE TU_SECRETO_DE_CLIENTE
```

Se abre el navegador: entra con tu cuenta, acepta el aviso de "app no verificada"
(*Configuración avanzada → Ir a Mi Notion*) y da permiso. El script imprime tres líneas `GOOGLE_...`.

### 3. Añadirlas al servidor [admin]

```bash
sudo nano /opt/notion/.env          # pega las tres líneas GOOGLE_... al final y guarda
sudo machinectl shell notion_bot@ /bin/bash -c 'export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock; cd /opt/notion && docker compose up -d --force-recreate'
```

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
