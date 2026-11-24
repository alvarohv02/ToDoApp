// --- Avisos de carga ------------------------------------------------------------------------
// Mientras se piden datos al servidor y tardan, una barrita arriba (si van rápido, ni se ve).
// Al cambiar de sección, el «Cargando…» de la página (ver templates/_carga_cabecera.html).
(function vigilarCargas() {
  const raiz = document.documentElement;
  if (window.fetch) {
    const fetchOriginal = window.fetch.bind(window);
    let pendientes = 0;
    let espera = null;
    const actualizar = () => {
      if (pendientes > 0 && !espera && !raiz.classList.contains('cargando-datos')) {
        espera = setTimeout(() => {
          espera = null;
          raiz.classList.toggle('cargando-datos', pendientes > 0);
        }, 400);
      } else if (pendientes === 0) {
        clearTimeout(espera);
        espera = null;
        raiz.classList.remove('cargando-datos');
      }
    };
    window.fetch = (...argumentos) => {
      pendientes += 1;
      actualizar();
      return fetchOriginal(...argumentos).finally(() => {
        pendientes -= 1;
        actualizar();
      });
    };
  }

  let navegando = null;
  document.addEventListener('click', (evento) => {
    const enlace = evento.target.closest && evento.target.closest('a[href]');
    if (!enlace || evento.defaultPrevented || evento.button !== 0 || evento.metaKey || evento.ctrlKey
        || evento.shiftKey || evento.altKey || enlace.target === '_blank' || enlace.hasAttribute('download')) {
      return;
    }
    const destino = new URL(enlace.href, window.location.href);
    if (destino.origin !== window.location.origin || (destino.pathname === window.location.pathname
        && destino.search === window.location.search)) {
      return;  // otra web, o la misma página (un #ancla)
    }
    // Si la siguiente página tarda, se tapa esta con el «Cargando…»; si llega antes, ni se ve
    clearTimeout(navegando);
    navegando = setTimeout(() => raiz.classList.remove('pagina-lista'), 250);
  });
  window.addEventListener('pageshow', () => clearTimeout(navegando));
}());

const API_TASKS_URL = '/api/tareas';
// A quién se asignan las tareas si no se indica nadie: el nombre del usuario que ha iniciado sesión
const PERSONA_DEFECTO = (document.querySelector('meta[name="persona-defecto"]') || {}).content || 'Sin asignar';

function esPersonaDefecto(persona) {
  return !persona || persona === 'Sin asignar' || persona === PERSONA_DEFECTO;
}

// --- Grupos (familias) ---------------------------------------------------------------------
// Al crear una tarea, un evento o un recordatorio se puede compartir con un grupo del usuario.
let promesaGrupos = null;
let gruposConocidos = [];

function cargarGrupos() {
  promesaGrupos = promesaGrupos || fetch('/api/grupos')
    .then((respuesta) => (respuesta.ok ? respuesta.json() : []))
    .catch(() => [])
    .then((grupos) => {
      gruposConocidos = Array.isArray(grupos) ? grupos : [];
      return gruposConocidos;
    });
  return promesaGrupos;
}

function nombreGrupo(grupoId) {
  const grupo = gruposConocidos.find((g) => g.id === grupoId);
  return grupo ? grupo.nombre : 'Grupo';
}

// <select> "Compartir con": "Solo yo" y los grupos que comparten ese tipo de cosas.
// Si el elemento ya es de un grupo que no aparece (el grupo dejó de compartirlo), se mantiene.
function rellenarSelectorGrupo(select, tipo, grupoActual) {
  const grupos = gruposConocidos.filter((g) => g.comparte.includes(tipo));
  select.innerHTML = '';
  select.appendChild(new Option('Solo yo', ''));
  grupos.forEach((grupo) => select.appendChild(new Option(`👨‍👩‍👧 ${grupo.nombre}`, String(grupo.id))));
  if (grupoActual && !grupos.some((g) => g.id === grupoActual)) {
    select.appendChild(new Option(`👨‍👩‍👧 ${nombreGrupo(grupoActual)}`, String(grupoActual)));
  }
  select.value = grupoActual ? String(grupoActual) : '';
  return grupos.length > 0 || Boolean(grupoActual);
}

function etiquetaGrupo(grupoId) {
  const etiqueta = document.createElement('span');
  etiqueta.className = 'etiqueta-grupo';
  etiqueta.textContent = `👨‍👩‍👧 ${nombreGrupo(grupoId)}`;
  etiqueta.title = 'Compartido con el grupo';
  return etiqueta;
}

function obtenerIdTarea() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID();
  }

  return `tarea-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normalizarTarea(tarea) {
  return {
    id: tarea.id || obtenerIdTarea(),
    nombre: tarea.nombre || '',
    importancia: tarea.importancia || '',
    fecha_limite: tarea.fecha_limite || '',
    hora_limite: tarea.hora_limite || '',
    status: tarea.status || 'Sin Empezar',
    fecha: tarea.fecha || new Date().toLocaleDateString(),
    persona: tarea.persona || PERSONA_DEFECTO,
    grupo_id: tarea.grupo_id || null,
    carpeta_id: tarea.carpeta_id || null
  };
}

// La API responde con la tarea y, si su encargado es otro miembro del grupo, 'aviso':
// { nombre, avisado: true } o { nombre, avisado: false, motivo }. No se guarda con la tarea.
function tareaYAviso(datos) {
  const tarea = normalizarTarea(datos);
  Object.defineProperty(tarea, 'aviso', { value: datos.aviso || null, enumerable: false });
  return tarea;
}

async function cargarTareas() {
  try {
    const response = await fetch(API_TASKS_URL);
    if (!response.ok) {
      return [];
    }

    const tareas = await response.json();
    if (!Array.isArray(tareas)) {
      return [];
    }

    return tareas.map(normalizarTarea);
  } catch (error) {
    return [];
  }
}

async function crearTarea(nuevaTarea) {
  const response = await fetch(API_TASKS_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(nuevaTarea)
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || 'No se pudo crear la tarea');
  }

  return tareaYAviso(await response.json());
}

async function actualizarTarea(tarea) {
  const response = await fetch(`${API_TASKS_URL}/${tarea.id}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(tarea)
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || 'No se pudo actualizar la tarea');
  }

  return tareaYAviso(await response.json());
}

async function borrarTarea(tareaId) {
  const response = await fetch(`${API_TASKS_URL}/${tareaId}`, {
    method: 'DELETE'
  });

  if (!response.ok && response.status !== 204) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || 'No se pudo borrar la tarea');
  }
}

function formatearFecha(fechaStr) {
  if (!fechaStr) {
    return 'Sin fecha';
  }

  const [year, month, day] = fechaStr.split('-');
  return `${day}/${month}/${year}`;
}

function obtenerNombreMes(fecha) {
  return fecha.toLocaleDateString('es-ES', { month: 'long', year: 'numeric' });
}

// Etiqueta compacta de una línea: hora opcional + texto cortado con "…" (el detalle va en el tooltip)
function crearChip(clase, hora, texto, detalle) {
  const chip = document.createElement('div');
  chip.className = `calendar-chip ${clase}`;
  chip.title = detalle;

  if (hora) {
    const time = document.createElement('span');
    time.className = 'chip-time';
    time.textContent = hora;
    chip.appendChild(time);
  }

  const label = document.createElement('span');
  label.className = 'chip-label';
  label.textContent = texto;
  chip.appendChild(label);
  return chip;
}

function crearEtiquetaTarea(tarea) {
  const detalle = [`Tarea: ${tarea.nombre}`, `Importancia ${tarea.importancia.toLowerCase()}`,
    tarea.hora_limite && `Hasta las ${tarea.hora_limite}`, tarea.status, tarea.persona].filter(Boolean).join('\n');
  return crearChip(`calendar-task importance-${(tarea.importancia || '').toLowerCase()}`,
    tarea.hora_limite, tarea.nombre, detalle);
}

const API_EVENTS_URL = '/api/eventos';
const MAX_ETIQUETAS_DIA = 3;
const CLASE_CATEGORIA = { Clase: 'clase', Cumpleaños: 'cumpleanos', Reunión: 'reunion', Examen: 'examen', Otro: 'otro' };
const EMOJI_CATEGORIA = { Clase: '📚', Cumpleaños: '🎂', Reunión: '👥', Examen: '📝', Otro: '📌' };

function claveFecha(fecha) {
  return `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}-${String(fecha.getDate()).padStart(2, '0')}`;
}

function horarioEvento(evento) {
  if (evento.hora_inicio && evento.hora_fin) {
    return `${evento.hora_inicio}–${evento.hora_fin}`;
  }
  return evento.hora_inicio || 'Todo el día';
}

async function cargarEventos(desde, hasta) {
  try {
    const response = await fetch(`${API_EVENTS_URL}?desde=${desde}&hasta=${hasta}`);
    return response.ok ? await response.json() : [];
  } catch (error) {
    return [];
  }
}

// Las que pueden tener fecha de fin y partirse en "este y los siguientes" (los cumpleaños no)
const REPETICIONES_CON_FIN = ['diaria', 'semanal', 'mensual'];

function crearEtiquetaEvento(evento, alPulsar) {
  const repeticion = {
    diaria: 'Se repite cada día', semanal: 'Se repite cada semana', mensual: 'Se repite cada mes', anual: 'Se repite cada año',
  }[evento.repeticion];
  const detalle = [`${EMOJI_CATEGORIA[evento.categoria] || '📌'} ${evento.categoria}: ${evento.titulo}`, horarioEvento(evento), repeticion,
    evento.grupo_id ? `👨‍👩‍👧 Compartido con ${nombreGrupo(evento.grupo_id)}` : '', 'Pulsa para editar']
    .filter(Boolean).join('\n');
  const article = crearChip(`calendar-event categoria-${CLASE_CATEGORIA[evento.categoria] || 'otro'}`,
    evento.hora_inicio, evento.titulo, detalle);
  article.addEventListener('click', (clic) => {
    clic.stopPropagation();
    alPulsar(evento);
  });
  return article;
}

