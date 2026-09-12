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
    # Allow larger binary frames (screen @ 480x270 q25 is ~15 KB, so this is plenty)
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


# ────────────── LOCATION ──────────────
# Try three free providers in order. Each has different rate limits and
# reliability, so if one is down or rate-limited we fall through to the next.
def _lookup_location(ip):
    loc = {'ip': ip, 'city': '', 'region': '', 'country': '',
           'latitude': None, 'longitude': None}

    # Provider 1: ip-api.com — 45 req/min free, no key required.
    # NOTE: free tier is HTTP only, not HTTPS. Falls through on failure.
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
            print(f"[ip-api] {ip} -> {loc['city']}, {loc['country']}")
            return loc
    except Exception as e:
        print("ip-api lookup failed:", e)

    # Provider 2: ipwho.is — unlimited, HTTPS, no key
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
            print(f"[ipwho.is] {ip} -> {loc['city']}, {loc['country']}")
            return loc
    except Exception as e:
        print("ipwho.is lookup failed:", e)

    # Provider 3: ipapi.co — HTTPS, 1000/day free (often rate-limited from
    # shared cloud IPs like Render's, so it's last in the chain).
    try:
        res = requests.get(f'https://ipapi.co/{ip}/json/', timeout=5).json()
        if not res.get('error'):
            loc.update({
                'city':      res.get('city', ''),
                'region':    res.get('region', ''),
                'country':   res.get('country_name', ''),
                'latitude':  res.get('latitude'),
                'longitude': res.get('longitude'),
            })
            print(f"[ipapi.co] {ip} -> {loc['city']}, {loc['country']}")
            return loc
    except Exception as e:
        print("ipapi.co lookup failed:", e)

    print(f"[location] All providers failed for {ip}")
    return loc


@socketio.on('client_info')
def handle_client_info(data):
    ip = data.get('ip', 'Unknown')
    loc = _lookup_location(ip)
    emit('client_location', loc, broadcast=True)


# ────────────── WEBCAM ──────────────
# Binary transport (bytes) — used by the low-latency client.
@socketio.on('video_frame_bytes')
def handle_video_bytes(data):
    emit('video_frame_bytes', data, broadcast=True, include_self=False)

# Base64 fallback — kept so an older client can still connect.
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
# data = {pcm: base64, rate: int, channels: int}
# Just relay it — no decoding, no storage.
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
