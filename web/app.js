const { createApp } = Vue;

function formatearFecha(fechaStr) {
  const [year, month, day] = fechaStr.split("-");
  const d = Number(day);
  const m = Number(month);
  
  return `${d}/${m}/${year}`;
}

createApp({
  data() {
    return {
      vista: 'tablero',
      mostrarFormulario: false,
      tareaArrastrando: null,
      nuevaTarea: { nombre: "", importancia: "", fecha_limite: "", persona: "" },
      tareas: []
    }
  },
  methods: {
    dragStart(tarea) { this.tareaArrastrando = tarea; },
    dragEnd() { this.tareaArrastrando = null; },
    dragOver(estado, event) { event.currentTarget.classList.add('highlight'); },
    drop(estado) {
      if (this.tareaArrastrando) {
        this.tareaArrastrando.status = estado;
      }
      document.querySelectorAll('.column').forEach(c => c.classList.remove('highlight'));
    },

    agregarTarea() {
      if (!this.nuevaTarea.nombre || !this.nuevaTarea.importancia) return;
      this.tareas.push({
        nombre: this.nuevaTarea.nombre,
        importancia: this.nuevaTarea.importancia,
        fecha_limite: formatearFecha(this.nuevaTarea.fecha_limite),
        status: "Sin empezar",
        fecha: new Date().toLocaleDateString(),
        persona: this.nuevaTarea.persona || "Sin asignar"
      });
      this.nuevaTarea = { nombre: "", importancia: "", fecha_limite: "", persona: "" };
      this.mostrarFormulario = false;
    },

    eliminarTarea(index, estado) {
      let lista = this.tareas.filter(t => t.status === estado);
      let tarea = lista[index];
      this.tareas = this.tareas.filter(t => t !== tarea);
    },

    eliminarTareaTabla(index) {
      this.tareas.splice(index, 1);
    }
  }
}).mount('#app');