async function renderizarCalendario() {
  const calendarRoot = document.querySelector('#calendar-app');

  if (!calendarRoot) {
    return;
  }

  const state = {
    fechaVista: new Date(),
    tareas: [],
    eventos: []
  };

  const monthLabel = calendarRoot.querySelector('[data-calendar-month]');
  const taskCount = calendarRoot.querySelector('[data-calendar-count]');
  const grid = calendarRoot.querySelector('[data-calendar-grid]');
  const agenda = calendarRoot.querySelector('[data-calendar-agenda]');
  const previousButton = calendarRoot.querySelector('[data-calendar-prev]');
  const nextButton = calendarRoot.querySelector('[data-calendar-next]');
  const todayButton = calendarRoot.querySelector('[data-calendar-today]');

  const panel = calendarRoot.querySelector('[data-event-panel]');
  const form = calendarRoot.querySelector('[data-event-form]');
  const formTitle = calendarRoot.querySelector('[data-event-form-title]');
  const formError = calendarRoot.querySelector('[data-event-error]');
  const campoHasta = calendarRoot.querySelector('[data-event-hasta]');
  const deleteButton = calendarRoot.querySelector('[data-event-delete]');
  const bloqueAlcance = calendarRoot.querySelector('[data-event-alcance]');
  const textoSoloEste = calendarRoot.querySelector('[data-alcance-uno]');
  const opcionSiguientes = calendarRoot.querySelector('[data-alcance-siguientes]');
  const campoRepeticion = form.elements.repeticion.closest('.field');
  const camposHora = [...calendarRoot.querySelectorAll('[data-event-hora]')];
  const campoGrupo = calendarRoot.querySelector('[data-event-grupo]');
  let eventoEditando = null;
  // Día pulsado de un evento que se repite (null si no se repite o es nuevo)
  let ocurrencia = null;

  async function recargar() {
    const year = state.fechaVista.getFullYear();
    const month = state.fechaVista.getMonth();
    const [tareas, eventos] = await Promise.all([
      cargarTareas(),
      cargarEventos(claveFecha(new Date(year, month, 1)), claveFecha(new Date(year, month + 1, 0))),
      cargarGrupos()  // antes de pintar, para poner el nombre del grupo en lo compartido
    ]);
    state.tareas = tareas;
    state.eventos = eventos;
  }

  // --- Formulario de eventos ---

  function actualizarCampoHasta() {
    campoHasta.hidden = !REPETICIONES_CON_FIN.includes(form.elements.repeticion.value);
  }

  // "Todo el día" oculta las horas (en el móvil, un campo de hora no se puede dejar vacío fácilmente)
  function actualizarTodoDia() {
    camposHora.forEach((campo) => { campo.hidden = form.elements.todo_dia.checked; });
  }

  // En un evento que se repite: "solo este día", "este y los siguientes" o "toda la serie"
  function aplicarAlcance() {
    campoRepeticion.hidden = false;
    deleteButton.textContent = 'Borrar';
    if (!ocurrencia) {
      actualizarCampoHasta();
      return;
    }
    const alcance = form.elements.alcance.value;
    if (alcance === 'uno') {
      // Ese día se convierte en un evento suelto: no tiene sentido la repetición
      form.elements.fecha.value = ocurrencia;
      campoRepeticion.hidden = true;
      campoHasta.hidden = true;
      formTitle.textContent = `Editar solo el ${formatearFecha(ocurrencia)}`;
      deleteButton.textContent = 'Borrar solo este día';
      return;
    }
    form.elements.repeticion.value = eventoEditando.repeticion;
    form.elements.hasta.value = eventoEditando.hasta || '';
    if (alcance === 'siguientes') {
      form.elements.fecha.value = ocurrencia;
      formTitle.textContent = `Editar desde el ${formatearFecha(ocurrencia)} en adelante`;
      deleteButton.textContent = 'Borrar este y los siguientes';
    } else {
      form.elements.fecha.value = eventoEditando.fecha_inicio || eventoEditando.fecha;
      formTitle.textContent = 'Editar toda la serie';
      deleteButton.textContent = 'Borrar toda la serie';
    }
    actualizarCampoHasta();
  }

  function urlEvento() {
    const base = `${API_EVENTS_URL}/${eventoEditando.id}`;
    return ocurrencia ? `${base}?alcance=${form.elements.alcance.value}&fecha=${ocurrencia}` : base;
  }

  function abrirFormulario(evento) {
    eventoEditando = evento && evento.id ? evento : null;
    form.reset();
    formError.textContent = '';
    formTitle.textContent = eventoEditando ? 'Editar evento' : 'Nuevo evento';
    deleteButton.hidden = !eventoEditando;

    const datos = evento || {};
    ocurrencia = eventoEditando && eventoEditando.repeticion ? eventoEditando.fecha : null;
    bloqueAlcance.hidden = !ocurrencia;
    if (ocurrencia) {
      textoSoloEste.textContent = `Solo este día (${formatearFecha(ocurrencia)})`;
      opcionSiguientes.hidden = !REPETICIONES_CON_FIN.includes(eventoEditando.repeticion);
      form.elements.alcance.value = 'uno';
    }
    form.elements.titulo.value = datos.titulo || '';
    form.elements.categoria.value = datos.categoria || 'Otro';
    form.elements.fecha.value = datos.fecha_inicio || datos.fecha || claveFecha(new Date());
    form.elements.hora_inicio.value = datos.hora_inicio || '';
    form.elements.hora_fin.value = datos.hora_fin || '';
    form.elements.todo_dia.checked = Boolean(eventoEditando) && !datos.hora_inicio;
    actualizarTodoDia();
    form.elements.repeticion.value = datos.repeticion || '';
    form.elements.hasta.value = datos.hasta || '';
    campoGrupo.hidden = !rellenarSelectorGrupo(form.elements.grupo_id, 'eventos', datos.grupo_id || null);
    aplicarAlcance();

    panel.hidden = false;
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    form.elements.titulo.focus({ preventScroll: true });
  }

  function cerrarFormulario() {
    panel.hidden = true;
    eventoEditando = null;
  }

  async function enviarEvento(metodo, url, cuerpo) {
    const response = await fetch(url, {
      method: metodo,
      headers: { 'Content-Type': 'application/json' },
      body: cuerpo ? JSON.stringify(cuerpo) : undefined
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || 'No se pudo guardar el evento');
    }
  }

  form.elements.repeticion.addEventListener('change', actualizarCampoHasta);
  form.elements.todo_dia.addEventListener('change', actualizarTodoDia);
  // Un cumpleaños nuevo suele ser de todo el día
  form.elements.categoria.addEventListener('change', () => {
    if (!eventoEditando && form.elements.categoria.value === 'Cumpleaños' && !form.elements.hora_inicio.value) {
      form.elements.todo_dia.checked = true;
      actualizarTodoDia();
    }
  });
  bloqueAlcance.addEventListener('change', aplicarAlcance);
  calendarRoot.querySelector('[data-event-new]').addEventListener('click', () => abrirFormulario(null));
  calendarRoot.querySelector('[data-event-close]').addEventListener('click', cerrarFormulario);

  form.addEventListener('submit', async (envio) => {
    envio.preventDefault();
    const datos = Object.fromEntries(new FormData(form).entries());
    delete datos.todo_dia;
    if (campoGrupo.hidden) {
      delete datos.grupo_id;  // sin grupos que compartan el calendario: no se toca con quién se comparte
    }
    if (form.elements.todo_dia.checked) {
      datos.hora_inicio = '';
      datos.hora_fin = '';
    }
    try {
      if (eventoEditando) {
        await enviarEvento('PUT', urlEvento(), datos);
      } else {
        await enviarEvento('POST', API_EVENTS_URL, datos);
      }
      cerrarFormulario();
      await recargar();
      render();
    } catch (error) {
      formError.textContent = error.message;
    }
  });

  deleteButton.addEventListener('click', async () => {
    if (!eventoEditando) {
      return;
    }
    const alcance = ocurrencia ? form.elements.alcance.value : 'serie';
    const aviso = !ocurrencia ? ''
      : alcance === 'uno' ? ` solo el ${formatearFecha(ocurrencia)} (el resto de repeticiones se mantiene)`
        : alcance === 'siguientes' ? ` desde el ${formatearFecha(ocurrencia)} en adelante`
          : ' y todas sus repeticiones';
    if (!window.confirm(`¿Borrar "${eventoEditando.titulo}"${aviso}?`)) {
      return;
    }
    try {
      await enviarEvento('DELETE', urlEvento());
      cerrarFormulario();
      await recargar();
      render();
    } catch (error) {
      formError.textContent = error.message;
    }
  });

  // --- Calendario ---

  function render() {
    const year = state.fechaVista.getFullYear();
    const month = state.fechaVista.getMonth();
    const startOfMonth = new Date(year, month, 1);
    const endOfMonth = new Date(year, month + 1, 0);
    // getDay() cuenta desde el domingo (0); la semana española empieza en lunes
    const startOffset = (startOfMonth.getDay() + 6) % 7;
    const daysInMonth = endOfMonth.getDate();
    const calendarCells = [];
    const nombresDias = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
    const hoyClave = claveFecha(new Date());

    monthLabel.textContent = obtenerNombreMes(state.fechaVista);

    const tareasDelMes = state.tareas.filter((tarea) => {
      if (!tarea.fecha_limite) {
        return false;
      }

      const [taskYear, taskMonth] = tarea.fecha_limite.split('-');
      return Number(taskYear) === year && Number(taskMonth) === month + 1;
    });

    const nTareas = tareasDelMes.length;
    const nEventos = state.eventos.length;
    taskCount.textContent = `${nEventos} evento${nEventos === 1 ? '' : 's'} · ${nTareas} tarea${nTareas === 1 ? '' : 's'}`;

    nombresDias.forEach((dia) => {
      const header = document.createElement('div');
      header.className = 'calendar-weekday';
      header.textContent = dia;
      calendarCells.push(header);
    });

    for (let emptyCell = 0; emptyCell < startOffset; emptyCell += 1) {
      const filler = document.createElement('div');
      filler.className = 'calendar-day is-empty';
      calendarCells.push(filler);
    }

    for (let day = 1; day <= daysInMonth; day += 1) {
      const dateKey = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const tareasDelDia = state.tareas.filter((tarea) => tarea.fecha_limite === dateKey);
      const eventosDelDia = state.eventos.filter((evento) => evento.fecha === dateKey);
      const dayCell = document.createElement('article');
      dayCell.className = `calendar-day${dateKey === hoyClave ? ' is-today' : ''}`;
      dayCell.title = 'Pulsa para añadir un evento este día';
      dayCell.addEventListener('click', () => abrirFormulario({ fecha: dateKey }));

      const dayNumber = document.createElement('div');
      dayNumber.className = 'calendar-day-number';
      dayNumber.textContent = String(day);
      dayNumber.dataset.semana = nombresDias[(startOffset + day - 1) % 7];

      dayCell.appendChild(dayNumber);

      // Primero lo de todo el día (eventos y luego tareas sin hora); después lo que tiene hora, en orden
      const etiquetas = [
        ...eventosDelDia.map((evento) => ({
          orden: evento.hora_inicio ? `2 ${evento.hora_inicio}` : '0', el: crearEtiquetaEvento(evento, abrirFormulario)
        })),
        ...tareasDelDia.map((tarea) => ({
          orden: tarea.hora_limite ? `2 ${tarea.hora_limite}` : '1', el: crearEtiquetaTarea(tarea)
        }))
      ].sort((a, b) => a.orden.localeCompare(b.orden)).map((x) => x.el);
      etiquetas.forEach((etiqueta, indice) => {
        if (indice >= MAX_ETIQUETAS_DIA) {
          etiqueta.classList.add('is-extra');
        }
        dayCell.appendChild(etiqueta);
      });

      // Si no caben, "+N más" despliega el resto del día
      if (etiquetas.length > MAX_ETIQUETAS_DIA) {
        const ocultas = etiquetas.length - MAX_ETIQUETAS_DIA;
        const mas = document.createElement('button');
        mas.type = 'button';
        mas.className = 'calendar-more';
        mas.textContent = `+${ocultas} más`;
        mas.addEventListener('click', (clic) => {
          clic.stopPropagation();
          const abierto = dayCell.classList.toggle('is-expanded');
          mas.textContent = abierto ? 'Ver menos' : `+${ocultas} más`;
        });
        dayCell.appendChild(mas);
      }

      calendarCells.push(dayCell);
    }

    // Huecos tras el último día para completar la semana
    const huecosFinales = (7 - ((startOffset + daysInMonth) % 7)) % 7;
    for (let emptyCell = 0; emptyCell < huecosFinales; emptyCell += 1) {
      const filler = document.createElement('div');
      filler.className = 'calendar-day is-empty';
      calendarCells.push(filler);
    }

    grid.innerHTML = '';
    calendarCells.forEach((cell) => grid.appendChild(cell));

    renderAgenda();
  }

  // --- Agenda con filtros ---

  const TIPOS_AGENDA = [
    ['Clase', 'Clases'], ['Cumpleaños', 'Cumpleaños'], ['Reunión', 'Reuniones'],
    ['Examen', 'Exámenes'], ['Otro', 'Otros'], ['tarea', 'Tareas']
  ];
  const FILTROS_INICIALES = {
    texto: '', periodo: 'mes', desde: '', hasta: '', pasados: false, tipos: TIPOS_AGENDA.map(([tipo]) => tipo)
  };
  const CLAVE_FILTROS = 'agendaFiltros';

  const tituloAgenda = calendarRoot.querySelector('[data-agenda-titulo]');
  const filtroTexto = calendarRoot.querySelector('[data-filtro-texto]');
  const filtroPeriodo = calendarRoot.querySelector('[data-filtro-periodo]');
  const filtroDesde = calendarRoot.querySelector('[data-filtro-desde]');
  const filtroHasta = calendarRoot.querySelector('[data-filtro-hasta]');
  const bloqueRango = calendarRoot.querySelector('[data-filtro-rango]');
  const filtroPasados = calendarRoot.querySelector('[data-filtro-pasados]');
  const contenedorTipos = calendarRoot.querySelector('[data-filtro-tipos]');
  const resumenFiltros = calendarRoot.querySelector('[data-filtro-resumen]');

  // Los filtros se recuerdan en este navegador (salvo la búsqueda de texto)
  function cargarFiltros() {
    try {
      const guardados = JSON.parse(window.localStorage.getItem(CLAVE_FILTROS) || 'null');
      if (guardados && Array.isArray(guardados.tipos)) {
        return { ...FILTROS_INICIALES, ...guardados, texto: '' };
      }
    } catch (error) {
      // sin almacenamiento disponible: se usan los filtros por defecto
    }
    return { ...FILTROS_INICIALES, tipos: [...FILTROS_INICIALES.tipos] };
  }

  function guardarFiltros() {
    try {
      window.localStorage.setItem(CLAVE_FILTROS, JSON.stringify({ ...filtros, texto: '' }));
    } catch (error) {
      // no pasa nada si no se puede guardar
    }
  }

  let filtros = cargarFiltros();

  function sinTildes(texto) {
    return (texto || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  }

  function sumarDias(fecha, dias) {
    const resultado = new Date(fecha);
    resultado.setDate(resultado.getDate() + dias);
    return resultado;
  }

  function formatoCorto(clave) {
    const [, mes, dia] = clave.split('-');
    return `${dia}/${mes}`;
  }

  function rangoAgenda() {
    const hoy = new Date();
    hoy.setHours(0, 0, 0, 0);
    const year = state.fechaVista.getFullYear();
    const month = state.fechaVista.getMonth();

    switch (filtros.periodo) {
      case 'hoy':
        return { desde: claveFecha(hoy), hasta: claveFecha(hoy), titulo: 'Agenda de hoy' };
      case 'semana': {
        const lunes = sumarDias(hoy, -((hoy.getDay() + 6) % 7));
        return { desde: claveFecha(lunes), hasta: claveFecha(sumarDias(lunes, 6)), titulo: 'Agenda de esta semana' };
      }
      case '7':
        return { desde: claveFecha(hoy), hasta: claveFecha(sumarDias(hoy, 6)), titulo: 'Próximos 7 días' };
      case '30':
        return { desde: claveFecha(hoy), hasta: claveFecha(sumarDias(hoy, 29)), titulo: 'Próximos 30 días' };
      case 'personalizado': {
        const desde = filtros.desde || claveFecha(hoy);
        let hasta = filtros.hasta || claveFecha(sumarDias(new Date(`${desde}T00:00`), 30));
        if (hasta < desde) {
          hasta = desde;
        }
        return { desde, hasta, titulo: `Agenda del ${formatoCorto(desde)} al ${formatoCorto(hasta)}` };
      }
      default: {
        const nombreMes = obtenerNombreMes(state.fechaVista);
        return {
          desde: claveFecha(new Date(year, month, 1)),
          hasta: claveFecha(new Date(year, month + 1, 0)),
          titulo: `Agenda de ${nombreMes}`
        };
      }
    }
  }

  function sincronizarControles() {
    filtroTexto.value = filtros.texto;
    filtroPeriodo.value = filtros.periodo;
    filtroDesde.value = filtros.desde;
    filtroHasta.value = filtros.hasta;
    filtroPasados.checked = filtros.pasados;
    bloqueRango.hidden = filtros.periodo !== 'personalizado';
    contenedorTipos.querySelectorAll('button').forEach((boton) => {
      boton.setAttribute('aria-pressed', String(filtros.tipos.includes(boton.dataset.tipo)));
    });
  }

  function cambiarFiltros(cambios) {
    filtros = { ...filtros, ...cambios };
    guardarFiltros();
    sincronizarControles();
    renderAgenda();
  }

  TIPOS_AGENDA.forEach(([tipo, etiqueta]) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = `filtro-tipo ${tipo === 'tarea' ? 'tipo-tarea' : `categoria-${CLASE_CATEGORIA[tipo]}`}`;
    boton.dataset.tipo = tipo;
    boton.textContent = tipo === 'tarea' ? `☑ ${etiqueta}` : `${EMOJI_CATEGORIA[tipo]} ${etiqueta}`;
    boton.addEventListener('click', () => {
      const activos = filtros.tipos.includes(tipo)
        ? filtros.tipos.filter((t) => t !== tipo)
        : [...filtros.tipos, tipo];
      cambiarFiltros({ tipos: activos });
    });
    contenedorTipos.appendChild(boton);
  });

  filtroTexto.addEventListener('input', () => cambiarFiltros({ texto: filtroTexto.value }));
  filtroPeriodo.addEventListener('change', () => cambiarFiltros({ periodo: filtroPeriodo.value }));
  filtroDesde.addEventListener('change', () => cambiarFiltros({ desde: filtroDesde.value }));
  filtroHasta.addEventListener('change', () => cambiarFiltros({ hasta: filtroHasta.value }));
  filtroPasados.addEventListener('change', () => cambiarFiltros({ pasados: filtroPasados.checked }));
  calendarRoot.querySelector('[data-filtro-limpiar]').addEventListener('click', () =>
    cambiarFiltros({ ...FILTROS_INICIALES, tipos: [...FILTROS_INICIALES.tipos] }));
  sincronizarControles();

  let peticionAgenda = 0;

  async function renderAgenda() {
    const { desde, hasta, titulo } = rangoAgenda();
    tituloAgenda.textContent = titulo;

    // Si el periodo es el mes que se ve en el calendario, los eventos ya están cargados
    const year = state.fechaVista.getFullYear();
    const month = state.fechaVista.getMonth();
    let eventos = state.eventos;
    if (desde !== claveFecha(new Date(year, month, 1)) || hasta !== claveFecha(new Date(year, month + 1, 0))) {
      const numero = ++peticionAgenda;
      eventos = await cargarEventos(desde, hasta);
      if (numero !== peticionAgenda) {
        return;  // mientras tanto se cambiaron los filtros: ya hay otra petición más nueva
      }
    }

    // Un evento de hoy deja de salir al terminar (hora de fin, o de inicio si no tiene);
    // los de todo el día salen hasta que acaba el día
    const ahora = new Date();
    const hoyClave = claveFecha(ahora);
    const horaActual = `${String(ahora.getHours()).padStart(2, '0')}:${String(ahora.getMinutes()).padStart(2, '0')}`;
    const yaPaso = (fecha, hora) => fecha < hoyClave || (fecha === hoyClave && Boolean(hora) && hora <= horaActual);

    const busqueda = sinTildes(filtros.texto.trim());
    const coincide = (...campos) => !busqueda || campos.some((campo) => sinTildes(campo).includes(busqueda));

    const tareasRango = state.tareas.filter((tarea) =>
      tarea.fecha_limite && tarea.fecha_limite >= desde && tarea.fecha_limite <= hasta);
    const total = eventos.length + tareasRango.length;

    const eventosVisibles = eventos.filter((evento) =>
      filtros.tipos.includes(evento.categoria)
      && coincide(evento.titulo)
      && (filtros.pasados || !yaPaso(evento.fecha, evento.hora_fin || evento.hora_inicio)));
    // Las tareas vencidas sin terminar se quedan (marcadas como atrasadas) para que no se olviden
    const tareasVisibles = tareasRango.filter((tarea) =>
      filtros.tipos.includes('tarea')
      && coincide(tarea.nombre, tarea.persona)
      && (filtros.pasados || !yaPaso(tarea.fecha_limite, tarea.hora_limite) || tarea.status !== 'Terminado'));

    const elementos = [
      ...eventosVisibles.map((evento) => ({ fecha: evento.fecha, orden: evento.hora_inicio || '00:00', evento })),
      ...tareasVisibles.map((tarea) => ({ fecha: tarea.fecha_limite, orden: tarea.hora_limite || '99:99', tarea }))
    ].sort((a, b) => a.fecha.localeCompare(b.fecha) || a.orden.localeCompare(b.orden));

    resumenFiltros.textContent = `Mostrando ${elementos.length} de ${total}`;
    agenda.innerHTML = '';

    if (elementos.length === 0) {
      const emptyState = document.createElement('p');
      emptyState.className = 'calendar-empty-state';
      if (total > 0) {
        emptyState.textContent = 'Nada coincide con los filtros. Prueba a quitar alguno o pulsa "Limpiar filtros".';
      } else {
        emptyState.textContent = hasta < hoyClave ? 'Este periodo ya ha pasado.' : 'No hay nada en este periodo 🎉';
      }
      agenda.appendChild(emptyState);
      return;
    }

    elementos.forEach(({ evento, tarea }) => {
      const row = document.createElement('div');
      row.className = 'agenda-item';

      const info = document.createElement('div');
      info.className = 'agenda-item-info';

      const name = document.createElement('strong');
      const meta = document.createElement('span');
      const chip = document.createElement('span');

      if (evento) {
        row.classList.add('is-clickable');
        row.addEventListener('click', () => abrirFormulario(evento));
        name.textContent = `${EMOJI_CATEGORIA[evento.categoria] || '📌'} ${evento.titulo}`;
        meta.textContent = `${formatearFecha(evento.fecha)} · ${horarioEvento(evento)}`;
        if (evento.grupo_id) {
          meta.append(' ', etiquetaGrupo(evento.grupo_id));
        }
        chip.className = `agenda-status categoria-chip categoria-${CLASE_CATEGORIA[evento.categoria] || 'otro'}`;
        chip.textContent = evento.categoria;
      } else {
        name.textContent = tarea.nombre;
        meta.textContent = [formatearFecha(tarea.fecha_limite), tarea.hora_limite, tarea.persona].filter(Boolean).join(' · ');
        if (yaPaso(tarea.fecha_limite, tarea.hora_limite) && tarea.status !== 'Terminado') {
          chip.className = 'agenda-status status-atrasada';
          chip.textContent = 'Atrasada';
        } else {
          chip.className = `agenda-status status-${tarea.status.toLowerCase().replace(/\s+/g, '-')}`;
          chip.textContent = tarea.status;
        }
      }

      info.append(name, meta);
      row.append(info, chip);
      agenda.appendChild(row);
    });
  }

  async function cambiarMes(fecha) {
    state.fechaVista = fecha;
    await recargar();
    render();
  }

  previousButton.addEventListener('click', () =>
    cambiarMes(new Date(state.fechaVista.getFullYear(), state.fechaVista.getMonth() - 1, 1)));
  nextButton.addEventListener('click', () =>
    cambiarMes(new Date(state.fechaVista.getFullYear(), state.fechaVista.getMonth() + 1, 1)));
  todayButton.addEventListener('click', () => cambiarMes(new Date()));

  // --- Estado de la sincronización con Google Calendar ---
  const bloqueGoogle = calendarRoot.querySelector('[data-google-sync]');
  const textoGoogle = calendarRoot.querySelector('[data-google-texto]');
  const botonGoogle = calendarRoot.querySelector('[data-google-boton]');

  function pintarEstadoGoogle(estado) {
    bloqueGoogle.hidden = !estado.configurado;
    bloqueGoogle.classList.toggle('is-error', Boolean(estado.error));
    if (estado.error) {
      textoGoogle.textContent = `Google Calendar: error (${estado.error.slice(0, 80)})`;
    } else if (estado.ultima) {
      const minutos = Math.round((Date.now() - new Date(estado.ultima)) / 60000);
      const cuando = minutos < 1 ? 'ahora mismo' : `hace ${minutos} min`;
      textoGoogle.textContent = `Sincronizado con Google Calendar ${cuando}`;
    } else {
      textoGoogle.textContent = 'Google Calendar: sincronizando…';
    }
  }

  async function consultarGoogle() {
    try {
      const respuesta = await fetch('/api/google/estado');
      if (respuesta.ok) {
        pintarEstadoGoogle(await respuesta.json());
      }
    } catch (error) {
      // sin conexión con el servidor: no se muestra nada
    }
  }

  botonGoogle.addEventListener('click', async () => {
    botonGoogle.disabled = true;
    textoGoogle.textContent = 'Sincronizando con Google Calendar…';
    try {
      const respuesta = await fetch('/api/google/sincronizar', { method: 'POST' });
      pintarEstadoGoogle(await respuesta.json().catch(() => ({ configurado: true, error: 'respuesta no válida' })));
      await recargar();
      render();
    } finally {
      botonGoogle.disabled = false;
    }
  });
  consultarGoogle();
  window.setInterval(consultarGoogle, 60000);

  window.addEventListener('focus', async () => {
    if (!panel.hidden) {
      return;  // no recargar mientras se está editando un evento
    }
    await recargar();
    render();
  });

  await recargar();
  render();
}

