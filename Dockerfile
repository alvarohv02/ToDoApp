FROM python:3.12-slim

# tzdata: para que "hoy" y "mañana" usen la zona horaria de TZ y no UTC
# ffmpeg: convierte las notas de voz (OGG/Opus) al formato que entiende el reconocedor de voz
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Madrid \
    VOSK_MODEL_PATH=/app/modelo-vosk

WORKDIR /app

# Modelo de voz a texto en español (Vosk, ~40 MB, funciona sin conexión y en CPUs antiguas)
ARG VOSK_MODEL=vosk-model-small-es-0.42
RUN python -c "import io, urllib.request, zipfile; \
z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen('https://alphacephei.com/vosk/models/${VOSK_MODEL}.zip').read())); \
z.extractall('/tmp/m')" \
    && mv /tmp/m/${VOSK_MODEL} /app/modelo-vosk && rm -rf /tmp/m && chmod -R a+rX /app/modelo-vosk

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY web/ web/
# Los archivos pueden llegar del servidor con permisos solo para su dueño (p. ej. tras un scp);
# el usuario del contenedor necesita poder leer el código, las plantillas y los estáticos
RUN chmod -R a+rX web

# Usuario sin privilegios; uid 1000 coincide con el primer usuario de Ubuntu,
# así puede escribir en la carpeta ./data montada desde el servidor
RUN useradd --uid 1000 --create-home notion \
    && mkdir -p web/data \
    && chown -R notion:notion web/data
USER notion

WORKDIR /app/web
EXPOSE 5000

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/tareas', timeout=4)"

# Un solo proceso: el bot de Telegram escucha en un hilo y no puede haber dos copias
CMD ["waitress-serve", "--listen=0.0.0.0:5000", "--threads=4", "app:app"]
