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
/project
 ├── index.html    # Main HTML (includes Vue via CDN)
 ├── style.css     # Styles
 └── app.js        # Vue logic + drag & drop + ⋮ menu
```

## Dependencies

* **Vue 3** via CDN (no build step):

```html
<script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
```

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
