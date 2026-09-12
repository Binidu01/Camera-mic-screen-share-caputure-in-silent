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

broadcasters = set()


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
    broadcasters.discard(request.sid)
    print(f"Client disconnected: {request.sid}")


# ────────────── LOCATION ──────────────
def _lookup_location(ip):
    loc = {'ip': ip, 'city': '', 'region': '', 'country': '',
           'latitude': None, 'longitude': None}

    try:
        res = requests.get(
            f'http://ip-api.com/json/{ip}',
            params={'fields': 'status,country,regionName,city,lat,lon'},
            timeout=5,
        ).json()
        if res.get('status') == 'success':
            loc.update({
                'city':      res.get('city', ''),
                'region':    res.get('regionName', ''),
                'country':   res.get('country', ''),
                'latitude':  res.get('lat'),
                'longitude': res.get('lon'),
            })
            return loc
    except Exception as e:
        print("ip-api failed:", e)

    try:
        res = requests.get(f'https://ipwho.is/{ip}', timeout=5).json()
        if res.get('success'):
            loc.update({
                'city':      res.get('city', ''),
                'region':    res.get('region', ''),
                'country':   res.get('country', ''),
                'latitude':  res.get('latitude'),
                'longitude': res.get('longitude'),
            })
            return loc
    except Exception as e:
        print("ipwho.is failed:", e)

    return loc


@socketio.on('client_info')
def handle_client_info(data):
    ip = data.get('ip', 'Unknown')
    emit('client_location', _lookup_location(ip), broadcast=True)


# ────────────── WEBRTC SIGNALING ──────────────
@socketio.on('register_broadcaster')
def on_register_broadcaster(data=None):
    broadcasters.add(request.sid)
    print(f"Broadcaster registered: {request.sid}")


@socketio.on('viewer_ready')
def on_viewer_ready():
    """A proctor page opened → ask every broadcaster to send them an offer."""
    for b in list(broadcasters):
        emit('viewer_joined', {'sid': request.sid}, to=b)


@socketio.on('webrtc_offer')
def on_offer(data):
    emit('webrtc_offer', {'from': request.sid, 'sdp': data['sdp']},
         to=data['target'])


@socketio.on('webrtc_answer')
def on_answer(data):
    emit('webrtc_answer', {'from': request.sid, 'sdp': data['sdp']},
         to=data['target'])


@socketio.on('webrtc_ice')
def on_ice(data):
    emit('webrtc_ice', {'from': request.sid, 'candidate': data['candidate']},
         to=data['target'])


if __name__ == '__main__':
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler

    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on 0.0.0.0:{port}")
    server = pywsgi.WSGIServer(('', port), app, handler_class=WebSocketHandler)
    server.serve_forever()