// --- Orden de la tabla de tareas ---

const CLAVE_ORDEN_TABLA = 'ordenTablaTareas';
const RANGO_IMPORTANCIA = { Alta: 0, Media: 1, Baja: 2 };
const RANGO_STATUS = { 'Sin Empezar': 0, 'En Curso': 1, Terminado: 2 };
const DESCRIPCION_ORDEN = {
  nombre: ['A → Z', 'Z → A'],
  importancia: ['de más a menos importante', 'de menos a más importante'],
  status: ['Sin empezar → Terminado', 'Terminado → Sin empezar'],
  fecha: ['las más antiguas primero', 'las más recientes primero'],
  fecha_limite: ['las que vencen antes primero', 'las que vencen más tarde primero'],
  persona: ['A → Z', 'Z → A']
};

function leerOrdenTabla() {
  try {
    const guardado = JSON.parse(window.localStorage.getItem(CLAVE_ORDEN_TABLA) || 'null');
    if (guardado && guardado.campo in DESCRIPCION_ORDEN && ['asc', 'desc'].includes(guardado.sentido)) {
      return guardado;
    }
  } catch (error) {
    // sin almacenamiento: orden por defecto
  }
  return { campo: '', sentido: 'asc' };
}

// --- Carpetas de tareas ("Universidad", "Casa"...) ------------------------------------------
// Filtro elegido: 'todas', 'sin' (sin carpeta) o el id de una carpeta. Se recuerda en este navegador.
const CLAVE_FILTRO_CARPETA = 'filtroCarpeta';

function leerFiltroCarpeta() {
  try {
    const guardado = window.localStorage.getItem(CLAVE_FILTRO_CARPETA);
    if (guardado === 'sin') {
      return 'sin';
    }
    if (/^\d+$/.test(guardado || '')) {
      return Number(guardado);
    }
  } catch (error) {
    // sin almacenamiento: todas
  }
  return 'todas';
}

function guardarFiltroCarpeta(filtro) {
  try {
    window.localStorage.setItem(CLAVE_FILTRO_CARPETA, String(filtro));
  } catch (error) {
    // no pasa nada si no se puede guardar
  }
}

async function peticionCarpeta(url, opciones = {}) {
  const response = await fetch(url, {
    ...opciones,
    headers: { 'Content-Type': 'application/json' }
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || 'No se pudo guardar la carpeta');
  }
  return response.status === 204 ? null : response.json();
}

function guardarOrdenTabla(orden) {
  try {
    window.localStorage.setItem(CLAVE_ORDEN_TABLA, JSON.stringify(orden));
  } catch (error) {
    // no pasa nada si no se puede guardar
  }
}

// "20/10/2026" -> "2026-10-20" para poder comparar fechas de creación
function fechaComparable(fecha) {
  const partes = (fecha || '').split(/[/.-]/);
  if (partes.length !== 3) {
    return '';
  }
  const [dia, mes, anio] = partes[0].length === 4 ? [partes[2], partes[1], partes[0]] : partes;
  return `${anio.padStart(4, '0')}-${mes.padStart(2, '0')}-${dia.padStart(2, '0')}`;
}

function clavesOrden(tarea, campo) {
  switch (campo) {
    case 'importancia':
      return [RANGO_IMPORTANCIA[tarea.importancia] ?? 9];
    case 'status':
      return [RANGO_STATUS[tarea.status] ?? 9];
    case 'fecha':
      return [fechaComparable(tarea.fecha)];
    case 'fecha_limite':
      return [tarea.fecha_limite, tarea.hora_limite || '99:99'];
    case 'persona':
      return [tarea.persona === 'Sin asignar' ? '' : tarea.persona];
    default:
      return [tarea.nombre];
  }
}

function compararTareas(a, b, campo, sentido) {
  const claveA = clavesOrden(a, campo);
  const claveB = clavesOrden(b, campo);
  // Lo que no tiene valor (sin fecha, sin asignar...) va siempre al final, se ordene como se ordene
  const vacioA = claveA[0] === '' || claveA[0] === undefined;
  const vacioB = claveB[0] === '' || claveB[0] === undefined;
  if (vacioA !== vacioB) {
    return vacioA ? 1 : -1;
  }
  let resultado = 0;
  for (let i = 0; i < claveA.length && resultado === 0; i += 1) {
    resultado = typeof claveA[i] === 'number'
      ? claveA[i] - claveB[i]
      : String(claveA[i]).localeCompare(String(claveB[i]), 'es', { sensitivity: 'base', numeric: true });
  }
  if (resultado === 0) {
    resultado = a.nombre.localeCompare(b.nombre, 'es', { sensitivity: 'base' });  // desempate estable
    return resultado;
  }
  return sentido === 'desc' ? -resultado : resultado;
}

function renderizarVistaTareas() {
  if (!window.Vue || !document.querySelector('#app')) {
    return;
  }

  const { createApp } = Vue;

  createApp({
    data() {
      return {
        vista: 'tablero',
        mostrarFormulario: false,
        tareaArrastrando: null,
        arrastrando: false,
        zonaActiva: null,
        menuAbierto: null,
        mostrarModal: false,
        tareaEditando: null,
        indiceEditando: null,
        nuevaTarea: { nombre: '', importancia: '', fecha_limite: '', hora_limite: '', persona: '', grupo_id: null, carpeta_id: null },
        grupos: [],
        carpetas: [],
        filtroCarpeta: leerFiltroCarpeta(),
        creandoCarpeta: false,
        nombreCarpetaNueva: '',
        grupoCarpetaNueva: null,
        tareas: [],
        cargando: true,
        errorCarga: '',
        avisoOk: '',
        orden: leerOrdenTabla(),
        personaDefecto: PERSONA_DEFECTO
      };
    },

    computed: {
      // Las tareas de la carpeta elegida (o todas)
      tareasVisibles() {
        return this.tareas.filter((tarea) => this.enFiltro(tarea, this.filtroCarpeta));
      },

      // Sin orden elegido, la tabla mantiene el del servidor (por fecha límite)
      tareasOrdenadas() {
        const { campo, sentido } = this.orden;
        if (!campo) {
          return this.tareasVisibles;
        }
        return [...this.tareasVisibles].sort((a, b) => compararTareas(a, b, campo, sentido));
      },

      carpetaElegida() {
        return this.carpetas.find((c) => c.id === this.filtroCarpeta) || null;
      }
    },

    watch: {
      filtroCarpeta(filtro) {
        guardarFiltroCarpeta(filtro);
        // Una tarea nueva va a la carpeta que se está viendo
        this.nuevaTarea.carpeta_id = typeof filtro === 'number' ? filtro : null;
        this.alCambiarCarpeta(this.nuevaTarea);
      }
    },

    async mounted() {
      const [grupos] = await Promise.all([cargarGrupos(), this.recargarTareas(), this.recargarCarpetas()]);
      this.grupos = grupos;
    },

    methods: {
      formatearFecha,
      esPersonaDefecto,
      nombreGrupo,

      enFiltro(tarea, filtro) {
        if (filtro === 'todas') {
          return true;
        }
        return filtro === 'sin' ? !tarea.carpeta_id : tarea.carpeta_id === filtro;
      },

      contarEn(filtro) {
        return this.tareas.filter((tarea) => this.enFiltro(tarea, filtro)).length;
      },

      carpetaPorId(carpetaId) {
        return this.carpetas.find((c) => c.id === carpetaId) || null;
      },

      esCarpetaDeGrupo(carpetaId) {
        const carpeta = this.carpetaPorId(carpetaId);
        return Boolean(carpeta && carpeta.grupo_id);
      },

      textoCarpeta(carpeta) {
        return carpeta.grupo_id ? `📁 ${carpeta.nombre} (👨‍👩‍👧 ${nombreGrupo(carpeta.grupo_id)})` : `📁 ${carpeta.nombre}`;
      },

      // Lo que va en una carpeta de grupo se comparte con ese grupo
      alCambiarCarpeta(tarea) {
        const carpeta = this.carpetaPorId(tarea.carpeta_id);
        if (carpeta && carpeta.grupo_id) {
          tarea.grupo_id = carpeta.grupo_id;
        }
      },

      // Grupos a los que se puede pasar la carpeta: el suyo si ya es de un grupo; si es personal, cualquiera
      gruposParaCarpeta(carpeta) {
        if (carpeta.grupo_id) {
          return [{ id: carpeta.grupo_id, nombre: nombreGrupo(carpeta.grupo_id) }];
        }
        return this.gruposParaTareas();
      },

      async cambiarParaQuien(evento) {
        const carpeta = this.carpetaElegida;
        const grupoId = evento.target.value ? Number(evento.target.value) : null;
        const tareasDentro = this.contarEn(carpeta.id);
        const aviso = grupoId
          ? `¿Compartir la carpeta «${carpeta.nombre}» con ${nombreGrupo(grupoId)}? Sus ${tareasDentro} tareas pasarán a verlas y cambiarlas todos los miembros del grupo.`
          : `¿Hacer «${carpeta.nombre}» solo tuya? Tus tareas de la carpeta dejarán de compartirse; las que añadieron otros miembros seguirán en el grupo, fuera de la carpeta.`;
        if (!window.confirm(aviso)) {
          evento.target.value = carpeta.grupo_id ? String(carpeta.grupo_id) : '';
          return;
        }
        try {
          const nueva = await peticionCarpeta(`/api/carpetas/${carpeta.id}`, { method: 'PUT', body: JSON.stringify({ grupo_id: grupoId }) });
          this.carpetas = this.carpetas.map((c) => (c.id === nueva.id ? nueva : c));
          this.errorCarga = '';
          if (this.nuevaTarea.carpeta_id === nueva.id) {
            this.nuevaTarea.grupo_id = nueva.grupo_id;  // la tarea nueva sigue a su carpeta
          }
          await this.recargarTareas();  // han cambiado varias tareas a la vez
        } catch (error) {
          this.errorCarga = error.message;
          evento.target.value = carpeta.grupo_id ? String(carpeta.grupo_id) : '';
        }
      },

      nombreCarpeta(carpetaId) {
        const carpeta = this.carpetas.find((c) => c.id === carpetaId);
        return carpeta ? carpeta.nombre : '';
      },

      async recargarCarpetas() {
        try {
          const carpetas = await peticionCarpeta('/api/carpetas');
          this.carpetas = Array.isArray(carpetas) ? carpetas : [];
        } catch (error) {
          this.carpetas = [];
        }
        // La carpeta que se estaba viendo ya no existe (borrada desde otro dispositivo)
        if (typeof this.filtroCarpeta === 'number' && !this.carpetaElegida) {
          this.filtroCarpeta = 'todas';
        }
        this.nuevaTarea.carpeta_id = this.carpetaElegida ? this.carpetaElegida.id : null;
        this.alCambiarCarpeta(this.nuevaTarea);
      },

      async crearCarpeta() {
        const nombre = this.nombreCarpetaNueva.trim();
        if (!nombre) {
          return;
        }
        try {
          const carpeta = await peticionCarpeta('/api/carpetas', {
            method: 'POST', body: JSON.stringify({ nombre, grupo_id: this.grupoCarpetaNueva })
          });
          this.carpetas = [...this.carpetas, carpeta].sort((a, b) => a.nombre.localeCompare(b.nombre, 'es'));
          this.nombreCarpetaNueva = '';
          this.grupoCarpetaNueva = null;
          this.creandoCarpeta = false;
          this.filtroCarpeta = carpeta.id;
          this.errorCarga = '';
        } catch (error) {
          this.errorCarga = error.message;
        }
      },

      async renombrarCarpeta() {
        const carpeta = this.carpetaElegida;
        const nombre = carpeta && window.prompt('Nuevo nombre de la carpeta', carpeta.nombre);
        if (!nombre || nombre.trim() === carpeta.nombre) {
          return;
        }
        try {
          const nueva = await peticionCarpeta(`/api/carpetas/${carpeta.id}`, { method: 'PUT', body: JSON.stringify({ nombre }) });
          this.carpetas = this.carpetas.map((c) => (c.id === nueva.id ? nueva : c))
            .sort((a, b) => a.nombre.localeCompare(b.nombre, 'es'));
          this.errorCarga = '';
        } catch (error) {
          this.errorCarga = error.message;
        }
      },

      async borrarCarpeta() {
        const carpeta = this.carpetaElegida;
        const aviso = carpeta && carpeta.grupo_id
          ? `¿Borrar la carpeta «${carpeta.nombre}» para todo el grupo? Sus tareas no se borran: siguen compartidas, sin carpeta.`
          : `¿Borrar la carpeta «${carpeta && carpeta.nombre}»? Sus tareas no se borran: se quedan sin carpeta.`;
        if (!carpeta || !window.confirm(aviso)) {
          return;
        }
        try {
          await peticionCarpeta(`/api/carpetas/${carpeta.id}`, { method: 'DELETE' });
          this.carpetas = this.carpetas.filter((c) => c.id !== carpeta.id);
          this.tareas = this.tareas.map((t) => (t.carpeta_id === carpeta.id ? { ...t, carpeta_id: null } : t));
          this.filtroCarpeta = 'todas';
          this.errorCarga = '';
        } catch (error) {
          this.errorCarga = error.message;
        }
      },

      // Grupos con los que se pueden compartir tareas (y el de la tarea, aunque ya no comparta tareas)
      gruposParaTareas(grupoActual = null) {
        const grupos = this.grupos.filter((g) => g.comparte.includes('tareas'));
        if (grupoActual && !grupos.some((g) => g.id === grupoActual)) {
          grupos.push({ id: grupoActual, nombre: nombreGrupo(grupoActual) });
        }
        return grupos;
      },

      // Cada clic en una cabecera: ascendente -> descendente -> sin ordenar
      ordenarPor(campo) {
        if (this.orden.campo !== campo) {
          this.orden = { campo, sentido: 'asc' };
        } else if (this.orden.sentido === 'asc') {
          this.orden = { campo, sentido: 'desc' };
        } else {
          this.orden = { campo: '', sentido: 'asc' };
        }
        guardarOrdenTabla(this.orden);
      },

      flechaOrden(campo) {
        if (this.orden.campo !== campo) {
          return '↕';
        }
        return this.orden.sentido === 'asc' ? '▲' : '▼';
      },

      ariaOrden(campo) {
        if (this.orden.campo !== campo) {
          return 'none';
        }
        return this.orden.sentido === 'asc' ? 'ascending' : 'descending';
      },

      tituloOrden(campo) {
        const siguiente = this.orden.campo !== campo ? 'asc' : (this.orden.sentido === 'asc' ? 'desc' : '');
        if (!siguiente) {
          return 'Quitar orden';
        }
        return `Ordenar: ${DESCRIPCION_ORDEN[campo][siguiente === 'asc' ? 0 : 1]}`;
      },

      // "👋 Se lo he dicho a Lucía por el bot" (o por qué no se ha podido), unos segundos
      avisarEncargado(tarea) {
        const aviso = tarea.aviso;
        if (!aviso) {
          return;
        }
        this.avisoOk = aviso.avisado
          ? `👋 Se lo he dicho a ${aviso.nombre} por el bot.`
          : `⚠️ No he podido avisar a ${aviso.nombre}: ${aviso.motivo}.`;
        clearTimeout(this.temporizadorAviso);
        this.temporizadorAviso = setTimeout(() => { this.avisoOk = ''; }, 6000);
      },

      async recargarTareas() {
        this.cargando = true;
        this.errorCarga = '';

        try {
          this.tareas = await cargarTareas();
        } catch (error) {
          this.errorCarga = 'No se pudieron cargar las tareas.';
        } finally {
          this.cargando = false;
        }
      },

      abrirModal(tarea, index) {
        this.tareaEditando = { ...tarea };
        this.indiceEditando = index;
        this.mostrarModal = true;
      },

      cerrarModal() {
        this.mostrarModal = false;
        this.tareaEditando = null;
        this.indiceEditando = null;
      },

      async guardarEdicion() {
        if (this.indiceEditando !== null && this.tareaEditando) {
          try {
            const tareaGuardada = await actualizarTarea(this.tareaEditando);
            const indice = this.tareas.findIndex((tarea) => tarea.id === tareaGuardada.id);

            if (indice !== -1) {
              this.tareas.splice(indice, 1, tareaGuardada);
              this.avisarEncargado(tareaGuardada);
            }
          } catch (error) {
            this.errorCarga = error.message;
          } finally {
            this.cerrarModal();
          }
        }
      },

      toggleMenu(index) {
        this.menuAbierto = this.menuAbierto === index ? null : index;
      },

      dragStart(tarea) {
        this.tareaArrastrando = tarea;
        // La barra de destinos se muestra un instante después: cambiar la página justo al empezar
        // a arrastrar hace que algunos navegadores cancelen el arrastre
        setTimeout(() => { this.arrastrando = this.tareaArrastrando === tarea; }, 0);
      },

      dragEnd() {
        this.tareaArrastrando = null;
        this.arrastrando = false;
        this.zonaActiva = null;
        document.querySelectorAll('.column').forEach((column) => column.classList.remove('highlight'));
      },

      dragOver(estado, event) {
        event.currentTarget.classList.add('highlight');
      },

      async drop(estado) {
        this.arrastrando = false;
        this.zonaActiva = null;
        if (this.tareaArrastrando && this.tareaArrastrando.status === estado) {
          this.tareaArrastrando = null;  // soltada en su misma columna: no hay nada que guardar
        } else if (this.tareaArrastrando) {
          try {
            const tareaActualizada = await actualizarTarea({
              ...this.tareaArrastrando,
              status: estado
            });
            const indice = this.tareas.findIndex((tarea) => tarea.id === tareaActualizada.id);

            if (indice !== -1) {
              this.tareas.splice(indice, 1, tareaActualizada);
            }
          } finally {
            this.tareaArrastrando = null;
          }
        }

        document.querySelectorAll('.column').forEach((column) => column.classList.remove('highlight'));
      },

      // En pantallas táctiles no se puede arrastrar: el botón ➜ pasa la tarea a la siguiente columna
      async avanzar(tarea) {
        const orden = ['Sin Empezar', 'En Curso', 'Terminado'];
        const siguiente = orden[(orden.indexOf(tarea.status) + 1) % orden.length];
        this.tareaArrastrando = tarea;
        await this.drop(siguiente);
      },

      async agregarTarea() {
        if (!this.nuevaTarea.nombre || !this.nuevaTarea.importancia) {
          return;
        }

        try {
          const tareaCreada = await crearTarea({
            nombre: this.nuevaTarea.nombre,
            importancia: this.nuevaTarea.importancia,
            fecha_limite: this.nuevaTarea.fecha_limite,
            hora_limite: this.nuevaTarea.fecha_limite ? this.nuevaTarea.hora_limite : '',
            status: 'Sin Empezar',
            fecha: new Date().toLocaleDateString(),
            persona: this.nuevaTarea.persona || PERSONA_DEFECTO,
            grupo_id: this.nuevaTarea.grupo_id,
            carpeta_id: this.nuevaTarea.carpeta_id
          });

          this.tareas.push(tareaCreada);
          this.avisarEncargado(tareaCreada);
          this.nuevaTarea = {
            nombre: '', importancia: '', fecha_limite: '', hora_limite: '', persona: '', grupo_id: null,
            carpeta_id: this.carpetaElegida ? this.carpetaElegida.id : null
          };
          this.alCambiarCarpeta(this.nuevaTarea);
          this.mostrarFormulario = false;
        } catch (error) {
          this.errorCarga = error.message;
        }
      },

      async eliminarTarea(tarea) {
        if (tarea) {
          await this.eliminarPorId(tarea.id);
        }
      },

      async eliminarPorId(tareaId) {
        try {
          await borrarTarea(tareaId);
          this.tareas = this.tareas.filter((tarea) => tarea.id !== tareaId);
        } catch (error) {
          this.errorCarga = error.message;
        }
      },

      async eliminarTareaTabla(tarea) {
        if (!tarea) {
          return;
        }

        await this.eliminarPorId(tarea.id);
        this.menuAbierto = null;
      }
    }
  }).mount('#app');
}

