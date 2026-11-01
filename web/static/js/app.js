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

function crearEtiquetaEvento(evento, alPulsar) {
  const repeticion = { semanal: 'Se repite cada semana', anual: 'Se repite cada año' }[evento.repeticion];
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
    campoHasta.hidden = form.elements.repeticion.value !== 'semanal';
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
      opcionSiguientes.hidden = eventoEditando.repeticion !== 'semanal';
      form.elements.alcance.value = 'uno';
    }
    form.elements.titulo.value = datos.titulo || '';
    form.elements.categoria.value = datos.categoria || 'Otro';
    form.elements.fecha.value = datos.fecha_inicio || datos.fecha || claveFecha(new Date());
    form.elements.hora_inicio.value = datos.hora_inicio || '';
    form.elements.hora_fin.value = datos.hora_fin || '';
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
  bloqueAlcance.addEventListener('change', aplicarAlcance);
  calendarRoot.querySelector('[data-event-new]').addEventListener('click', () => abrirFormulario(null));
  calendarRoot.querySelector('[data-event-close]').addEventListener('click', cerrarFormulario);

  form.addEventListener('submit', async (envio) => {
    envio.preventDefault();
    const datos = Object.fromEntries(new FormData(form).entries());
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

      const etiquetas = [
        ...eventosDelDia.map((evento) => crearEtiquetaEvento(evento, abrirFormulario)),
        ...tareasDelDia.map((tarea) => crearEtiquetaTarea(tarea))
      ];
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
  meta.append(
    crearElemento('span', `reminder-chip estado-${recordatorio.estado}`, etiquetasEstado[recordatorio.estado]),
    crearElemento('span', 'reminder-chip', recordatorio.canal)
  );
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

// --- Inicio: resumen de hoy y de los próximos días --------------------------------

function elementoLinea(cuando, texto, tipo, claseExtra = '') {
  const li = document.createElement('li');
  li.className = `timeline-item tipo-${tipo} ${claseExtra}`.trim();
  const momento = document.createElement('span');
  momento.className = 'timeline-when';
  momento.textContent = cuando;
  const titulo = document.createElement('span');
  titulo.className = 'timeline-text';
  titulo.textContent = texto;
  titulo.title = texto;
  const etiqueta = document.createElement('span');
  etiqueta.className = 'timeline-tipo';
  etiqueta.textContent = { evento: 'Evento', tarea: 'Tarea', recordatorio: 'Aviso', atrasada: 'Atrasada' }[tipo];
  li.append(momento, titulo, etiqueta);
  return li;
}

function rellenarLista(lista, elementos, vacio) {
  if (!lista) {
    return;
  }
  lista.replaceChildren(...(elementos.length ? elementos : [Object.assign(document.createElement('li'), {
    className: 'empty-state', textContent: vacio
  })]));
}

function diaCorto(clave, hoyClave) {
  if (clave === hoyClave) {
    return 'Hoy';
  }
  const fecha = new Date(`${clave}T00:00`);
  return fecha.toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric' });
}

async function renderizarInicio() {
  const raiz = document.querySelector('#inicio-app');
  if (!raiz) {
    return;
  }

  const ahora = new Date();
  const hoyClave = claveFecha(ahora);
  const hora = ahora.getHours();
  raiz.querySelector('[data-inicio-saludo]').textContent =
    `${hora < 6 ? 'Buenas noches' : hora < 13 ? 'Buenos días' : hora < 21 ? 'Buenas tardes' : 'Buenas noches'} 👋`;
  const fechaLarga = ahora.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' });
  raiz.querySelector('[data-inicio-fecha]').textContent = fechaLarga;

  const enUnaSemana = new Date(ahora);
  enUnaSemana.setDate(enUnaSemana.getDate() + 6);
  const [tareas, eventos, recordatorios] = await Promise.all([
    cargarTareas(),
    cargarEventos(hoyClave, claveFecha(enUnaSemana)),
    fetch(API_REMINDERS_URL).then((r) => (r.ok ? r.json() : [])).catch(() => [])
  ]);

  const pendientes = tareas.filter((t) => t.status !== 'Terminado');
  const atrasadas = pendientes.filter((t) => t.fecha_limite && t.fecha_limite < hoyClave);
  const avisos = recordatorios.filter((r) => r.estado === 'pendiente');

  raiz.querySelector('[data-stat-pendientes]').textContent = pendientes.length;
  raiz.querySelector('[data-stat-atrasadas]').textContent = atrasadas.length;
  raiz.querySelector('[data-stat-eventos]').textContent = eventos.length;
  raiz.querySelector('[data-stat-recordatorios]').textContent = avisos.length;

  const claseEvento = (e) => `categoria-${CLASE_CATEGORIA[e.categoria] || 'otro'}`;
  const emoji = (e) => EMOJI_CATEGORIA[e.categoria] || '📌';

  // Hoy: atrasadas, eventos, tareas que vencen y avisos, por hora
  const hoy = [
    ...atrasadas.map((t) => ({ orden: '00:00', el: elementoLinea(formatearFecha(t.fecha_limite).slice(0, 5), t.nombre, 'atrasada') })),
    ...eventos.filter((e) => e.fecha === hoyClave).map((e) => ({
      orden: e.hora_inicio || '00:01',
      el: elementoLinea(e.hora_inicio || 'Todo el día', `${emoji(e)} ${e.titulo}`, 'evento', claseEvento(e))
    })),
    ...pendientes.filter((t) => t.fecha_limite === hoyClave).map((t) => ({
      orden: t.hora_limite || '23:59', el: elementoLinea(t.hora_limite || 'Hoy', t.nombre, 'tarea')
    })),
    ...avisos.filter((r) => r.cuando.startsWith(hoyClave)).map((r) => ({
      orden: r.cuando.slice(11), el: elementoLinea(r.cuando.slice(11), `⏰ ${r.texto}`, 'recordatorio')
    }))
  ].sort((a, b) => a.orden.localeCompare(b.orden)).map((x) => x.el);
  rellenarLista(raiz.querySelector('[data-inicio-hoy]'), hoy, 'Nada para hoy. ¡Día libre! 🎉');

  // Próximos días (sin hoy), máximo 8
  const proximos = [
    ...eventos.filter((e) => e.fecha > hoyClave).map((e) => ({
      orden: `${e.fecha} ${e.hora_inicio || '00:00'}`,
      el: elementoLinea(diaCorto(e.fecha, hoyClave), `${emoji(e)} ${e.titulo}`, 'evento', claseEvento(e))
    })),
    ...pendientes.filter((t) => t.fecha_limite > hoyClave && t.fecha_limite <= claveFecha(enUnaSemana)).map((t) => ({
      orden: `${t.fecha_limite} ${t.hora_limite || '23:59'}`, el: elementoLinea(diaCorto(t.fecha_limite, hoyClave), t.nombre, 'tarea')
    }))
  ].sort((a, b) => a.orden.localeCompare(b.orden)).slice(0, 8).map((x) => x.el);
  rellenarLista(raiz.querySelector('[data-inicio-proximos]'), proximos, 'Nada en los próximos 7 días.');

  const sinFecha = pendientes.filter((t) => !t.fecha_limite).slice(0, 6).map((t) =>
    elementoLinea(t.importancia, t.nombre, 'tarea', `imp-${t.importancia.toLowerCase()}`));
  rellenarLista(raiz.querySelector('[data-inicio-sinfecha]'), sinFecha, 'Ninguna: todas tienen fecha 👌');
}

function iniciarAplicacion() {
  iniciarTema();
  renderizarInicio();
  renderizarVistaTareas();
  renderizarCalendario();
  renderizarRecordatorios();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', iniciarAplicacion);
} else {
  iniciarAplicacion();
}
