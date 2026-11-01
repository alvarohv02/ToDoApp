"""Voz a texto en el propio servidor con Vosk (sin servicios externos).

Las notas de voz de Telegram y WhatsApp llegan en OGG/Opus: ffmpeg las convierte a PCM de 16 kHz
mono, que es lo que espera el modelo. El modelo se carga la primera vez y se queda en memoria.
"""
import json
import logging
import os
import subprocess
import threading

log = logging.getLogger(__name__)

FRECUENCIA = 16000
MAX_SEGUNDOS = 180  # protege al servidor de audios muy largos

_modelo = None
_cerrojo = threading.Lock()  # Vosk no es seguro con varios hilos usando el mismo reconocedor a la vez


class TranscripcionNoDisponible(Exception):
    pass


def _cargar_modelo():
    global _modelo
    if _modelo is None:
        ruta = os.getenv('VOSK_MODEL_PATH', '/app/modelo-vosk')
        if not os.path.isdir(ruta):
            raise TranscripcionNoDisponible(f'No encuentro el modelo de voz en {ruta}')
        try:
            from vosk import Model, SetLogLevel
        except ImportError as error:
            raise TranscripcionNoDisponible('La librería vosk no está instalada') from error
        SetLogLevel(-1)
        log.info('Cargando el modelo de voz (solo la primera vez)...')
        _modelo = Model(ruta)
    return _modelo


def _a_pcm(audio):
    try:
        proceso = subprocess.run(
            ['ffmpeg', '-loglevel', 'error', '-i', 'pipe:0', '-t', str(MAX_SEGUNDOS),
             '-ar', str(FRECUENCIA), '-ac', '1', '-f', 's16le', 'pipe:1'],
            input=audio, capture_output=True, timeout=120, check=True,
        )
    except FileNotFoundError as error:
        raise TranscripcionNoDisponible('ffmpeg no está instalado') from error
    except subprocess.CalledProcessError as error:
        raise ValueError(f'No se pudo leer el audio: {error.stderr.decode(errors="ignore")[:200]}') from error
    return proceso.stdout


def transcribir(audio):
    """Bytes de un audio (ogg, mp3, m4a...) -> texto en español, sin puntuación."""
    from vosk import KaldiRecognizer

    pcm = _a_pcm(audio)
    with _cerrojo:
        reconocedor = KaldiRecognizer(_cargar_modelo(), FRECUENCIA)
        trozos = []
        bloque = 8000  # 0,25 s de audio
        for inicio in range(0, len(pcm), bloque):
            if reconocedor.AcceptWaveform(pcm[inicio:inicio + bloque]):
                trozos.append(json.loads(reconocedor.Result()).get('text', ''))
        trozos.append(json.loads(reconocedor.FinalResult()).get('text', ''))
    return ' '.join(t for t in trozos if t).strip()
