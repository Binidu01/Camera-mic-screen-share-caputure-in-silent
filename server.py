# --- gevent monkey patch MUST come before any other import ---
from gevent import monkey
monkey.patch_all()

# --- force TCP_NODELAY on every accepted connection ---
import socket as _socket
_orig_accept = _socket.socket.accept
def _accept_nodelay(self):
    conn, addr = _orig_accept(self)
    try:
        conn.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
    except Exception:
        pass
    return conn, addr
_socket.socket.accept = _accept_nodelay

import os
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
    max_http_buffer_size=5_000_000,
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


# ────────────── WEBCAM ──────────────
@socketio.on('video_frame_bytes')
def handle_video_bytes(data):
    emit('video_frame_bytes', data, broadcast=True, include_self=False)

@socketio.on('video_frame')
def handle_video(data):
    emit('video_frame', data, broadcast=True, include_self=False)


# ────────────── SCREEN ──────────────
@socketio.on('screen_frame_bytes')
def handle_screen_bytes(data):
    emit('screen_frame_bytes', data, broadcast=True, include_self=False)

@socketio.on('screen_frame')
def handle_screen(data):
    emit('screen_frame', data, broadcast=True, include_self=False)


# ────────────── LIVE AUDIO ──────────────
@socketio.on('audio_bytes')
def handle_audio_bytes(data):
    emit('audio_bytes', data, broadcast=True, include_self=False)

@socketio.on('audio_data')
def handle_audio(data):
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
