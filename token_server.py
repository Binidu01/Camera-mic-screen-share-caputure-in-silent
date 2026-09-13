import os
import datetime
import asyncio
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from livekit import api

app = Flask(__name__)
CORS(app)

LIVEKIT_API_KEY    = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
LIVEKIT_URL        = os.environ["LIVEKIT_URL"]

# LiveKit HTTP API URL (https:// instead of wss://) for server-side queries
LIVEKIT_HTTP_URL = LIVEKIT_URL.replace('wss://', 'https://').replace('ws://', 'http://')

# Default room name — only used if the client doesn't supply one
DEFAULT_ROOM = "proctor-room"


@app.route('/')
def index():
    """Serve the viewer HTML from templates/index.html."""
    return render_template('index.html')


@app.route('/healthz')
def healthz():
    return "ok", 200


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


@app.route('/rooms', methods=['GET'])
def list_rooms():
    """
    Return the list of currently-active LiveKit rooms.
    Only rooms with at least one participant are returned by default.
    """
    try:
        client = api.LiveKitAPI(
            url=LIVEKIT_HTTP_URL,
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET,
        )

        async def _fetch():
            try:
                resp = await client.room.list_rooms(api.ListRoomsRequest())
                return resp.rooms
            finally:
                await client.aclose()

        rooms = asyncio.run(_fetch())

        result = []
        for r in rooms:
            result.append({
                'name': r.name,
                'num_participants': r.num_participants,
                'creation_time': r.creation_time,
            })

        return jsonify({'rooms': result})

    except Exception as e:
        print("list_rooms failed:", e)
        return jsonify({'rooms': [], 'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
