import os
import asyncio
import threading
import traceback
import datetime

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from livekit import api

app = Flask(__name__)
CORS(app)

# ─────────────── CONFIG ───────────────
LIVEKIT_API_KEY    = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
LIVEKIT_URL        = os.environ["LIVEKIT_URL"]

# The admin HTTP API needs https://, not wss://
LIVEKIT_HTTP_URL = LIVEKIT_URL.replace('wss://', 'https://').replace('ws://', 'http://')

DEFAULT_ROOM = "proctor-room"


# ─────────────── PAGES ───────────────
@app.route('/')
def index():
    """Serve the viewer HTML from templates/index.html."""
    return render_template('index.html')


@app.route('/healthz')
def healthz():
    return "ok", 200


# ─────────────── TOKEN ───────────────
@app.route('/token', methods=['POST'])
def get_token():
    """
    Issue a LiveKit JWT.
    Body: { "identity": "proctor-abc123", "room": "student-DESKTOP-xyz" }
    Both fields are optional; sensible defaults are used if missing.
    """
    data = request.get_json() or {}
    identity = data.get('identity', 'viewer')
    room     = data.get('room', DEFAULT_ROOM)

    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room,
            can_publish=True,
            can_subscribe=True,
        ))
        .with_ttl(datetime.timedelta(hours=6))
        .to_jwt()
    )

    return jsonify({'token': token, 'url': LIVEKIT_URL})


# ─────────────── ROOMS ───────────────
async def _fetch_rooms_async():
    """Async helper — creates its own LiveKitAPI client."""
    client = api.LiveKitAPI(
        url=LIVEKIT_HTTP_URL,
        api_key=LIVEKIT_API_KEY,
        api_secret=LIVEKIT_API_SECRET,
    )
    try:
        resp = await client.room.list_rooms(api.ListRoomsRequest())
        return resp.rooms
    finally:
        await client.aclose()


@app.route('/rooms', methods=['GET'])
def list_rooms():
    """
    Return active LiveKit rooms.
    The LiveKit Python SDK is async-only, but Flask under gunicorn/gevent
    has no running event loop. We spin up a fresh event loop in a
    dedicated thread, run the async call there, and join it back.
    """
    result = {}

    def run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result['data'] = loop.run_until_complete(_fetch_rooms_async())
        except Exception as e:
            result['error'] = str(e)
            print("[rooms] exception in thread:")
            traceback.print_exc()
        finally:
            loop.close()

    thread = threading.Thread(target=run_in_thread)
    thread.start()
    thread.join(timeout=15)   # never hang a request forever

    if 'error' in result:
        return jsonify({'rooms': [], 'error': result['error']}), 500

    rooms_raw = result.get('data', [])
    rooms = [{
        'name': r.name,
        'num_participants': r.num_participants,
        'creation_time': r.creation_time,
    } for r in rooms_raw]

    return jsonify({'rooms': rooms})


# ─────────────── MAIN ───────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"LiveKit HTTP URL: {LIVEKIT_HTTP_URL}")
    app.run(host='0.0.0.0', port=port)
