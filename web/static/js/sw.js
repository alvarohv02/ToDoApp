// Service worker de la app instalable (iPhone/Android/escritorio).
//
// Qué hace:
//   - Guarda una copia de las páginas y de los archivos estáticos para que la app abra al instante
//     y siga mostrando algo si no hay conexión (por ejemplo, con Tailscale desconectado).
//   - Nunca guarda las respuestas de /api/: los datos se piden siempre al servidor.
//
// Estrategia "red primero, caché de respaldo": se intenta la red y, si falla, se sirve lo guardado.
// Así una actualización del código llega en la siguiente carga sin tener que tocar nada aquí.
const CACHE = 'mi-notion-v1';
const PRECARGA = [
    '/',
    '/tareas',
    '/calendar',
    '/recordatorios',
    '/correos',
    '/static/css/app.css',
    '/static/js/app.js',
    '/static/img/Logo_Notas.png',
    '/static/img/icono-192.png',
    'https://unpkg.com/vue@3/dist/vue.global.js',
];

self.addEventListener('install', (evento) => {
    evento.waitUntil(
        caches.open(CACHE)
            // Que falle un archivo no impide instalar el resto
            .then((cache) => Promise.allSettled(PRECARGA.map((url) => cache.add(url))))
            .then(() => self.skipWaiting()),
    );
});

self.addEventListener('activate', (evento) => {
    evento.waitUntil(
        caches.keys()
            .then((nombres) => Promise.all(nombres.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
            .then(() => self.clients.claim()),
    );
});

self.addEventListener('fetch', (evento) => {
    const peticion = evento.request;
    if (peticion.method !== 'GET') return;

    const url = new URL(peticion.url);
    const esApi = url.origin === self.location.origin && url.pathname.startsWith('/api/');
    const esVue = url.hostname === 'unpkg.com';
    if (esApi) return;
    if (url.origin !== self.location.origin && !esVue) return;

    evento.respondWith(
        fetch(peticion)
            .then((respuesta) => {
                if (respuesta.ok || respuesta.type === 'opaque') {
                    const copia = respuesta.clone();
                    caches.open(CACHE).then((cache) => cache.put(peticion, copia)).catch(() => {});
                }
                return respuesta;
            })
            .catch(async () => {
                const guardada = await caches.match(peticion, { ignoreSearch: peticion.mode === 'navigate' });
                if (guardada) return guardada;
                if (peticion.mode === 'navigate') {
                    return new Response(
                        '<!DOCTYPE html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
                        + '<title>Sin conexión · Mi Notion</title>'
                        + '<body style="font-family:system-ui,sans-serif;background:#f5f6fa;color:#1c2030;display:grid;place-items:center;min-height:100vh;margin:0;text-align:center;padding:2rem">'
                        + '<div><h1 style="font-size:1.4rem">No hay conexión con el servidor</h1>'
                        + '<p>Comprueba que Tailscale está conectado y vuelve a intentarlo.</p>'
                        + '<p><a href="/" style="color:#4f6df5;font-weight:600">Reintentar</a></p></div></body></html>',
                        { headers: { 'Content-Type': 'text/html; charset=utf-8' } },
                    );
                }
                return Response.error();
            }),
    );
});
