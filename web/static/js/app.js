const API_TASKS_URL = '/api/tareas';
// A quién se asignan las tareas si no se indica nadie (PERSONA_POR_DEFECTO del .env)
const PERSONA_DEFECTO = (document.querySelector('meta[name="persona-defecto"]') || {}).content || 'Sin asignar';

function esPersonaDefecto(persona) {
  return !persona || persona === 'Sin asignar' || persona === PERSONA_DEFECTO;
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
    persona: tarea.persona || PERSONA_DEFECTO
  };
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

  return normalizarTarea(await response.json());
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

  return normalizarTarea(await response.json());
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
  const detalle = [`${EMOJI_CATEGORIA[evento.categoria] || '📌'} ${evento.categoria}: ${evento.titulo}`, horarioEvento(evento), repeticion, 'Pulsa para editar']
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
  let eventoEditando = null;
  // Día pulsado de un evento que se repite (null si no se repite o es nuevo)
  let ocurrencia = null;

  async function recargar() {
    const year = state.fechaVista.getFullYear();
    const month = state.fechaVista.getMonth();
    const [tareas, eventos] = await Promise.all([
      cargarTareas(),
      cargarEventos(claveFecha(new Date(year, month, 1)), claveFecha(new Date(year, month + 1, 0)))
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
        menuAbierto: null,
        mostrarModal: false,
        tareaEditando: null,
        indiceEditando: null,
        nuevaTarea: { nombre: '', importancia: '', fecha_limite: '', hora_limite: '', persona: '' },
        tareas: [],
        cargando: true,
        errorCarga: '',
        orden: leerOrdenTabla(),
        personaDefecto: PERSONA_DEFECTO
      };
    },

    computed: {
      // Sin orden elegido, la tabla mantiene el del servidor (por fecha límite)
      tareasOrdenadas() {
        const { campo, sentido } = this.orden;
        if (!campo) {
          return this.tareas;
        }
        return [...this.tareas].sort((a, b) => compararTareas(a, b, campo, sentido));
      }
    },

    async mounted() {
      await this.recargarTareas();
    },

    methods: {
      formatearFecha,
      esPersonaDefecto,

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
            }
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
      },

      dragEnd() {
        this.tareaArrastrando = null;
      },

      dragOver(estado, event) {
        event.currentTarget.classList.add('highlight');
      },

      async drop(estado) {
        if (this.tareaArrastrando) {
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
            persona: this.nuevaTarea.persona || PERSONA_DEFECTO
          });

          this.tareas.push(tareaCreada);
          this.nuevaTarea = { nombre: '', importancia: '', fecha_limite: '', hora_limite: '', persona: '' };
          this.mostrarFormulario = false;
        } catch (error) {
          this.errorCarga = error.message;
        }
      },

      async eliminarTarea(index, estado) {
        const lista = this.tareas.filter((tarea) => tarea.status === estado);
        const tarea = lista[index];

        if (!tarea) {
          return;
        }

        await this.eliminarPorId(tarea.id);
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

function crearTarjetaRecordatorio(recordatorio, alCambiar) {
  const tarjeta = crearElemento('article', `reminder-card is-${{ enviado: 'sent', error: 'error' }[recordatorio.estado] || 'pending'}`);

  const columnaTexto = crearElemento('div');
  const inputTexto = crearElemento('input');
  inputTexto.type = 'text';
  inputTexto.value = recordatorio.texto;
  inputTexto.setAttribute('aria-label', 'Texto del recordatorio');
  const meta = crearElemento('div', 'reminder-meta');
  const etiquetasEstado = { pendiente: 'Pendiente', enviado: 'Enviado', error: 'No se pudo enviar' };
  meta.append(crearElemento('span', `reminder-chip estado-${recordatorio.estado}`, etiquetasEstado[recordatorio.estado]));
  columnaTexto.append(inputTexto, meta);

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
  tarjeta.append(columnaTexto, inputFecha, acciones, mensaje);

  const hayCambios = () =>
    inputTexto.value.trim() !== recordatorio.texto || inputFecha.value !== recordatorio.cuando;
  [inputTexto, inputFecha].forEach((input) =>
    input.addEventListener('input', () => {
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
        body: JSON.stringify({ texto: inputTexto.value.trim(), cuando: inputFecha.value })
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

async function renderizarRecordatorios() {
  const raiz = document.querySelector('#reminders-app');
  if (!raiz) {
    return;
  }

  const listaPendientes = raiz.querySelector('[data-reminders-pending-list]');
  const listaHechos = raiz.querySelector('[data-reminders-done-list]');
  const contador = raiz.querySelector('[data-reminders-pending]');
  const proximo = raiz.querySelector('[data-reminders-next]');

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
        ? pendientes.map((r) => crearTarjetaRecordatorio(r, recargar))
        : [crearElemento('p', 'calendar-empty-state', 'No hay recordatorios pendientes. Pídeselos al bot: "recuérdame mañana a las 10 que…"')])
    );
    listaHechos.replaceChildren(
      ...(hechos.length
        ? hechos.map((r) => crearTarjetaRecordatorio(r, recargar))
        : [crearElemento('p', 'calendar-empty-state', 'Nada enviado en los últimos 30 días.')])
    );
  }

  await recargar();
}

// --- Tema claro / oscuro ---------------------------------------------------------

function iniciarTema() {
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

  async function abrir(cuenta, uid) {
    abierto = `${cuenta}/${uid}`;
    history.replaceState(null, '', `#${abierto}`);
    pintar();
    detalle.hidden = false;
    errorDetalle.textContent = '';
    raiz.querySelector('[data-correo-asunto]').textContent = 'Abriendo…';
    raiz.querySelector('[data-correo-de]').textContent = '';
    raiz.querySelector('[data-correo-meta]').textContent = '';
    raiz.querySelector('[data-correo-texto]').textContent = '';
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
      raiz.querySelector('[data-correo-texto]').textContent = correo.texto || '(Este correo no tiene texto)';
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

function iniciarAplicacion() {
  iniciarTema();
  renderizarInicio();
  renderizarVistaTareas();
  renderizarCalendario();
  renderizarRecordatorios();
  renderizarCorreos();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', iniciarAplicacion);
} else {
  iniciarAplicacion();
}
