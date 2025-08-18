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
      ├── index.html
      ├── tareas.html
      └── calendar.html
 ├── static
      ├── css
           ├── style_index.css
           ├── style_tareas.css
           └── style_calendar.css
      ├── js
           └── app.js
      └── img
           ├── Logo_Notas.ico
           └── Logo_Notas.png 
 └── app.py
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
* **Colors**: tweak `.status.*` in `style.css`.
* **Validation**: in `agregarTarea()` (addTask) enforce required fields or normalize date format.

## Credits

* UI inspired by **Notion/Trello**-style tools.
* Built with **Vue 3** (CDN) for simplicity.

