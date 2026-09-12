import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from livekit import api

app = Flask(__name__)
CORS(app)

# --- LiveKit Cloud credentials (from your dashboard) ---
LIVEKIT_API_KEY    = "APIZkEpnCrb6My7"
LIVEKIT_API_SECRET = "dBGWZuXfUvo864aQ4Horon1edtNUBFB6xL6xsvW48qm"
LIVEKIT_URL        = "wss://bini-w60p6ccw.livekit.cloud"

# Single shared room for now. Everyone who connects joins this room.
ROOM_NAME = "proctor-room"


@app.route('/token', methods=['POST'])
def get_token():
    """Issue a LiveKit JWT for the identity provided in the request body."""
    data = request.get_json() or {}
    identity = data.get('identity', 'viewer')

    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(api.VideoGrants(
            room_join=True,
            room=ROOM_NAME,
            can_publish=True,
            can_subscribe=True,
        ))
        .with_ttl(datetime.timedelta(hours=6))
        .to_jwt()
    )

    return jsonify({
        'token': token,
        'url': LIVEKIT_URL,
    })


@app.route('/healthz')
def healthz():
    return "ok", 200


if __name__ == '__main__':
    print("Token server running on http://0.0.0.0:5001")
    print(f"Room: {ROOM_NAME}")
    print(f"LiveKit URL: {LIVEKIT_URL}")
    app.run(host='0.0.0.0', port=5001)