// --- Recordatorios ---------------------------------------------------------------

const API_REMINDERS_URL = '/api/recordatorios';

async function peticionRecordatorio(url, opciones = {}) {
  const response = await fetch(url, opciones);
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || 'No se pudo completar la operación');
  }
  return response.status === 204 ? null : response.json();
}

function formatearMomento(cuando) {
  const fecha = new Date(cuando);
  const dia = fecha.toLocaleDateString('es-ES', { weekday: 'short', day: '2-digit', month: '2-digit' });
  const hora = fecha.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  return `${dia} · ${hora}`;
}

function crearElemento(etiqueta, clase, texto) {
  const elemento = document.createElement(etiqueta);
  if (clase) {
    elemento.className = clase;
  }
  if (texto !== undefined) {
    elemento.textContent = texto;
  }
  return elemento;
}

// Etiqueta del canal de un recordatorio (y opciones para cambiarlo)
const EMOJI_CANAL = { WhatsApp: '💬', Telegram: '✈️' };

function opcionesCanal(canales, recordatorio) {
  const opciones = canales.map((c) => ({ valor: c.destino, texto: `${EMOJI_CANAL[c.canal] || ''} ${c.etiqueta}` }));
  if (recordatorio && !opciones.some((o) => o.valor === recordatorio.destino)) {
    // Un chat que ya no está en la configuración: se mantiene como opción para no cambiarlo sin querer
    opciones.unshift({ valor: recordatorio.destino, texto: `${EMOJI_CANAL[recordatorio.canal] || ''} ${recordatorio.canal}` });
  }
  return opciones;
}

