import os
import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from livekit import api

app = Flask(__name__)
CORS(app)

# Read credentials from environment variables (set in Render dashboard)
LIVEKIT_API_KEY    = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
LIVEKIT_URL        = os.environ["LIVEKIT_URL"]

ROOM_NAME = "proctor-room"


@app.route('/token', methods=['POST'])
def get_token():
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

    return jsonify({'token': token, 'url': LIVEKIT_URL})


@app.route('/healthz')
def healthz():
    return "ok", 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
