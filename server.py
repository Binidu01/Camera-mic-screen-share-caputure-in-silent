# --- gevent monkey patch MUST come before any other import ---
from gevent import monkey
monkey.patch_all()

import os
import requests
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="gevent",
    ping_interval=25,
    ping_timeout=60,
    logger=False,
    engineio_logger=False,
)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/healthz')
def healthz():
    return "ok", 200


@socketio.on('connect')
def on_connect():
    print(f"Client connected: {request.sid}")
    return True


@socketio.on('disconnect')
def on_disconnect():
    print(f"Client disconnected: {request.sid}")


# ────────────── LOCATION ──────────────
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


# ────────────── WEBCAM ──────────────
@socketio.on('video_frame')
def handle_video(data):
    emit('video_frame', data, broadcast=True, include_self=False)


# ────────────── SCREEN ──────────────
@socketio.on('screen_frame')
def handle_screen(data):
    emit('screen_frame', data, broadcast=True, include_self=False)


# ────────────── LIVE AUDIO ──────────────
@socketio.on('audio_data')
def handle_audio(data):
    # data = {pcm: base64, rate: int, channels: int}
    # Just relay it — no decoding, no storage.
    emit('audio_data', data, broadcast=True, include_self=False)


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