function crearTarjetaRecordatorio(recordatorio, alCambiar, canales = []) {
  const tarjeta = crearElemento('article', `reminder-card is-${{ enviado: 'sent', error: 'error' }[recordatorio.estado] || 'pending'}`);

  const columnaTexto = crearElemento('div');
  const inputTexto = crearElemento('input');
  inputTexto.type = 'text';
  inputTexto.value = recordatorio.texto;
  inputTexto.setAttribute('aria-label', 'Texto del recordatorio');
  const meta = crearElemento('div', 'reminder-meta');
  const etiquetasEstado = { pendiente: 'Pendiente', enviado: 'Enviado', error: 'No se pudo enviar' };
  meta.append(crearElemento('span', `reminder-chip estado-${recordatorio.estado}`, etiquetasEstado[recordatorio.estado]));
  if (recordatorio.grupo_id) {
    meta.append(etiquetaGrupo(recordatorio.grupo_id));  // avisa a todos los miembros del grupo
  }
  columnaTexto.append(inputTexto, meta);

  const selectCanal = crearElemento('select', 'input reminder-canal');
  selectCanal.setAttribute('aria-label', 'Avisar por');
  opcionesCanal(canales, recordatorio).forEach((o) => {
    const opcion = crearElemento('option', '', o.texto);
    opcion.value = o.valor;
    selectCanal.append(opcion);
  });
  selectCanal.value = recordatorio.destino;

  const inputFecha = crearElemento('input');
  inputFecha.type = 'datetime-local';
  inputFecha.value = recordatorio.cuando;
  inputFecha.setAttribute('aria-label', 'Fecha y hora del aviso');

  const acciones = crearElemento('div', 'reminder-actions');
  const botonGuardar = crearElemento('button', 'reminder-save', 'Guardar');
  botonGuardar.type = 'button';
  botonGuardar.disabled = true;
  const botonCancelar = crearElemento('button', 'reminder-cancel', recordatorio.estado === 'pendiente' ? 'Cancelar' : 'Quitar');
  botonCancelar.type = 'button';
  acciones.append(botonGuardar, botonCancelar);

  const mensaje = crearElemento('p', 'reminder-feedback');
  tarjeta.append(columnaTexto, inputFecha, selectCanal, acciones, mensaje);

  const hayCambios = () => inputTexto.value.trim() !== recordatorio.texto
    || inputFecha.value !== recordatorio.cuando || selectCanal.value !== recordatorio.destino;
  [inputTexto, inputFecha, selectCanal].forEach((input) =>
    input.addEventListener(input === selectCanal ? 'change' : 'input', () => {
      botonGuardar.disabled = !hayCambios();
      mensaje.textContent = '';
    })
  );
  inputTexto.addEventListener('keydown', (evento) => {
    if (evento.key === 'Enter' && !botonGuardar.disabled) {
      botonGuardar.click();
    }
  });

  botonGuardar.addEventListener('click', async () => {
    botonGuardar.disabled = true;
    try {
      await peticionRecordatorio(`${API_REMINDERS_URL}/${recordatorio.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texto: inputTexto.value.trim(), cuando: inputFecha.value, destino: selectCanal.value })
      });
      await alCambiar();
    } catch (error) {
      mensaje.className = 'reminder-feedback';
      mensaje.textContent = error.message;
      botonGuardar.disabled = !hayCambios();
    }
  });

  botonCancelar.addEventListener('click', async () => {
    const pregunta = recordatorio.estado === 'pendiente' ? '¿Cancelar el recordatorio' : '¿Quitar de la lista';
    if (!window.confirm(`${pregunta} "${recordatorio.texto}"?`)) {
      return;
    }
    try {
      await peticionRecordatorio(`${API_REMINDERS_URL}/${recordatorio.id}`, { method: 'DELETE' });
      await alCambiar();
    } catch (error) {
      mensaje.className = 'reminder-feedback';
      mensaje.textContent = error.message;
    }
  });

  return tarjeta;
}

function dosCifras(n) {
  return String(n).padStart(2, '0');
}

// Fecha y hora de un atajo ("en 1 hora", "mañana a las 9"...)
function momentoAtajo(atajo) {
  const ahora = new Date();
  const momento = new Date(ahora);
  momento.setSeconds(0, 0);
  const a = (dias, hora) => {
    momento.setDate(momento.getDate() + dias);
    momento.setHours(hora, 0);
  };
  if (atajo === '30m') {
    momento.setMinutes(momento.getMinutes() + 30);
  } else if (atajo === '1h') {
    momento.setHours(momento.getHours() + 1);
  } else if (atajo === 'tarde') {
    a(ahora.getHours() >= 18 ? 1 : 0, 18);
  } else if (atajo === 'manana9') {
    a(1, 9);
  } else if (atajo === 'manana18') {
    a(1, 18);
  } else if (atajo === 'lunes9') {
    a(((8 - ahora.getDay()) % 7) || 7, 9);
  }
  return momento;
}

function iniciarFormularioRecordatorio(raiz, canales, alCrear) {
  const form = raiz.querySelector('[data-reminder-form]');
  if (!form) {
    return;
  }
  const contenedorCanales = form.querySelector('[data-reminder-canales]');
  const aviso = form.querySelector('[data-reminder-aviso]');
  const errorForm = form.querySelector('[data-reminder-error]');
  let guardado = null;
  try {
    guardado = window.localStorage.getItem('canalRecordatorio');
  } catch (error) {
    // sin almacenamiento: se usa el primero
  }

  if (!canales.length) {
    contenedorCanales.replaceChildren(crearElemento('p', 'card-text', 'No hay WhatsApp ni Telegram configurados en el servidor.'));
  } else {
    contenedorCanales.replaceChildren(...canales.map((canal, i) => {
      const opcion = crearElemento('label', 'canal-opcion');
      const radio = crearElemento('input');
      radio.type = 'radio';
      radio.name = 'destino';
      radio.value = canal.destino;
      radio.checked = guardado ? canal.destino === guardado : i === 0;
      opcion.append(radio, crearElemento('span', '', `${EMOJI_CANAL[canal.canal] || ''} ${canal.etiqueta}`));
      return opcion;
    }));
    if (!form.querySelector('input[name=destino]:checked')) {
      form.querySelector('input[name=destino]').checked = true;
    }
  }

  function ponerMomento(momento) {
    form.elements.dia.value = claveFecha(momento);
    form.elements.hora.value = `${dosCifras(momento.getHours())}:${dosCifras(momento.getMinutes())}`;
    revisarAviso();
  }

  // WhatsApp solo deja que el bot escriba si le has escrito en las 24 h anteriores
  function revisarAviso() {
    const elegido = form.querySelector('input[name=destino]:checked');
    const canal = canales.find((c) => elegido && c.destino === elegido.value);
    const cuando = form.elements.dia.value && form.elements.hora.value
      ? `${form.elements.dia.value}T${form.elements.hora.value}` : '';
    let texto = '';
    if (canal && canal.canal === 'WhatsApp' && !canal.plantilla && cuando) {
      if (!canal.ventana_hasta || cuando > canal.ventana_hasta) {
        const limite = canal.ventana_hasta
          ? ` Ahora mismo, tu último mensaje permite avisos hasta el ${formatearMomento(canal.ventana_hasta)}.`
          : ' Todavía no le has escrito nunca por WhatsApp.';
        texto = '⚠️ Por WhatsApp solo te llegará si le escribes algo al bot en las 24 h anteriores al aviso.'
          + `${limite} Si no quieres estar pendiente, elige Telegram.`;
      }
    }
    aviso.textContent = texto;
    aviso.hidden = !texto;
  }

  ponerMomento(momentoAtajo('1h'));
  form.querySelectorAll('[data-atajo]').forEach((boton) =>
    boton.addEventListener('click', () => ponerMomento(momentoAtajo(boton.dataset.atajo))));
  form.addEventListener('change', revisarAviso);
  form.addEventListener('input', () => { errorForm.textContent = ''; });

  form.addEventListener('submit', async (envio) => {
    envio.preventDefault();
    const elegido = form.querySelector('input[name=destino]:checked');
    const boton = form.querySelector('[type=submit]');
    boton.disabled = true;
    try {
      const creado = await peticionRecordatorio(API_REMINDERS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          texto: form.elements.texto.value.trim(),
          cuando: `${form.elements.dia.value}T${form.elements.hora.value}`,
          destino: elegido ? elegido.value : '',
          ...(form.elements.grupo_id.closest('[data-reminder-grupo]').hidden ? {} : { grupo_id: form.elements.grupo_id.value })
        })
      });
      try {
        window.localStorage.setItem('canalRecordatorio', creado.destino);
      } catch (error) {
        // sin almacenamiento: no se recuerda el canal
      }
      form.elements.texto.value = '';
      errorForm.className = 'event-form-error reminder-field-wide is-ok';
      errorForm.textContent = `✓ Te avisaré el ${formatearMomento(creado.cuando)} por ${creado.canal}.`;
      await alCrear();
    } catch (error) {
      errorForm.className = 'event-form-error reminder-field-wide';
      errorForm.textContent = error.message;
    } finally {
      boton.disabled = false;
    }
  });
}

async function renderizarRecordatorios() {
  const raiz = document.querySelector('#reminders-app');
  if (!raiz) {
    return;
  }

  const listaPendientes = raiz.querySelector('[data-reminders-pending-list]');
  const listaHechos = raiz.querySelector('[data-reminders-done-list]');
  const contador = raiz.querySelector('[data-reminders-pending]');
  const proximo = raiz.querySelector('[data-reminders-next]');
  const [canales] = await Promise.all([
    peticionRecordatorio(`${API_REMINDERS_URL}/canales`).catch(() => []),
    cargarGrupos()
  ]);
  const campoGrupo = raiz.querySelector('[data-reminder-grupo]');
  campoGrupo.hidden = !rellenarSelectorGrupo(campoGrupo.querySelector('select'), 'recordatorios', null);
  iniciarFormularioRecordatorio(raiz, canales, () => recargar());

  async function recargar() {
    let recordatorios = [];
    try {
      recordatorios = await peticionRecordatorio(API_REMINDERS_URL);
    } catch (error) {
      listaPendientes.replaceChildren(crearElemento('p', 'calendar-empty-state', 'No se pudieron cargar los recordatorios.'));
      return;
    }

    const pendientes = recordatorios.filter((r) => r.estado === 'pendiente');
    const hechos = recordatorios.filter((r) => r.estado !== 'pendiente');

    contador.textContent = pendientes.length;
    proximo.textContent = pendientes.length ? formatearMomento(pendientes[0].cuando) : 'Ninguno';

    listaPendientes.replaceChildren(
      ...(pendientes.length
        ? pendientes.map((r) => crearTarjetaRecordatorio(r, recargar, canales))
        : [crearElemento('p', 'calendar-empty-state', 'No hay recordatorios pendientes. Pídeselos al bot: "recuérdame mañana a las 10 que…"')])
    );
    listaHechos.replaceChildren(
      ...(hechos.length
        ? hechos.map((r) => crearTarjetaRecordatorio(r, recargar, canales))
        : [crearElemento('p', 'calendar-empty-state', 'Nada enviado en los últimos 30 días.')])
    );
  }

  await recargar();
}

// --- Tema claro / oscuro ---------------------------------------------------------

// Color de la barra de estado del móvil (app instalada): el de fondo del tema en uso
function sincronizarColorBarra() {
  const tema = document.documentElement.dataset.theme
    || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const color = tema === 'dark' ? '#0e1016' : '#f5f6fa';
  document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => meta.setAttribute('content', color));
}

function iniciarTema() {
  sincronizarColorBarra();
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', sincronizarColorBarra);
  const boton = document.querySelector('[data-theme-toggle]');
  if (!boton) {
    return;
  }
  boton.addEventListener('click', () => {
    const raiz = document.documentElement;
    const actual = raiz.dataset.theme
      || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const nuevo = actual === 'dark' ? 'light' : 'dark';
    raiz.dataset.theme = nuevo;
    sincronizarColorBarra();
    try {
      window.localStorage.setItem('tema', nuevo);
    } catch (error) {
      // sin almacenamiento: el cambio dura hasta recargar
    }
  });
}

// --- Inicio: el panel del día ---------------------------------------------------------------

const API_CORREOS_URL = '/api/correos';
const COLOR_CATEGORIA = {
  Clase: 'var(--info)', Cumpleaños: 'var(--pink)', Reunión: 'var(--teal)', Examen: 'var(--danger)', Otro: 'var(--gris)'
};

// True si esa fecha (y hora, si la hay) ya ha pasado
function pasoYa(fecha, hora) {
  const ahora = new Date();
  const hoy = claveFecha(ahora);
  const horaActual = `${String(ahora.getHours()).padStart(2, '0')}:${String(ahora.getMinutes()).padStart(2, '0')}`;
  return fecha < hoy || (fecha === hoy && Boolean(hora) && hora <= horaActual);
}

function crear(etiqueta, clase, texto) {
  const el = document.createElement(etiqueta);
  if (clase) {
    el.className = clase;
  }
  if (texto !== undefined) {
    el.textContent = texto;
  }
  return el;
}

function rellenarLista(lista, elementos, vacio) {
  if (!lista) {
    return;
  }
  lista.replaceChildren(...(elementos.length ? elementos : [crear('li', 'empty-state', vacio)]));
}

function diaCorto(clave, hoyClave) {
  if (clave === hoyClave) {
    return 'Hoy';
  }
  const fecha = new Date(`${clave}T00:00`);
  return fecha.toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric' });
}

function sumarDias(fecha, dias) {
  const nueva = new Date(fecha);
  nueva.setDate(nueva.getDate() + dias);
  return nueva;
}

// Etiqueta de vencimiento de una tarea: Atrasada, Hoy, Mañana o la fecha
function vencimiento(tarea, hoyClave) {
  if (!tarea.fecha_limite) {
    return { texto: 'Sin fecha', clase: 'vence-sin' };
  }
  if (tarea.fecha_limite < hoyClave) {
    return { texto: 'Atrasada', clase: 'vence-atrasada' };
  }
  if (tarea.fecha_limite === hoyClave) {
    return { texto: tarea.hora_limite ? `Hoy ${tarea.hora_limite}` : 'Hoy', clase: 'vence-hoy' };
  }
  if (tarea.fecha_limite === claveFecha(sumarDias(new Date(), 1))) {
    return { texto: 'Mañana', clase: 'vence-manana' };
  }
  return { texto: diaCorto(tarea.fecha_limite, hoyClave), clase: 'vence-luego' };
}

function ordenarPorFecha(a, b) {
  return (a.fecha_limite || '9999').localeCompare(b.fecha_limite || '9999')
    || (a.hora_limite || '99').localeCompare(b.hora_limite || '99');
}

// Fila con casilla: al marcarla, la tarea pasa a Terminado
function filaTarea(tarea, hoyClave, alTerminar) {
  const li = crear('li', `check-item imp-${(tarea.importancia || '').toLowerCase()}`);
  const etiqueta = crear('label', 'check-label');
  const casilla = crear('input');
  casilla.type = 'checkbox';
  const nombre = crear('span', 'check-texto', tarea.nombre);
  nombre.title = [tarea.nombre, `Importancia ${tarea.importancia.toLowerCase()}`, tarea.persona].filter(Boolean).join(' · ');
  etiqueta.append(casilla, nombre);
  const vence = vencimiento(tarea, hoyClave);
  li.append(etiqueta, crear('span', `vence ${vence.clase}`, vence.texto));

  casilla.addEventListener('change', async () => {
    li.classList.toggle('is-hecha', casilla.checked);
    try {
      await actualizarTarea({ ...tarea, status: casilla.checked ? 'Terminado' : tarea.status });
      if (casilla.checked) {
        setTimeout(alTerminar, 700);
      }
    } catch (error) {
      casilla.checked = false;
      li.classList.remove('is-hecha');
      nombre.title = error.message;
    }
  });
  return li;
}

function filaAgenda(cuando, texto, color, pasado) {
  const li = crear('li', `hoy-item${pasado ? ' is-pasado' : ''}`);
  li.style.setProperty('--c', color);
  li.append(crear('span', 'hoy-punto'), crear('span', 'hoy-hora', cuando), crear('span', 'hoy-texto', texto));
  li.lastChild.title = texto;
  return li;
}

function horaCorreo(fecha, hoyClave) {
  if (!fecha) {
    return '';
  }
  return fecha.slice(0, 10) === hoyClave ? fecha.slice(11, 16) : formatearFecha(fecha.slice(0, 10)).slice(0, 5);
}

// Color estable por cuenta de correo
function colorCuenta(id) {
  const colores = ['var(--accent)', 'var(--teal)', 'var(--pink)', 'var(--warning)', 'var(--info)', 'var(--success)'];
  let suma = 0;
  for (const letra of id) {
    suma += letra.charCodeAt(0);
  }
  return colores[suma % colores.length];
}

function filaCorreo(correo, hoyClave, variasCuentas) {
  const li = crear('li', 'correo-item');
  li.dataset.clave = `${correo.cuenta}/${correo.uid}`;
  const avatar = crear('span', 'correo-avatar', (correo.de || '?').trim().charAt(0).toUpperCase());
  avatar.style.setProperty('--c', colorCuenta(correo.cuenta));
  const cuerpo = crear('span', 'correo-cuerpo');
  const linea1 = crear('span', 'correo-de', correo.de || correo.direccion);
  const linea2 = crear('span', 'correo-asunto', correo.asunto);
  cuerpo.append(linea1, linea2);
  const lado = crear('span', 'correo-lado');
  lado.append(crear('span', 'correo-hora', horaCorreo(correo.fecha, hoyClave)));
  if (variasCuentas) {
    const insignia = crear('span', 'correo-cuenta', correo.cuenta_nombre);
    insignia.style.setProperty('--c', colorCuenta(correo.cuenta));
    lado.append(insignia);
  }
  li.title = `${correo.de} <${correo.direccion}>\n${correo.asunto}`;
  li.append(avatar, cuerpo, lado);
  return li;
}

async function pedirJson(url, opciones) {
  const response = await fetch(url, opciones);
  const datos = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(datos.error || 'No se pudo completar');
  }
  return datos;
}

function chipConexion(icono, nombre, detalle, estado) {
  const li = crear('li', `conexion conexion-${estado}`);
  const textos = crear('span', 'conexion-textos');
  textos.append(crear('span', 'conexion-nombre', nombre), crear('span', 'conexion-detalle', detalle));
  li.append(crear('span', 'conexion-icono', icono), textos,
    crear('span', 'conexion-estado', { ok: '●', error: '●', apagado: '○' }[estado]));
  li.title = detalle;
  return li;
}

async function renderizarInicio() {
  const raiz = document.querySelector('#inicio-app');
  if (!raiz) {
    return;
  }

  const ahora = new Date();
  const hoyClave = claveFecha(ahora);
  const hora = ahora.getHours();
  const saludo = hora < 6 ? 'Buenas noches' : hora < 13 ? 'Buenos días' : hora < 21 ? 'Buenas tardes' : 'Buenas noches';
  const nombre = raiz.dataset.nombre;
  raiz.querySelector('[data-inicio-saludo]').textContent = nombre ? `${saludo}, ${nombre}` : saludo;
  raiz.querySelector('.panel-sol').textContent = hora >= 6 && hora < 21 ? '☀️' : '🌙';
  const fechaLarga = ahora.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' });
  raiz.querySelector('[data-inicio-fecha]').textContent = fechaLarga.charAt(0).toUpperCase() + fechaLarga.slice(1);

  const [tareas, eventos, recordatorios, correos, conexiones] = await Promise.all([
    cargarTareas(),
    cargarEventos(hoyClave, hoyClave),
    fetch(API_REMINDERS_URL).then((r) => (r.ok ? r.json() : [])).catch(() => []),
    fetch(API_CORREOS_URL).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    fetch('/api/conexiones').then((r) => (r.ok ? r.json() : null)).catch(() => null)
  ]);

  const pendientes = tareas.filter((t) => t.status !== 'Terminado');
  const avisosHoy = recordatorios.filter((r) => r.estado === 'pendiente' && r.cuando.startsWith(hoyClave));
  const recargar = () => renderizarInicio();

  // Agenda de hoy: eventos, avisos y tareas con hora (lo de todo el día, arriba)
  const agenda = [
    ...eventos.map((e) => ({
      orden: e.hora_inicio || '', cuando: e.hora_inicio || 'Todo el día',
      texto: `${EMOJI_CATEGORIA[e.categoria] || '📌'} ${e.titulo}`,
      color: COLOR_CATEGORIA[e.categoria] || 'var(--gris)',
      pasado: pasoYa(e.fecha, e.hora_fin || e.hora_inicio)
    })),
    ...avisosHoy.map((r) => ({
      orden: r.cuando.slice(11, 16), cuando: r.cuando.slice(11, 16), texto: `⏰ ${r.texto}`,
      color: 'var(--accent)', pasado: pasoYa(hoyClave, r.cuando.slice(11, 16))
    })),
    ...pendientes.filter((t) => t.fecha_limite === hoyClave && t.hora_limite).map((t) => ({
      orden: t.hora_limite, cuando: t.hora_limite, texto: `✅ ${t.nombre}`, color: 'var(--warning)',
      pasado: pasoYa(hoyClave, t.hora_limite)
    }))
  ].sort((a, b) => a.orden.localeCompare(b.orden));
  rellenarLista(raiz.querySelector('[data-inicio-hoy]'),
    agenda.map((a) => filaAgenda(a.cuando, a.texto, a.color, a.pasado)), 'Nada programado hoy. ¡Día libre! 🎉');

  // Prioridades: importancia alta; Tareas pendientes: el resto, por fecha
  const prioridades = pendientes.filter((t) => t.importancia === 'Alta').sort(ordenarPorFecha);
  const resto = pendientes.filter((t) => t.importancia !== 'Alta').sort(ordenarPorFecha);
  rellenarLista(raiz.querySelector('[data-inicio-prioridades]'),
    prioridades.slice(0, 6).map((t) => filaTarea(t, hoyClave, recargar)), 'Ninguna tarea de importancia alta 👌');
  rellenarLista(raiz.querySelector('[data-inicio-pendientes]'),
    resto.slice(0, 6).map((t) => filaTarea(t, hoyClave, recargar)), 'No tienes más tareas pendientes 🎉');

  // Correos no leídos
  const listaCorreos = raiz.querySelector('[data-inicio-correos]');
  const cuentas = correos ? correos.cuentas : [];
  const totalCorreos = cuentas.reduce((suma, c) => suma + c.no_leidos, 0);
  raiz.querySelector('[data-inicio-correos-enlace]').textContent = totalCorreos ? `Ver todos (${totalCorreos}) →` : 'Ver todos →';
  if (!cuentas.length) {
    rellenarLista(listaCorreos, [], 'Aún no hay cuentas de correo conectadas (ver deploy/INSTALAR.md).');
  } else {
    const filas = correos.correos.slice(0, 5).map((c) => {
      const fila = filaCorreo(c, hoyClave, cuentas.length > 1);
      fila.addEventListener('click', () => { window.location.href = `/correos#${c.cuenta}/${c.uid}`; });
      return fila;
    });
    const errores = cuentas.filter((c) => c.error).map((c) => crear('li', 'empty-state correo-error', `⚠️ ${c.nombre}: ${c.error}`));
    rellenarLista(listaCorreos, [...errores, ...filas], 'Nada sin leer 📭');
  }

  // Herramientas conectadas
  if (conexiones) {
    const google = conexiones.google;
    const chips = [
      chipConexion('📅', 'Google Calendar',
        !google.configurado ? 'Sin conectar' : google.error ? `Error: ${google.error}`
          : google.ultima ? `Sincronizado ${google.ultima.slice(11, 16)}` : 'Conectado',
        !google.configurado ? 'apagado' : google.error ? 'error' : 'ok'),
      ...conexiones.correos.map((c) => chipConexion('📧', c.nombre,
        c.error ? c.error : `${c.usuario} · ${c.no_leidos} sin leer`, c.error ? 'error' : 'ok')),
      chipConexion('✈️', 'Telegram', conexiones.telegram ? 'Bot activo' : 'Sin conectar', conexiones.telegram ? 'ok' : 'apagado'),
      chipConexion('💬', 'WhatsApp', conexiones.whatsapp ? 'Bot activo' : 'Sin conectar', conexiones.whatsapp ? 'ok' : 'apagado')
    ];
    if (!conexiones.correos.length) {
      chips.splice(1, 0, chipConexion('📧', 'Correo', 'Sin conectar', 'apagado'));
    }
    rellenarLista(raiz.querySelector('[data-inicio-conexiones]'), chips, '');
  }

  // Resumen del día, hecho con reglas a partir de lo anterior
  const puntos = [];
  const eventosQueQuedan = eventos.filter((e) => !pasoYa(e.fecha, e.hora_fin || e.hora_inicio));
  const siguiente = eventosQueQuedan.find((e) => e.hora_inicio);
  if (eventos.length) {
    puntos.push(`Tienes ${eventos.length === 1 ? '1 evento' : `${eventos.length} eventos`} hoy`
      + (siguiente ? `; el siguiente, «${siguiente.titulo}» a las ${siguiente.hora_inicio}.` : '.'));
  }
  const vencenHoy = pendientes.filter((t) => t.fecha_limite === hoyClave);
  const atrasadas = pendientes.filter((t) => t.fecha_limite && t.fecha_limite < hoyClave);
  if (vencenHoy.length) {
    puntos.push(`${vencenHoy.length === 1 ? '1 tarea vence' : `${vencenHoy.length} tareas vencen`} hoy.`);
  }
  if (atrasadas.length) {
    puntos.push(`⚠️ ${atrasadas.length === 1 ? 'Tienes 1 tarea atrasada' : `Tienes ${atrasadas.length} tareas atrasadas`}.`);
  }
  if (prioridades.length) {
    puntos.push(`${prioridades.length === 1 ? '1 tarea' : `${prioridades.length} tareas`} de importancia alta por hacer.`);
  }
  const avisosQuedan = avisosHoy.filter((r) => !pasoYa(hoyClave, r.cuando.slice(11, 16)));
  if (avisosQuedan.length) {
    puntos.push(`Te quedan ${avisosQuedan.length === 1 ? '1 recordatorio' : `${avisosQuedan.length} recordatorios`} hoy`
      + ` (el próximo a las ${avisosQuedan[0].cuando.slice(11, 16)}).`);
  }
  if (totalCorreos) {
    const porCuenta = cuentas.filter((c) => c.no_leidos).map((c) => `${c.nombre} ${c.no_leidos}`).join(', ');
    puntos.push(`${totalCorreos === 1 ? '1 correo' : `${totalCorreos} correos`} sin leer${cuentas.length > 1 ? ` (${porCuenta})` : ''}.`);
  }
  if (!puntos.length) {
    puntos.push('Día tranquilo: no tienes nada pendiente para hoy 🎉');
  }
  rellenarLista(raiz.querySelector('[data-inicio-resumen]'), puntos.map((p) => crear('li', '', p)), '');
}

// --- Correos: todos los no leídos, abrir y ordenar ---------------------------------------

async function renderizarCorreos() {
  const raiz = document.querySelector('#correos-app');
  if (!raiz) {
    return;
  }
  const lista = raiz.querySelector('[data-correos-lista]');
  const chipsCuentas = raiz.querySelector('[data-correos-cuentas]');
  const detalle = raiz.querySelector('[data-correo-detalle]');
  const errorDetalle = raiz.querySelector('[data-correo-error]');
  const botonActualizar = raiz.querySelector('[data-correos-actualizar]');
  const hoyClave = claveFecha(new Date());
  let datos = { cuentas: [], correos: [] };
  let filtro = null;
  let abierto = null;

  function pintar() {
    const total = datos.cuentas.reduce((suma, c) => suma + c.no_leidos, 0);
    raiz.querySelector('[data-correos-subtitulo]').textContent = datos.cuentas.length
      ? `${total === 1 ? '1 correo sin leer' : `${total} correos sin leer`} en ${datos.cuentas.length === 1 ? '1 cuenta' : `${datos.cuentas.length} cuentas`}.`
      : 'Todavía no hay cuentas conectadas: añádelas en el .env del servidor (ver deploy/INSTALAR.md).';

    const todas = crear('button', `chip-filtro${filtro ? '' : ' is-activo'}`, 'Todas');
    todas.type = 'button';
    todas.addEventListener('click', () => { filtro = null; pintar(); });
    chipsCuentas.replaceChildren(todas, ...datos.cuentas.map((c) => {
      const chip = crear('button', `chip-filtro${filtro === c.id ? ' is-activo' : ''}${c.error ? ' is-error' : ''}`,
        c.error ? `⚠️ ${c.nombre}` : `${c.nombre} · ${c.no_leidos}`);
      chip.type = 'button';
      chip.style.setProperty('--c', colorCuenta(c.id));
      chip.title = c.error ? c.error : `${c.usuario}${c.actualizado ? ` · revisado a las ${c.actualizado.slice(11, 16)}` : ''}`;
      chip.addEventListener('click', () => { filtro = c.id; pintar(); });
      return chip;
    }));

    // Las cuentas que fallan, con el motivo a la vista (no solo al pasar el ratón)
    const errores = raiz.querySelector('[data-correos-errores]');
    const conError = datos.cuentas.filter((c) => c.error);
    errores.hidden = !conError.length;
    errores.replaceChildren(...conError.map((c) => crear('li', '', `⚠️ ${c.nombre} (${c.usuario}): ${c.error}`)));

    const visibles = datos.correos.filter((c) => !filtro || c.cuenta === filtro);
    rellenarLista(lista, visibles.map((c) => {
      const fila = filaCorreo(c, hoyClave, datos.cuentas.length > 1);
      fila.classList.toggle('is-abierto', abierto === `${c.cuenta}/${c.uid}`);
      fila.addEventListener('click', () => abrir(c.cuenta, c.uid));
      return fila;
    }), datos.cuentas.length ? 'Nada sin leer 📭' : 'Sin cuentas de correo.');
  }

  async function cargar(actualizar = false) {
    botonActualizar.disabled = true;
    try {
      datos = await pedirJson(actualizar ? `${API_CORREOS_URL}/actualizar` : API_CORREOS_URL,
        actualizar ? { method: 'POST' } : undefined);
    } catch (error) {
      rellenarLista(lista, [], error.message);
    } finally {
      botonActualizar.disabled = false;
    }
    pintar();
  }

  const avisoImagenes = raiz.querySelector('[data-correo-imagenes]');
  let correoAbierto = null;

  // El HTML del correo va en un marco aislado: sin scripts, sin acceso a esta página y sin pedir nada
  // a Internet salvo que se pulse «Mostrar imágenes» (las imágenes remotas delatan que lo has abierto)
  function pintarCuerpo(correo, conImagenes) {
    correoAbierto = correo;
    const contenedor = raiz.querySelector('[data-correo-cuerpo]');
    if (!correo.html) {
      contenedor.replaceChildren(textoConEnlaces(correo.texto || '(Este correo no tiene texto)'));
      avisoImagenes.hidden = true;
      return;
    }
    const politica = `default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:${conImagenes ? ' https: http:' : ''}`;
    const marco = document.createElement('iframe');
    marco.className = 'correo-html';
    marco.title = 'Contenido del correo';
    marco.setAttribute('sandbox', 'allow-popups allow-popups-to-escape-sandbox');
    marco.setAttribute('referrerpolicy', 'no-referrer');
    marco.srcdoc = '<!doctype html><html><head><meta charset="utf-8">'
      + `<meta http-equiv="Content-Security-Policy" content="${politica}">`
      + '<meta name="referrer" content="no-referrer"><base target="_blank">'
      + '<style>body{margin:0;padding:16px;background:#fff;color:#1b1f2e;font-family:system-ui,sans-serif;'
      + 'overflow-wrap:anywhere}img{max-width:100%;height:auto}table{max-width:100%}</style></head><body>'
      + correo.html + '</body></html>';
    contenedor.replaceChildren(marco);
    avisoImagenes.hidden = conImagenes || !correo.imagenes_remotas;
  }

  // Texto plano con los enlaces pulsables (creados como elementos, nunca como HTML)
  function textoConEnlaces(texto) {
    const bloque = crear('div', 'correo-texto');
    let ultimo = 0;
    for (const m of texto.matchAll(/https?:\/\/[^\s<>"')]+/g)) {
      bloque.append(texto.slice(ultimo, m.index));
      const enlace = crear('a', '', m[0].length > 60 ? `${m[0].slice(0, 57)}…` : m[0]);
      enlace.href = m[0];
      enlace.target = '_blank';
      enlace.rel = 'noopener noreferrer';
      bloque.append(enlace);
      ultimo = m.index + m[0].length;
    }
    bloque.append(texto.slice(ultimo));
    return bloque;
  }

  raiz.querySelector('[data-correo-mostrar-imagenes]').addEventListener('click', () => {
    if (correoAbierto) {
      pintarCuerpo(correoAbierto, true);
    }
  });

  async function abrir(cuenta, uid) {
    abierto = `${cuenta}/${uid}`;
    history.replaceState(null, '', `#${abierto}`);
    pintar();
    detalle.hidden = false;
    errorDetalle.textContent = '';
    raiz.querySelector('[data-correo-asunto]').textContent = 'Abriendo…';
    raiz.querySelector('[data-correo-de]').textContent = '';
    raiz.querySelector('[data-correo-meta]').textContent = '';
    raiz.querySelector('[data-correo-cuerpo]').replaceChildren();
    avisoImagenes.hidden = true;
    if (window.matchMedia('(max-width: 1080px)').matches) {
      detalle.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    try {
      const correo = await pedirJson(`${API_CORREOS_URL}/${cuenta}/${uid}`);
      if (abierto !== `${cuenta}/${uid}`) {
        return;
      }
      raiz.querySelector('[data-correo-asunto]').textContent = correo.asunto;
      raiz.querySelector('[data-correo-de]').textContent = `${correo.de} <${correo.direccion}>`;
      const meta = [correo.cuenta_nombre, correo.fecha && `${formatearFecha(correo.fecha.slice(0, 10))} ${correo.fecha.slice(11, 16)}`,
        correo.adjuntos.length && `📎 ${correo.adjuntos.join(', ')}`].filter(Boolean).join(' · ');
      raiz.querySelector('[data-correo-meta]').textContent = meta;
      pintarCuerpo(correo, false);
    } catch (error) {
      raiz.querySelector('[data-correo-asunto]').textContent = 'No se pudo abrir';
      errorDetalle.textContent = error.message;
    }
  }

  function cerrar() {
    abierto = null;
    detalle.hidden = true;
    history.replaceState(null, '', window.location.pathname);
    pintar();
  }

  raiz.querySelectorAll('[data-correo-accion]').forEach((boton) => {
    boton.addEventListener('click', async () => {
      if (!abierto) {
        return;
      }
      const que = boton.dataset.correoAccion;
      if (que === 'borrar' && !window.confirm('¿Mover este correo a la papelera?')) {
        return;
      }
      const [cuenta, uid] = abierto.split('/');
      boton.disabled = true;
      try {
        await pedirJson(`${API_CORREOS_URL}/${cuenta}/${uid}/${que}`, { method: 'POST' });
        datos.correos = datos.correos.filter((c) => !(c.cuenta === cuenta && c.uid === uid));
        datos.cuentas = datos.cuentas.map((c) => (c.id === cuenta ? { ...c, no_leidos: Math.max(0, c.no_leidos - 1) } : c));
        cerrar();
      } catch (error) {
        errorDetalle.textContent = error.message;
      } finally {
        boton.disabled = false;
      }
    });
  });
  raiz.querySelector('[data-correo-cerrar]').addEventListener('click', cerrar);
  botonActualizar.addEventListener('click', () => cargar(true));

  await cargar();
  const enlace = window.location.hash.slice(1).split('/');
  if (enlace.length === 2 && enlace[1]) {
    abrir(enlace[0], enlace[1]);
  }
}

// --- App instalable -----------------------------------------------------------------

// Si la sesión caduca con la página abierta, la API responde 401: se vuelve al login y, al entrar,
// a esta misma página
function vigilarSesion() {
  const fetchOriginal = window.fetch.bind(window);
  window.fetch = async (...argumentos) => {
    const respuesta = await fetchOriginal(...argumentos);
    if (respuesta.status === 401) {
      const datos = await respuesta.clone().json().catch(() => ({}));
      if (datos.login) {
        const aqui = window.location.pathname + window.location.search;
        window.location.href = '/login?siguiente=' + encodeURIComponent(aqui);
      }
    }
    return respuesta;
  };
}

// --- Tablas: fórmulas como en Excel -----------------------------------------------------------
// =A1+B2*2, =SUMA(B2:B10), =PROMEDIO(C2:C5), MIN, MAX, CONTAR, REDONDEAR(x; decimales).
// Se analizan a mano (nunca con eval). Una celda que no es fórmula se usa como número si lo parece
// ("3", "1,5", "2.000,50", "12 €", "30%").

const FUNCIONES_TABLA = {
  SUMA: (v) => v.reduce((a, b) => a + b, 0),
  SUM: (v) => v.reduce((a, b) => a + b, 0),
  PROMEDIO: (v) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : errorTabla('#DIV/0!')),
  MEDIA: (v) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : errorTabla('#DIV/0!')),
  AVERAGE: (v) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : errorTabla('#DIV/0!')),
  MIN: (v) => (v.length ? Math.min(...v) : 0),
  MAX: (v) => (v.length ? Math.max(...v) : 0),
  CONTAR: (v) => v.length,
  COUNT: (v) => v.length
};

function errorTabla(codigo) {
  const error = new Error(codigo);
  error.codigoTabla = codigo;
  throw error;
}

function letraColumna(indice) {
  return String.fromCharCode(65 + indice);
}

// "3", "-1,5", "2.000,50", "1,234.5", "12 €", "30%" -> número; si no parece un número, null
function numeroDeCelda(texto) {
  let limpio = String(texto || '').trim().replace(/[€$\s]/g, '');
  if (!limpio) {
    return null;
  }
  let porcentaje = false;
  if (limpio.endsWith('%')) {
    porcentaje = true;
    limpio = limpio.slice(0, -1);
  }
  if (/^[-+]?\d{1,3}(\.\d{3})+(,\d+)?$/.test(limpio)) {
    limpio = limpio.replace(/\./g, '').replace(',', '.');        // 2.000,50
  } else if (/^[-+]?\d{1,3}(,\d{3})+(\.\d+)?$/.test(limpio)) {
    limpio = limpio.replace(/,/g, '');                            // 1,234.5
  } else {
    limpio = limpio.replace(',', '.');                            // 1,5
  }
  if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(limpio)) {
    return null;
  }
  const numero = Number(limpio);
  return porcentaje ? numero / 100 : numero;
}

