# 🛡️ Online Exam Proctoring System

A real-time, browser-based exam monitoring tool using Python, Flask, and Socket.IO. This project enables instructors to remotely monitor students during online exams by capturing live webcam video, screen activity, and audio streams.

## 🎯 Features

- 📷 **Live Webcam Feed** – Monitor the student’s surroundings.
- 🖥️ **Live Screen Sharing** – View the student’s screen activity in real time.
- 🎙️ **Microphone Streaming** – Listen to background noise or speech.
- 🌐 **IP Address Tracking** – Detect and display the client’s IP address.
- 💾 **Audio Save Option** – Save recorded microphone audio for review.

## 🧩 Technologies Used

- **Backend:** Python, Flask, Flask-SocketIO, Eventlet
- **Frontend:** HTML, CSS, JavaScript
- **Client Dependencies:** OpenCV, PyAudio, PyAutoGUI, socketio-client

## 🏗️ Architecture

- `client.py`: Python script run on the student's machine to stream webcam, screen, and microphone.
- `server.py`: Flask server to receive and broadcast real-time data to the admin dashboard.
- `templates/index.html`: The admin dashboard that displays live feeds and controls.

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/proctoring-system.git
cd proctoring-system

2. Install server dependencies
pip install flask flask-socketio eventlet requests

3. Install client dependencies
pip install opencv-python pyautogui pyaudio python-socketio

4. Run the server
python server.py

5. Run the client (on student's machine)
python client.py

🌐 Deployment
You can deploy the server to a free hosting service like:

Render

Replit

Railway

⚠️ Disclaimer
This system is built for educational and ethical use only, such as classroom demonstrations in cybersecurity or online assessment environments with student and parental consent. Unauthorized use may violate laws and institutional policies.