# --- gevent monkey patch MUST come before any other import ---
from gevent import monkey
monkey.patch_all()

import os
import wave
import base64
import requests
from flask import Flask, render_template, send_from_directory, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)

# ping_interval / ping_timeout keep the WebSocket alive through Render's proxy
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="gevent",
    ping_interval=25,
    ping_timeout=60,
    logger=False,
    engineio_logger=False,
)

# Buffer to store audio chunks
audio_frames = []


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/healthz')
def healthz():
    return "ok", 200


@socketio.on('connect')
def on_connect():
    print(f"Client connected: {request.sid}")
    return True  # explicit accept


@socketio.on('disconnect')
def on_disconnect():
    print(f"Client disconnected: {request.sid}")


@socketio.on('client_info')
def handle_client_info(data):
    ip = data.get('ip', 'Unknown')
    loc = {'ip': ip, 'city': '', 'region': '', 'country': '',
           'latitude': None, 'longitude': None}
    try:
        res = requests.get(f'https://ipapi.co/{ip}/json/', timeout=5).json()
        loc.update({
            'city':      res.get('city', ''),
            'region':    res.get('region', ''),
            'country':   res.get('country_name', ''),
            'latitude':  res.get('latitude'),
            'longitude': res.get('longitude'),
        })
    except Exception as e:
        print("Geolocation lookup failed:", e)
    emit('client_location', loc, broadcast=True)


@socketio.on('video_frame')
def handle_video(data):
    emit('video_frame', data, broadcast=True, include_self=False)


@socketio.on('screen_frame')
def handle_screen(data):
    emit('screen_frame', data, broadcast=True, include_self=False)


@socketio.on('audio_data')
def handle_audio(data):
    global audio_frames
    try:
        chunk = base64.b64decode(data)
        audio_frames.append(chunk)
        # Cap memory so a long demo doesn't OOM the free 512 MB instance
        if len(audio_frames) > 5000:
            audio_frames = audio_frames[-5000:]
    except Exception as e:
        print("Audio decode error:", e)
    emit('audio_data', data, broadcast=True, include_self=False)


@app.route('/save_audio')
def save_audio():
    global audio_frames
    if not audio_frames:
        return "No audio to save", 400
    try:
        wf = wave.open('received_audio.wav', 'wb')
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"".join(audio_frames))
        wf.close()
        audio_frames = []
        return send_from_directory('.', 'received_audio.wav', as_attachment=True)
    except Exception as e:
        return f"Error saving audio: {e}", 500


# --- entry point ---
# Locally: `python server.py` runs the gevent WSGI server.
# On Render: gunicorn with the gevent-websocket worker serves `app`,
# so this block is not used, but keep it so local testing still works.
if __name__ == '__main__':
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler

    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on 0.0.0.0:{port}")
    server = pywsgi.WSGIServer(
        ('', port),
        app,
        handler_class=WebSocketHandler,
    )
    server.serve_forever()