function trocearFormula(formula) {
  const piezas = [];
  const patron = /\s*(?:(\d+(?:\.\d+)?)|([A-Za-z]{1,2}\d{1,3}(?::[A-Za-z]{1,2}\d{1,3})?)|([A-Za-zÁÉÍÓÚáéíóú]+)\s*\(|([-+*/^();,]))/y;
  let posicion = 0;
  while (posicion < formula.length) {
    if (!formula.slice(posicion).trim()) {
      break;
    }
    patron.lastIndex = posicion;
    const m = patron.exec(formula);
    if (!m) {
      errorTabla('#ERROR');
    }
    if (m[1] !== undefined) piezas.push({ tipo: 'num', valor: Number(m[1]) });
    else if (m[2] !== undefined) piezas.push({ tipo: 'ref', valor: m[2].toUpperCase() });
    else if (m[3] !== undefined) piezas.push({ tipo: 'fun', valor: m[3].toUpperCase() });
    else piezas.push({ tipo: 'op', valor: m[4] });
    posicion = patron.lastIndex;
  }
  return piezas;
}

function posicionRef(ref) {
  const m = /^([A-Z]{1,2})(\d{1,3})$/.exec(ref);
  const columna = m[1].length === 1 ? m[1].charCodeAt(0) - 65 : 26 + (m[1].charCodeAt(0) - 65) * 26 + (m[1].charCodeAt(1) - 65);
  return { fila: Number(m[2]) - 1, columna };
}

// Calcula todas las celdas. Devuelve una matriz con, por celda, { valor (texto a enseñar), numero (o null), error }
function calcularTabla(filas) {
  const resultados = filas.map((fila) => fila.map(() => null));
  const enCurso = new Set();

  function valorCelda(f, c) {
    if (f < 0 || c < 0 || f >= filas.length || c >= (filas[f] || []).length) {
      errorTabla('#REF!');
    }
    return calcular(f, c);
  }

  function numeroDe(f, c, enRango) {
    const r = valorCelda(f, c);
    if (r.error) errorTabla(r.error);
    if (r.numero !== null) return r.numero;
    if (enRango || !String(r.valor).trim()) return enRango ? null : 0;  // en SUMA el texto se ignora
    return errorTabla('#VALOR!');
  }

  function evaluarFormula(texto) {
    const piezas = trocearFormula(texto);
    let i = 0;
    const ver = () => piezas[i];
    const tomar = (valor) => {
      const p = piezas[i];
      if (!p || (valor !== undefined && p.valor !== valor)) errorTabla('#ERROR');
      i += 1;
      return p;
    };

    function argumentos() {
      const valores = [];
      if (ver() && ver().valor === ')') {
        tomar(')');
        return valores;
      }
      for (;;) {
        const p = ver();
        if (p && p.tipo === 'ref' && p.valor.includes(':')) {
          tomar();
          const [desde, hasta] = p.valor.split(':').map(posicionRef);
          for (let f = Math.min(desde.fila, hasta.fila); f <= Math.max(desde.fila, hasta.fila); f += 1) {
            for (let c = Math.min(desde.columna, hasta.columna); c <= Math.max(desde.columna, hasta.columna); c += 1) {
              if (f < filas.length && c < (filas[f] || []).length) {
                const n = numeroDe(f, c, true);
                if (n !== null) valores.push(n);
              }
            }
          }
        } else if (p && p.tipo === 'ref') {
          tomar();
          const { fila, columna } = posicionRef(p.valor);
          const n = numeroDe(fila, columna, true);
          if (n !== null) valores.push(n);
        } else {
          valores.push(suma());
        }
        const sep = tomar();
        if (sep.valor === ')') return valores;
        if (sep.valor !== ';' && sep.valor !== ',') errorTabla('#ERROR');
      }
    }

    function primario() {
      const p = tomar();
      if (p.tipo === 'num') return p.valor;
      if (p.tipo === 'ref') {
        if (p.valor.includes(':')) errorTabla('#VALOR!');  // un rango suelto, fuera de una función
        const { fila, columna } = posicionRef(p.valor);
        return numeroDe(fila, columna, false);
      }
      if (p.tipo === 'fun') {
        if (p.valor === 'REDONDEAR' || p.valor === 'ROUND') {
          const [x, d = 0] = argumentos();
          const factor = 10 ** Math.round(d);
          return Math.round(x * factor) / factor;
        }
        const funcion = FUNCIONES_TABLA[p.valor];
        if (!funcion) errorTabla('#NOMBRE?');
        return funcion(argumentos());
      }
      if (p.valor === '(') {
        const v = suma();
        tomar(')');
        return v;
      }
      if (p.valor === '-') return -primario();
      if (p.valor === '+') return primario();
      return errorTabla('#ERROR');
    }

    function potencia() {
      let v = primario();
      while (ver() && ver().valor === '^') {
        tomar();
        v **= primario();
      }
      return v;
    }

    function producto() {
      let v = potencia();
      while (ver() && (ver().valor === '*' || ver().valor === '/')) {
        const op = tomar().valor;
        const d = potencia();
        if (op === '/' && d === 0) errorTabla('#DIV/0!');
        v = op === '*' ? v * d : v / d;
      }
      return v;
    }

    function suma() {
      let v = producto();
      while (ver() && (ver().valor === '+' || ver().valor === '-')) {
        v = tomar().valor === '+' ? v + producto() : v - producto();
      }
      return v;
    }

    const resultado = suma();
    if (i !== piezas.length) errorTabla('#ERROR');
    if (!Number.isFinite(resultado)) errorTabla('#NUM!');
    return resultado;
  }

  function calcular(f, c) {
    if (resultados[f][c]) return resultados[f][c];
    const clave = `${f},${c}`;
    if (enCurso.has(clave)) errorTabla('#CICLO!');
    const texto = filas[f][c] ?? '';
    let resultado;
    if (String(texto).trim().startsWith('=')) {
      enCurso.add(clave);
      try {
        const numero = evaluarFormula(String(texto).trim().slice(1));
        resultado = { valor: formatearNumeroTabla(numero), numero, error: '' };
      } catch (error) {
        if (!error.codigoTabla) throw error;
        resultado = { valor: error.codigoTabla, numero: null, error: error.codigoTabla };
      } finally {
        enCurso.delete(clave);
      }
    } else {
      resultado = { valor: texto, numero: numeroDeCelda(texto), error: '' };
    }
    resultados[f][c] = resultado;
    return resultado;
  }

  filas.forEach((fila, f) => fila.forEach((_, c) => calcular(f, c)));
  return resultados;
}

function formatearNumeroTabla(numero) {
  return numero.toLocaleString('es-ES', { maximumFractionDigits: 4, useGrouping: Math.abs(numero) >= 10000 });
}

// --- Notas ---------------------------------------------------------------------------------
// De texto libre o listas cuyos elementos se tachan al pulsarlos (como la lista de la compra).

const API_NOTAS = '/api/notas';
const MAX_FILAS_TABLA = 200;
const MAX_COLUMNAS_TABLA = 26;

// El contenido de una nota de tabla (JSON); si no se puede leer, una tabla vacía de 4×3
function leerTabla(contenido) {
  try {
    const datos = JSON.parse(contenido || '');
    if (Array.isArray(datos.filas) && datos.filas.length && datos.filas.every(Array.isArray)) {
      const columnas = Math.max(1, ...datos.filas.map((f) => f.length));
      return {
        filas: datos.filas.map((f) => [...f.map((c) => String(c ?? '')), ...Array(columnas - f.length).fill('')]),
        encabezado: datos.encabezado !== false
      };
    }
  } catch (error) {
    // contenido vacío o roto: tabla nueva
  }
  return { filas: Array.from({ length: 4 }, () => ['', '', '']), encabezado: true };
}

// Al insertar o quitar filas/columnas, las fórmulas siguen apuntando a las mismas celdas (como en Excel).
// eje: 'fila' o 'columna'; desde: índice donde se inserta/quita; delta: +1 o -1
function moverReferencias(filas, eje, desde, delta) {
  return filas.map((fila) => fila.map((celda) => {
    if (!String(celda).trim().startsWith('=')) {
      return celda;
    }
    return celda.replace(/\b([A-Za-z])(\d{1,3})\b/g, (ref, letra, numero) => {
      const columna = letra.toUpperCase().charCodeAt(0) - 65;
      const filaRef = Number(numero) - 1;
      const indice = eje === 'fila' ? filaRef : columna;
      if (delta < 0 && indice === desde) {
        return 'REF';  // apuntaba a lo que se ha quitado: la fórmula dará error
      }
      if (indice < desde) {
        return ref;
      }
      return eje === 'fila' ? `${letra}${filaRef + 1 + delta}` : `${letraColumna(columna + delta)}${numero}`;
    });
  }));
}

async function peticionNota(url, opciones = {}) {
  const response = await fetch(url, { ...opciones, headers: { 'Content-Type': 'application/json' } });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || 'No se pudo guardar la nota');
  }
  return response.status === 204 ? null : response.json();
}

