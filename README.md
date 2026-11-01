# ToDoApp

Aplicación web tipo Notion para gestionar tareas con vista de tablero, tabla y calendario.

## Asistente por WhatsApp y Telegram

Puedes gestionar las tareas escribiendo en lenguaje natural por WhatsApp o por Telegram
(los dos a la vez, sobre las mismas tareas). Todo el procesamiento se hace en tu servidor:
no se usa ningún servicio de IA externo. Lo único externo son las propias plataformas de
mensajería (WhatsApp Cloud API de Meta y Bot API de Telegram), que entregan los mensajes.

Escribe *ayuda* en el chat para ver ejemplos. Entiende, entre otras:

- Crear: "apunta llamar al dentista el viernes, urgente", "tengo que comprar pan mañana",
  "añade informe para el día 15 asignada a Marta"
- Consultar: "¿qué tengo hoy?", "qué tengo el viernes", "tareas esta semana",
  "tareas atrasadas / importantes / en curso", "¿qué tiene Marta?"
- Cambiar: "he terminado lo del dentista", "empiezo con el informe", "mueve la compra al lunes",
  "quita la fecha del informe", "cambia la importancia del informe a alta", "asigna el informe a Marta"
- Borrar: "borra la tarea del gimnasio" (siempre pide confirmación)
- Recordatorios: "recuérdame mañana a las 10 que tengo una reunión a las 11", "avísame en 20 minutos
  de sacar la ropa", "mis recordatorios", "cancela el recordatorio de la reunión". Llegan por el mismo
  canal (Telegram o WhatsApp) en el que se pidieron; en WhatsApp ver el límite de 24 h en `deploy/INSTALAR.md`.