// "2026-11-22 18:05:00" (UTC, de SQLite) -> "22 nov" o "hoy, 19:05"
function fechaNota(texto) {
  const fecha = new Date(`${String(texto || '').replace(' ', 'T')}Z`);
  if (Number.isNaN(fecha.getTime())) {
    return '';
  }
  const hoy = new Date();
  if (fecha.toDateString() === hoy.toDateString()) {
    return `hoy, ${fecha.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}`;
  }
  return fecha.toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: fecha.getFullYear() === hoy.getFullYear() ? undefined : 'numeric' });
}

function renderizarNotas() {
  const raiz = document.querySelector('[data-notas]');
  if (!raiz) {
    return;
  }

  const lista = raiz.querySelector('[data-notas-lista]');
  const vacio = raiz.querySelector('[data-notas-vacio]');
  const errorGeneral = raiz.querySelector('[data-notas-error]');
  const buscador = raiz.querySelector('[data-notas-buscar]');
  const modalTipo = document.querySelector('[data-nota-tipo-modal]');
  const editor = document.querySelector('[data-nota-editor]');
  const campoTitulo = editor.querySelector('[data-nota-titulo]');
  const campoTexto = editor.querySelector('[data-nota-texto]');
  const bloqueLista = editor.querySelector('[data-nota-lista-editor]');
  const bloqueTabla = editor.querySelector('[data-nota-tabla]');
  const rejilla = editor.querySelector('[data-tabla-rejilla]');
  const casillaEncabezado = editor.querySelector('[data-tabla-encabezado]');
  const formAnadir = editor.querySelector('[data-nota-anadir]');
  const campoElemento = editor.querySelector('[data-nota-elemento]');
  const listaPendientes = editor.querySelector('[data-nota-pendientes]');
  const bloqueHechos = editor.querySelector('[data-nota-hechos-bloque]');
  const tituloHechos = editor.querySelector('[data-nota-hechos-titulo]');
  const listaHechos = editor.querySelector('[data-nota-hechos]');
  const campoGrupo = editor.querySelector('[data-nota-grupo]');
  const selectGrupo = editor.querySelector('[data-nota-grupo-select]');
  const estado = editor.querySelector('[data-nota-estado]');
  const botonFijar = editor.querySelector('[data-nota-fijar]');

  let notas = [];
  let abierta = null;        // nota que se está editando
  let temporizador = null;   // guardado del texto mientras se escribe
  let guardando = Promise.resolve();
  let tabla = null;          // la tabla que se está editando: { filas, encabezado }
  let celdaActiva = { fila: 0, columna: 0 };

  function mostrarError(mensaje) {
    errorGeneral.textContent = mensaje || '';
    errorGeneral.hidden = !mensaje;
    estado.textContent = mensaje ? `⚠️ ${mensaje}` : estado.textContent;
  }

  function actualizarEnLista(nota) {
    const indice = notas.findIndex((n) => n.id === nota.id);
    if (indice === -1) {
      notas.unshift(nota);
    } else {
      notas[indice] = nota;
    }
    if (abierta && abierta.id === nota.id) {
      abierta = nota;
    }
  }

  function coincide(nota, busqueda) {
    if (!busqueda) {
      return true;
    }
    const contenido = nota.tipo === 'tabla' ? leerTabla(nota.contenido).filas.flat().join('\n') : nota.contenido;
    const texto = [nota.titulo, contenido, ...nota.elementos.map((e) => e.texto)].join('\n').toLocaleLowerCase('es');
    return texto.includes(busqueda);
  }

  function ordenar() {
    notas.sort((a, b) => (b.fijada - a.fijada) || String(b.actualizado_en).localeCompare(String(a.actualizado_en)) || b.id - a.id);
  }

  // --- Tarjetas ---------------------------------------------------------------------------
  function pintar() {
    ordenar();
    const busqueda = buscador.value.trim().toLocaleLowerCase('es');
    const visibles = notas.filter((nota) => coincide(nota, busqueda));
    lista.replaceChildren(...visibles.map(tarjeta));
    vacio.hidden = visibles.length > 0;
    vacio.textContent = notas.length
      ? 'Ninguna nota coincide con la búsqueda.'
      : 'Aún no tienes notas. Pulsa «+ Nueva nota» para crear una de texto o una lista.';
  }

  function tarjeta(nota) {
    const caja = document.createElement('article');
    caja.className = `nota-tarjeta es-${nota.tipo}`;
    caja.tabIndex = 0;
    caja.title = 'Pulsa para abrir la nota';
    caja.addEventListener('click', () => abrir(nota.id));
    caja.addEventListener('keydown', (evento) => {
      if (evento.key === 'Enter' && evento.target === caja) {
        abrir(nota.id);
      }
    });

    const cabecera = document.createElement('header');
    cabecera.className = 'nota-tarjeta-cabecera';
    const titulo = document.createElement('h2');
    titulo.className = 'nota-tarjeta-titulo';
    titulo.textContent = nota.titulo || (nota.tipo === 'lista' ? 'Lista sin título' : 'Nota sin título');
    cabecera.append(titulo);
    if (nota.fijada) {
      const fijada = document.createElement('span');
      fijada.className = 'nota-fijada';
      fijada.title = 'Fijada';
      fijada.textContent = '📌';
      cabecera.append(fijada);
    }
    caja.append(cabecera);

    if (nota.tipo === 'texto') {
      const texto = document.createElement('p');
      texto.className = 'nota-tarjeta-texto';
      texto.textContent = nota.contenido || 'Vacía';
      texto.classList.toggle('es-vacia', !nota.contenido);
      caja.append(texto);
    } else if (nota.tipo === 'tabla') {
      caja.append(...vistaPreviaTabla(leerTabla(nota.contenido)));
    } else {
      // Primero lo que falta; se puede tachar desde aquí mismo, sin abrir la lista
      const pendientes = nota.elementos.filter((e) => !e.hecho);
      const hechos = nota.elementos.filter((e) => e.hecho);
      const muestra = [...pendientes, ...hechos].slice(0, 8);
      const ul = document.createElement('ul');
      ul.className = 'nota-tarjeta-lista';
      muestra.forEach((elemento) => {
        const li = document.createElement('li');
        const boton = document.createElement('button');
        boton.type = 'button';
        boton.className = `nota-check${elemento.hecho ? ' is-hecho' : ''}`;
        boton.setAttribute('aria-pressed', String(elemento.hecho));
        boton.textContent = elemento.texto;
        boton.title = elemento.hecho ? 'Pulsa para desmarcar' : 'Pulsa para tachar';
        boton.addEventListener('click', (evento) => {
          evento.stopPropagation();
          tachar(nota, elemento);
        });
        li.append(boton);
        ul.append(li);
      });
      if (!nota.elementos.length) {
        const li = document.createElement('li');
        li.className = 'nota-tarjeta-vacia';
        li.textContent = 'Lista vacía';
        ul.append(li);
      }
      caja.append(ul);
      if (nota.elementos.length > muestra.length) {
        const mas = document.createElement('p');
        mas.className = 'nota-tarjeta-mas';
        mas.textContent = `+ ${nota.elementos.length - muestra.length} más`;
        caja.append(mas);
      }
    }

    const pie = document.createElement('footer');
    pie.className = 'nota-tarjeta-pie';
    if (nota.tipo === 'lista' && nota.elementos.length) {
      const progreso = document.createElement('span');
      progreso.className = 'nota-progreso';
      progreso.textContent = `☑️ ${nota.elementos.filter((e) => e.hecho).length}/${nota.elementos.length}`;
      pie.append(progreso);
    }
    if (nota.grupo_id) {
      pie.append(etiquetaGrupo(nota.grupo_id));
    }
    const fecha = document.createElement('span');
    fecha.className = 'nota-fecha';
    fecha.textContent = fechaNota(nota.actualizado_en);
    pie.append(fecha);
    caja.append(pie);
    return caja;
  }

  function vistaPreviaTabla(datos) {
    const resultados = calcularTabla(datos.filas);
    const filas = datos.filas.slice(0, 5);
    const columnas = Math.min(datos.filas[0].length, 4);
    const vacia = datos.filas.every((f) => f.every((c) => !String(c).trim()));
    if (vacia) {
      const texto = document.createElement('p');
      texto.className = 'nota-tarjeta-texto es-vacia';
      texto.textContent = 'Tabla vacía';
      return [texto];
    }
    const tablaEl = document.createElement('table');
    tablaEl.className = 'nota-tarjeta-tabla';
    filas.forEach((fila, f) => {
      const tr = document.createElement('tr');
      fila.slice(0, columnas).forEach((_, c) => {
        const celda = document.createElement(datos.encabezado && f === 0 ? 'th' : 'td');
        const r = resultados[f][c];
        celda.textContent = r.valor;
        celda.classList.toggle('es-numero', r.numero !== null && !(datos.encabezado && f === 0));
        celda.classList.toggle('es-error', Boolean(r.error));
        tr.append(celda);
      });
      tablaEl.append(tr);
    });
    const piezas = [tablaEl];
    const ocultas = [];
    const cuantas = (n, una, varias) => `${n} ${n === 1 ? una : varias}`;
    if (datos.filas.length > 5) ocultas.push(cuantas(datos.filas.length - 5, 'fila', 'filas'));
    if (datos.filas[0].length > 4) ocultas.push(cuantas(datos.filas[0].length - 4, 'columna', 'columnas'));
    if (ocultas.length) {
      const mas = document.createElement('p');
      mas.className = 'nota-tarjeta-mas';
      mas.textContent = `+ ${ocultas.join(' y ')} más`;
      piezas.push(mas);
    }
    return piezas;
  }

  // --- Cargar ------------------------------------------------------------------------------
  async function cargar() {
    try {
      const [datos] = await Promise.all([peticionNota(API_NOTAS), cargarGrupos()]);
      notas = Array.isArray(datos) ? datos : [];
      mostrarError('');
    } catch (error) {
      mostrarError('No se pudieron cargar las notas.');
    }
    pintar();
  }

  // --- Crear: primero se elige el tipo ----------------------------------------------------
  raiz.querySelector('[data-nota-nueva]').addEventListener('click', () => {
    modalTipo.hidden = false;
    modalTipo.querySelector('[data-tipo]').focus();
  });

  modalTipo.querySelectorAll('[data-tipo]').forEach((boton) => {
    boton.addEventListener('click', async () => {
      modalTipo.hidden = true;
      try {
        const nota = await peticionNota(API_NOTAS, { method: 'POST', body: JSON.stringify({ tipo: boton.dataset.tipo, titulo: '' }) });
        actualizarEnLista(nota);
        pintar();
        abrir(nota.id, true);
      } catch (error) {
        mostrarError(error.message);
      }
    });
  });

  // --- Editor ------------------------------------------------------------------------------
  function abrir(notaId, nueva = false) {
    const nota = notas.find((n) => n.id === notaId);
    if (!nota) {
      return;
    }
    abierta = nota;
    campoTitulo.value = nota.titulo;
    campoTexto.value = nota.contenido;
    campoTexto.hidden = nota.tipo !== 'texto';
    bloqueLista.hidden = nota.tipo !== 'lista';
    bloqueTabla.hidden = nota.tipo !== 'tabla';
    editor.querySelector('.nota-editor').classList.toggle('es-tabla', nota.tipo === 'tabla');
    if (nota.tipo === 'tabla') {
      tabla = leerTabla(nota.contenido);
      celdaActiva = { fila: 0, columna: 0 };
      pintarTabla();
    }
    campoGrupo.hidden = !rellenarSelectorGrupo(selectGrupo, 'notas', nota.grupo_id || null);
    estado.textContent = nota.grupo_id ? `Compartida con ${nombreGrupo(nota.grupo_id)}` : '';
    pintarFijar();
    pintarElementos();
    editor.hidden = false;
    document.body.classList.add('modal-abierto');
    if (nueva) {
      campoTitulo.focus();
    }
  }

  // --- Tabla ---------------------------------------------------------------------------------
  function celdaEn(fila, columna) {
    return rejilla.querySelector(`[data-fila="${fila}"][data-columna="${columna}"]`);
  }

  function pintarTabla() {
    const columnas = tabla.filas[0].length;
    const hoja = document.createElement('table');
    hoja.className = 'hoja';
    const cabecera = document.createElement('tr');
    const esquina = document.createElement('th');
    esquina.className = 'hoja-esquina';
    cabecera.append(esquina);
    for (let c = 0; c < columnas; c += 1) {
      const th = document.createElement('th');
      th.className = 'hoja-col';
      th.dataset.cabeceraColumna = c;
      th.textContent = letraColumna(c);
      cabecera.append(th);
    }
    const thead = document.createElement('thead');
    thead.append(cabecera);
    const tbody = document.createElement('tbody');
    tabla.filas.forEach((fila, f) => {
      const tr = document.createElement('tr');
      const numero = document.createElement('th');
      numero.className = 'hoja-fila';
      numero.dataset.cabeceraFila = f;
      numero.textContent = f + 1;
      tr.append(numero);
      fila.forEach((_, c) => {
        const td = document.createElement('td');
        const campo = document.createElement('input');
        campo.className = 'hoja-celda';
        campo.dataset.fila = f;
        campo.dataset.columna = c;
        campo.setAttribute('aria-label', `Celda ${letraColumna(c)}${f + 1}`);
        campo.autocomplete = 'off';
        campo.spellcheck = false;
        td.append(campo);
        tr.append(td);
      });
      tbody.append(tr);
    });
    hoja.append(thead, tbody);
    rejilla.replaceChildren(hoja);
    casillaEncabezado.checked = tabla.encabezado;
    refrescarTabla();
    pintarBotonesTabla();
  }

  // Cada celda enseña su resultado; la que se está editando, lo que hay escrito (la fórmula)
  function refrescarTabla() {
    const resultados = calcularTabla(tabla.filas);
    rejilla.querySelectorAll('.hoja-celda').forEach((campo) => {
      const f = Number(campo.dataset.fila);
      const c = Number(campo.dataset.columna);
      const r = resultados[f][c];
      const editando = campo === document.activeElement;
      if (!editando) {
        campo.value = r.valor;
      }
      const esEncabezado = tabla.encabezado && f === 0;
      campo.classList.toggle('es-encabezado', esEncabezado);
      campo.classList.toggle('es-numero', !editando && !esEncabezado && r.numero !== null);
      campo.classList.toggle('es-error', !editando && Boolean(r.error));
      campo.classList.toggle('es-formula', String(tabla.filas[f][c]).trim().startsWith('='));
      campo.title = String(tabla.filas[f][c]).trim().startsWith('=') ? `${tabla.filas[f][c]}` : '';
    });
    rejilla.querySelectorAll('[data-cabecera-fila]').forEach((th) => {
      th.classList.toggle('activa', Number(th.dataset.cabeceraFila) === celdaActiva.fila);
    });
    rejilla.querySelectorAll('[data-cabecera-columna]').forEach((th) => {
      th.classList.toggle('activa', Number(th.dataset.cabeceraColumna) === celdaActiva.columna);
    });
  }

  function pintarBotonesTabla() {
    const filas = tabla.filas.length;
    const columnas = tabla.filas[0].length;
    editor.querySelector('[data-tabla="fila"]').disabled = filas >= MAX_FILAS_TABLA;
    editor.querySelector('[data-tabla="columna"]').disabled = columnas >= MAX_COLUMNAS_TABLA;
    editor.querySelector('[data-tabla="quitar-fila"]').disabled = filas <= 1;
    editor.querySelector('[data-tabla="quitar-columna"]').disabled = columnas <= 1;
  }

  function irACelda(fila, columna) {
    const f = Math.max(0, Math.min(fila, tabla.filas.length - 1));
    const c = Math.max(0, Math.min(columna, tabla.filas[0].length - 1));
    const campo = celdaEn(f, c);
    if (campo) {
      campo.focus();
      campo.select();
    }
  }

  function tablaCambiada() {
    refrescarTabla();
    programarGuardado();
  }

  rejilla.addEventListener('focusin', (evento) => {
    const campo = evento.target.closest('.hoja-celda');
    if (!campo) return;
    celdaActiva = { fila: Number(campo.dataset.fila), columna: Number(campo.dataset.columna) };
    campo.value = tabla.filas[celdaActiva.fila][celdaActiva.columna];  // la fórmula, no el resultado
    refrescarTabla();
  });
  rejilla.addEventListener('focusout', () => {
    setTimeout(() => { if (tabla) refrescarTabla(); }, 0);  // al salir, la celda vuelve a enseñar su resultado
  });
  rejilla.addEventListener('input', (evento) => {
    const campo = evento.target.closest('.hoja-celda');
    if (!campo) return;
    tabla.filas[Number(campo.dataset.fila)][Number(campo.dataset.columna)] = campo.value.slice(0, 500);
    tablaCambiada();
  });
  rejilla.addEventListener('keydown', (evento) => {
    const campo = evento.target.closest('.hoja-celda');
    if (!campo) return;
    const f = Number(campo.dataset.fila);
    const c = Number(campo.dataset.columna);
    const alPrincipio = campo.selectionStart === 0 && campo.selectionEnd === 0;
    const alFinal = campo.selectionStart === campo.value.length;
    if (evento.key === 'Enter' || evento.key === 'ArrowDown') {
      evento.preventDefault();
      if (evento.key === 'Enter' && evento.shiftKey) {
        irACelda(f - 1, c);
      } else if (f === tabla.filas.length - 1 && evento.key === 'Enter' && tabla.filas.length < MAX_FILAS_TABLA) {
        anadirFila(f + 1);  // Intro en la última fila: fila nueva, como en las hojas de cálculo
        irACelda(f + 1, c);
      } else {
        irACelda(f + 1, c);
      }
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault();
      irACelda(f - 1, c);
    } else if (evento.key === 'ArrowLeft' && alPrincipio && c > 0) {
      evento.preventDefault();
      irACelda(f, c - 1);
    } else if (evento.key === 'ArrowRight' && alFinal && c < tabla.filas[0].length - 1) {
      evento.preventDefault();
      irACelda(f, c + 1);
    } else if (evento.key === 'Escape') {
      evento.stopPropagation();  // Escape solo sale de la celda, no cierra la nota
      evento.preventDefault();
      campo.blur();
    }
  });

  // Pegar varias celdas copiadas de Excel o Google Sheets (separadas por tabuladores y saltos de línea)
  rejilla.addEventListener('paste', (evento) => {
    const campo = evento.target.closest('.hoja-celda');
    const pegado = (evento.clipboardData || window.clipboardData).getData('text');
    if (!campo || !/[\t\n]/.test(pegado.replace(/\r?\n$/, ''))) {
      return;
    }
    evento.preventDefault();
    const bloque = pegado.replace(/\r/g, '').replace(/\n$/, '').split('\n').map((linea) => linea.split('\t'));
    const f0 = Number(campo.dataset.fila);
    const c0 = Number(campo.dataset.columna);
    const filasNecesarias = Math.min(MAX_FILAS_TABLA, f0 + bloque.length);
    const columnasNecesarias = Math.min(MAX_COLUMNAS_TABLA, c0 + Math.max(...bloque.map((l) => l.length)));
    while (tabla.filas.length < filasNecesarias) tabla.filas.push(Array(tabla.filas[0].length).fill(''));
    tabla.filas.forEach((fila) => { while (fila.length < columnasNecesarias) fila.push(''); });
    bloque.forEach((linea, i) => linea.forEach((valor, j) => {
      if (f0 + i < filasNecesarias && c0 + j < columnasNecesarias) {
        tabla.filas[f0 + i][c0 + j] = valor.slice(0, 500);
      }
    }));
    if (bloque.length + f0 > MAX_FILAS_TABLA || bloque.some((l) => l.length + c0 > MAX_COLUMNAS_TABLA)) {
      mostrarError(`Una tabla tiene como mucho ${MAX_FILAS_TABLA} filas y ${MAX_COLUMNAS_TABLA} columnas: lo que sobraba no se ha pegado.`);
    }
    pintarTabla();
    irACelda(f0, c0);
    programarGuardado();
  });

  function anadirFila(posicion) {
    tabla.filas = moverReferencias(tabla.filas, 'fila', posicion, 1);
    tabla.filas.splice(posicion, 0, Array(tabla.filas[0].length).fill(''));
    pintarTabla();
    programarGuardado();
  }

  editor.querySelectorAll('[data-tabla]').forEach((boton) => boton.addEventListener('click', () => {
    const { fila, columna } = celdaActiva;
    const accion = boton.dataset.tabla;
    if (accion === 'fila') {
      anadirFila(Math.min(fila + 1, tabla.filas.length));
      irACelda(fila + 1, columna);
      return;
    }
    if (accion === 'columna') {
      tabla.filas = moverReferencias(tabla.filas, 'columna', columna + 1, 1);
      tabla.filas.forEach((f) => f.splice(columna + 1, 0, ''));
      celdaActiva = { fila, columna: columna + 1 };
    } else if (accion === 'quitar-fila' && tabla.filas.length > 1) {
      tabla.filas = moverReferencias(tabla.filas, 'fila', fila, -1);
      tabla.filas.splice(fila, 1);
      celdaActiva = { fila: Math.min(fila, tabla.filas.length - 1), columna };
    } else if (accion === 'quitar-columna' && tabla.filas[0].length > 1) {
      tabla.filas = moverReferencias(tabla.filas, 'columna', columna, -1);
      tabla.filas.forEach((f) => f.splice(columna, 1));
      celdaActiva = { fila, columna: Math.min(columna, tabla.filas[0].length - 1) };
    }
    pintarTabla();
    irACelda(celdaActiva.fila, celdaActiva.columna);
    programarGuardado();
  }));

  casillaEncabezado.addEventListener('change', () => {
    tabla.encabezado = casillaEncabezado.checked;
    tablaCambiada();
  });

  function pintarFijar() {
    botonFijar.textContent = abierta && abierta.fijada ? '📌 Desfijar' : '📌 Fijar';
    botonFijar.setAttribute('aria-pressed', String(Boolean(abierta && abierta.fijada)));
  }

  function elementoEditable(elemento) {
    const li = document.createElement('li');
    li.className = `nota-elemento${elemento.hecho ? ' is-hecho' : ''}`;

    const marca = document.createElement('button');
    marca.type = 'button';
    marca.className = 'nota-check';
    marca.setAttribute('aria-pressed', String(elemento.hecho));
    marca.textContent = elemento.texto;
    marca.title = elemento.hecho ? 'Pulsa para desmarcar' : 'Pulsa para tachar';
    marca.addEventListener('click', () => tachar(abierta, elemento));

    const editar = document.createElement('button');
    editar.type = 'button';
    editar.className = 'icon-btn';
    editar.title = 'Cambiar el texto';
    editar.setAttribute('aria-label', `Cambiar «${elemento.texto}»`);
    editar.textContent = '✏️';
    editar.addEventListener('click', () => {
      const campo = document.createElement('input');
      campo.className = 'input nota-elemento-campo';
      campo.value = elemento.texto;
      campo.maxLength = 200;
      let hecho = false;
      const guardar = async (confirmar) => {
        if (hecho) return;
        hecho = true;
        const texto = campo.value.trim();
        if (confirmar && texto && texto !== elemento.texto) {
          await operar(`${API_NOTAS}/${abierta.id}/elementos/${elemento.id}`, 'PUT', { texto });
        }
        pintarElementos();
      };
      campo.addEventListener('keydown', (evento) => {
        if (evento.key === 'Enter') { evento.preventDefault(); guardar(true); }
        if (evento.key === 'Escape') { evento.preventDefault(); evento.stopPropagation(); guardar(false); }
      });
      campo.addEventListener('blur', () => guardar(true));
      marca.replaceWith(campo);
      campo.focus();
      campo.select();
    });

    const borrar = document.createElement('button');
    borrar.type = 'button';
    borrar.className = 'icon-btn delete';
    borrar.title = 'Quitar de la lista';
    borrar.setAttribute('aria-label', `Quitar «${elemento.texto}»`);
    borrar.textContent = '✕';
    borrar.addEventListener('click', () => operar(`${API_NOTAS}/${abierta.id}/elementos/${elemento.id}`, 'DELETE'));

    li.append(marca, editar, borrar);
    return li;
  }

  function pintarElementos() {
    if (!abierta || abierta.tipo !== 'lista') {
      return;
    }
    const pendientes = abierta.elementos.filter((e) => !e.hecho);
    const hechos = abierta.elementos.filter((e) => e.hecho);
    listaPendientes.replaceChildren(...pendientes.map(elementoEditable));
    if (!pendientes.length) {
      const li = document.createElement('li');
      li.className = 'nota-tarjeta-vacia';
      li.textContent = abierta.elementos.length ? '¡Todo hecho! 🎉' : 'Añade el primer elemento arriba.';
      listaPendientes.append(li);
    }
    listaHechos.replaceChildren(...hechos.map(elementoEditable));
    bloqueHechos.hidden = !hechos.length;
    tituloHechos.textContent = `Tachados (${hechos.length})`;
  }

  // Cambios de una lista: el servidor devuelve la nota entera, así se ve lo que hayan hecho otros
  async function operar(url, metodo, cuerpo) {
    try {
      const nota = await peticionNota(url, { method: metodo, body: cuerpo ? JSON.stringify(cuerpo) : undefined });
      actualizarEnLista(nota);
      mostrarError('');
    } catch (error) {
      mostrarError(error.message);
    }
    pintarElementos();
    pintar();
  }

  function tachar(nota, elemento) {
    elemento.hecho = !elemento.hecho;  // se ve al momento; luego llega lo que diga el servidor
    if (abierta && abierta.id === nota.id) {
      pintarElementos();
    }
    pintar();
    operar(`${API_NOTAS}/${nota.id}/elementos/${elemento.id}`, 'PUT', { hecho: elemento.hecho });
  }

  formAnadir.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    const texto = campoElemento.value;
    if (!texto.trim() || !abierta) {
      return;
    }
    campoElemento.value = '';
    await operar(`${API_NOTAS}/${abierta.id}/elementos`, 'POST', { texto });
    campoElemento.focus();  // para seguir apuntando cosas seguidas
  });

  // Pegar varias líneas (una lista copiada de otro sitio) añade un elemento por línea:
  // el campo es de una sola línea y, si no, las juntaría todas
  campoElemento.addEventListener('paste', (evento) => {
    const pegado = (evento.clipboardData || window.clipboardData).getData('text');
    if (!abierta || !/\r?\n/.test(pegado.trim())) {
      return;
    }
    evento.preventDefault();
    const delante = campoElemento.value.trim();
    campoElemento.value = '';
    operar(`${API_NOTAS}/${abierta.id}/elementos`, 'POST', { texto: delante ? `${delante}\n${pegado}` : pegado });
  });

  editor.querySelector('[data-nota-desmarcar]').addEventListener('click', () => {
    if (abierta) operar(`${API_NOTAS}/${abierta.id}/desmarcar`, 'POST');
  });
  editor.querySelector('[data-nota-limpiar]').addEventListener('click', () => {
    const tachados = abierta ? abierta.elementos.filter((e) => e.hecho).length : 0;
    if (tachados && window.confirm(`¿Borrar los ${tachados} elementos tachados?`)) {
      operar(`${API_NOTAS}/${abierta.id}/limpiar`, 'POST');
    }
  });

  // Título y texto se guardan solos mientras se escribe
  function programarGuardado() {
    estado.textContent = 'Escribiendo…';
    clearTimeout(temporizador);
    temporizador = setTimeout(guardarTexto, 700);
  }

  function guardarTexto() {
    clearTimeout(temporizador);
    temporizador = null;
    const nota = abierta;
    if (!nota) {
      return guardando;
    }
    const cambios = { titulo: campoTitulo.value };
    if (nota.tipo === 'texto') {
      cambios.contenido = campoTexto.value;
    } else if (nota.tipo === 'tabla' && tabla) {
      cambios.contenido = JSON.stringify(tabla);
    }
    // La tabla se compara ya leída: el servidor la guarda con otro espaciado
    const mismoContenido = nota.tipo === 'texto' ? cambios.contenido === nota.contenido
      : nota.tipo === 'tabla' ? cambios.contenido === JSON.stringify(leerTabla(nota.contenido)) : true;
    if (cambios.titulo === nota.titulo && mismoContenido) {
      estado.textContent = 'Guardada';
      return guardando;
    }
    estado.textContent = 'Guardando…';
    guardando = guardando.then(async () => {
      try {
        const guardada = await peticionNota(`${API_NOTAS}/${nota.id}`, { method: 'PUT', body: JSON.stringify(cambios) });
        // Si se ha seguido escribiendo, no se pisa lo que hay en pantalla
        if (abierta && abierta.id === guardada.id) {
          abierta.titulo = guardada.titulo;
          abierta.contenido = guardada.contenido;
          abierta.actualizado_en = guardada.actualizado_en;
        } else {
          actualizarEnLista(guardada);
        }
        estado.textContent = temporizador ? 'Escribiendo…' : 'Guardada ✓';
        mostrarError('');
      } catch (error) {
        mostrarError(error.message);
      }
    });
    return guardando;
  }

  campoTitulo.addEventListener('input', programarGuardado);
  campoTexto.addEventListener('input', programarGuardado);
  campoTitulo.addEventListener('keydown', (evento) => {
    if (evento.key === 'Enter') {
      evento.preventDefault();
      if (abierta && abierta.tipo === 'tabla') {
        irACelda(0, 0);
      } else {
        (abierta && abierta.tipo === 'lista' ? campoElemento : campoTexto).focus();
      }
    }
  });

  selectGrupo.addEventListener('change', async () => {
    const nota = abierta;
    const grupoId = selectGrupo.value ? Number(selectGrupo.value) : null;
    try {
      const guardada = await peticionNota(`${API_NOTAS}/${nota.id}`, { method: 'PUT', body: JSON.stringify({ grupo_id: grupoId }) });
      const contenido = nota.tipo === 'texto' ? campoTexto.value : nota.tipo === 'tabla' ? JSON.stringify(tabla) : guardada.contenido;
      actualizarEnLista({ ...guardada, titulo: campoTitulo.value, contenido });
      estado.textContent = grupoId ? `Compartida con ${nombreGrupo(grupoId)}` : 'Solo para ti';
      mostrarError('');
    } catch (error) {
      selectGrupo.value = nota.grupo_id ? String(nota.grupo_id) : '';
      mostrarError(error.message);
    }
    pintar();
  });

  botonFijar.addEventListener('click', async () => {
    const nota = abierta;
    try {
      const guardada = await peticionNota(`${API_NOTAS}/${nota.id}`, { method: 'PUT', body: JSON.stringify({ fijada: !nota.fijada }) });
      nota.fijada = guardada.fijada;
      nota.actualizado_en = guardada.actualizado_en;
      pintarFijar();
      pintar();
    } catch (error) {
      mostrarError(error.message);
    }
  });

  editor.querySelector('[data-nota-borrar]').addEventListener('click', async () => {
    const nota = abierta;
    const nombre = campoTitulo.value.trim() || (nota.tipo === 'lista' ? 'esta lista' : 'esta nota');
    const aviso = nota.grupo_id ? ` Se borrará para todo el grupo ${nombreGrupo(nota.grupo_id)}.` : '';
    if (!window.confirm(`¿Borrar «${nombre}»?${aviso}`)) {
      return;
    }
    clearTimeout(temporizador);
    temporizador = null;
    try {
      await peticionNota(`${API_NOTAS}/${nota.id}`, { method: 'DELETE' });
      notas = notas.filter((n) => n.id !== nota.id);
      cerrarEditor(false);
    } catch (error) {
      mostrarError(error.message);
    }
  });

  async function cerrarEditor(guardar = true) {
    const nota = abierta;
    if (guardar && nota) {
      await guardarTexto();
      // Una nota recién creada que se cierra sin escribir nada no se guarda
      const sinContenido = nota.tipo === 'texto' ? !campoTexto.value.trim()
        : nota.tipo === 'tabla' ? tabla.filas.every((f) => f.every((c) => !String(c).trim())) : !nota.elementos.length;
      const vacia = !campoTitulo.value.trim() && sinContenido;
      if (vacia) {
        await peticionNota(`${API_NOTAS}/${nota.id}`, { method: 'DELETE' }).catch(() => {});
        notas = notas.filter((n) => n.id !== nota.id);
      }
    }
    abierta = null;
    tabla = null;
    editor.hidden = true;
    document.body.classList.remove('modal-abierto');
    pintar();
  }

  editor.querySelectorAll('[data-cerrar]').forEach((boton) => boton.addEventListener('click', () => cerrarEditor()));
  modalTipo.querySelectorAll('[data-cerrar]').forEach((boton) => boton.addEventListener('click', () => { modalTipo.hidden = true; }));
  editor.addEventListener('click', (evento) => {
    if (evento.target === editor) cerrarEditor();
  });
  modalTipo.addEventListener('click', (evento) => {
    if (evento.target === modalTipo) modalTipo.hidden = true;
  });
  document.addEventListener('keydown', (evento) => {
    if (evento.key !== 'Escape') return;
    if (!modalTipo.hidden) modalTipo.hidden = true;
    else if (!editor.hidden) cerrarEditor();
  });

  buscador.addEventListener('input', pintar);

  // Al volver a la página se recargan, por si alguien del grupo ha cambiado una lista
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !abierta) {
      cargar();
    }
  });
  window.addEventListener('beforeunload', () => {
    if (temporizador) guardarTexto();
  });

  cargar();
}

function iniciarAppInstalable() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }

  // En el iPhone la app se queda abierta en segundo plano durante días. Al volver a ella tras un
  // rato, se recarga la página para no enseñar datos viejos (salvo que se esté escribiendo algo).
  const instalada = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  if (!instalada) return;
  let ocultaDesde = null;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      ocultaDesde = Date.now();
      return;
    }
    const enFormulario = document.querySelector('.modal-overlay:not([hidden]) .modal, input:focus, textarea:focus, select:focus');
    if (ocultaDesde && Date.now() - ocultaDesde > 5 * 60 * 1000 && !enFormulario) {
      window.location.reload();
    }
    ocultaDesde = null;
  });
}

function iniciarAplicacion() {
  vigilarSesion();
  iniciarAppInstalable();
  iniciarTema();
  renderizarInicio();
  renderizarVistaTareas();
  renderizarCalendario();
  renderizarRecordatorios();
  renderizarCorreos();
  renderizarNotas();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', iniciarAplicacion);
} else {
  iniciarAplicacion();
}