Notas de voz: el bot las transcribe en el propio servidor con [Vosk](https://alphacephei.com/vosk/)
(modelo pequeño en español, sin servicios externos) y puede separar varias peticiones de un mismo
audio o mensaje: "apunta comprar pan y recuérdame a las cinco llamar a Marta y tengo examen el jueves".

Fechas en español: "mañana", "pasado mañana", "el viernes", "el lunes que viene", "25/10",
"3 de enero", "el día 15", "dentro de dos semanas", "el fin de semana"...
Las tareas se buscan por parecido ("lo del dentista" → "Llamar al dentista"); si hay varias, pregunta cuál.

### Cómo funciona

- `web/reglas.py` + `web/fechas.py`: motor de reglas que convierte la frase en una acción.
- `web/asistente.py`: ejecuta la acción, redacta la respuesta y gestiona las preguntas ("¿cuál?", "¿lo borro?").
- `web/whatsapp.py`: webhook de WhatsApp Cloud API (Meta llama a tu servidor: necesita dominio y HTTPS).
- `web/telegram_bot.py`: bot de Telegram por long polling (tu servidor pregunta a Telegram:
  no necesita dominio, HTTPS ni abrir puertos). Se arranca solo junto a la web si hay `TELEGRAM_TOKEN`.
  Comandos de menú: /hoy, /semana, /tareas, /atrasadas, /ayuda.
- `web/herramientas.py` y `web/db.py`: operaciones sobre las tareas en el SQLite que comparte con la web.
- `web/llm_local.py` (opcional, desactivado por defecto): pasa a un LLM local con [Ollama](https://ollama.com)
  lo que las reglas no entienden. Solo merece la pena con >= 8 GB de RAM y CPU con AVX2 o GPU
  (`OLLAMA_ENABLED=true` en el `.env`).

### Crear el bot de Telegram

1. En Telegram, abre @BotFather → `/newbot` → elige nombre y usuario del bot.
2. Copia el token en `TELEGRAM_TOKEN` y pon tu @usuario (y el de la otra persona) en `TELEGRAM_ALLOWED_USERS`.
3. Reinicia el servicio y escribe al bot. Si alguien no autorizado le escribe, el bot le dice su id
   para que puedas añadirlo.

### Despliegue en el servidor con Docker

Todo corre en un contenedor (`Dockerfile` + `docker-compose.yml`). La base de datos se guarda
fuera, en la carpeta `data/`, así que reconstruir o actualizar el contenedor no borra las tareas.
El contenedor se reinicia solo si falla o si se reinicia el servidor.

Se ejecuta con el usuario `notion_bot` y Docker en modo *rootless*: el usuario no tiene sudo
ni pertenece al grupo `docker` (que equivale a ser root), así que el contenedor no tiene ningún
privilegio sobre el servidor. Los pasos completos de instalación están en `deploy/INSTALAR.md`.

Uso diario:

| Acción | Comando |
|---|---|
| Ver estado | `docker compose ps` |
| Ver logs | `docker compose logs -f` |
| Reiniciar (p. ej. tras cambiar el `.env`) | `docker compose up -d --force-recreate` |
| Actualizar tras cambiar el código | `docker compose up -d --build` |
| Parar | `docker compose down` |
| Copia de seguridad | `cp data/tareas.sqlite3 ~/tareas-$(date +%F).sqlite3` |

El contenedor solo escucha en `127.0.0.1:5000`. Para que WhatsApp llegue desde Internet:

1. HTTPS público solo para `/webhook/`: `deploy/nginx-notion.conf` + certbot (instrucciones dentro).
   Necesitas el registro DNS `bot` → tu IP pública y los puertos 80/443 redirigidos en el router.
2. En developers.facebook.com → tu app → WhatsApp → Configuración: URL de callback
   `https://bot.tudominio.es/webhook/`, verify token = `WHATSAPP_VERIFY_TOKEN`, y suscríbete a `messages`.

Telegram no necesita nada de esto: funciona en cuanto el contenedor arranca.

La web no tiene login: no la publiques en Internet, solo el webhook.
El bot solo responde a los números de `WHATSAPP_ALLOWED_NUMBERS` y a los usuarios de `TELEGRAM_ALLOWED_USERS`.
Si solo usas Telegram, puedes saltarte nginx, certbot y la configuración del dominio.

# Task Planner

Simple planning app with **two views** (Kanban Board and Table) built with **HTML, CSS, and JavaScript** using **Vue 3 (CDN)**. It supports **drag & drop** between columns, **adding** modifying and **deleting** tasks.

## Features

* **Two views**:
  * **Board (Kanban)**: columns *Sin Empezar*, *En Curso*, *Terminado* with native **drag & drop**.
  * **Table**: full list with *Nombre, Importancia, Status, Fecha de Creación, Fecha Límite, Persona Encargada*.
* **Add tasks** via a collapsible form (toolbar **➕** button).
* **Delete tasks**:
  * On board: delete button on each card.
  * In table: **three‑dot menu (⋮)** → *Edit* / *Delete*.
* **Date picker**

## Project structure

```
/web
 ├── templates
      ├── base.html            (menú lateral / barra inferior en móvil, tema claro/oscuro)
      ├── index.html           (panel "Hoy")
      ├── tareas.html          (tablero y tabla, Vue 3)
      ├── calendar.html        (calendario, eventos y agenda con filtros)
      └── recordatorios.html
 ├── static
      ├── css/app.css          (una sola hoja de estilos con el sistema de diseño)
      ├── js/app.js
      └── img/
 ├── app.py, db.py, ...        (servidor Flask, bot y base de datos)
```

## Dependencies

* **Vue 3** via CDN (no build step):

```html
<script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
```

* Flask

```powershell
pip install Flask
```

## How to run

* Run ```app.py``` in file explorer (vscode may cause problems if run through it)
* Open localhost on any browser (most likely port 5000)

## Key functionality

* **Drag & Drop**: drag a task card and drop it into another column to change its `status`.
* **Form toggle (+)**: the **➕** button shows/hides the new task form.
* **⋮ Menu in the table**: clicking opens a small panel with *Edit* and *Delete*.

## Customization

* **Statuses**: edit the array `['Sin Empezar', 'En Curso', 'Terminado']` in `index.html` (board section) or map statuses in `app.js` and `.status.*` in `style_tareas.css`.
* **Colors**: tweak the variables at the top of `static/css/app.css` (light and dark theme).
* **Validation**: in `agregarTarea()` (addTask) enforce required fields or normalize date format.

## Credits

* UI inspired by **Notion/Trello**-style tools.
* Built with **Vue 3** (CDN) for simplicity.

