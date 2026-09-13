import asyncio
import os
import pathlib
import platform
import queue
import re
import signal
import socket
import sys
import threading
import time
import uuid

import cv2
import mss
import numpy as np
import requests
import sounddevice as sd
from livekit import rtc

# --- CONFIG ---
TOKEN_URL = 'https://camera-mic-screen-share-caputure-in.onrender.com/token'
DEBUG_TIMING = False


# ─────────────────────────────────────────────────────────────
#  STUDENT IDENTITY  —  persisted to disk so restarts reuse it
# ─────────────────────────────────────────────────────────────
def make_student_id():
    """
    Deterministic ID persisted to disk so restarts never create a
    new room. Format: <hostname>-<short-hash>
    """
    # Where to remember our ID (survives restarts)
    try:
        home = pathlib.Path.home()
    except Exception:
        home = pathlib.Path(os.getcwd())
    cache_file = home / '.livekit_student_id'

    # Reuse saved ID if present
    if cache_file.exists():
        try:
            saved = cache_file.read_text().strip()
            if saved:
                return saved
        except Exception:
            pass

    # Generate a fresh one
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = platform.node() or 'unknown'

    hostname = re.sub(r'[^A-Za-z0-9-]', '-', hostname).strip('-')
    if not hostname:
        hostname = 'pc'

    try:
        mac = uuid.getnode()
    except Exception:
        mac = 0
    h = format(abs(hash(f"{hostname}-{mac}")) % (16**6), '06x')

    new_id = f"{hostname}-{h}"

    # Persist for next run
    try:
        cache_file.write_text(new_id)
        print(f"Generated new student ID (saved to {cache_file}): {new_id}")
    except Exception as e:
        print(f"Warning: couldn't save student ID to {cache_file}: {e}")

    return new_id


STUDENT_ID = os.environ.get('STUDENT_NAME') or make_student_id()
ROOM_NAME  = f"student-{STUDENT_ID}"
IDENTITY   = f"publisher-{STUDENT_ID}"

STOP = threading.Event()

_cap = None
_audio_stream = None
_room = None
_loop = None


def log(msg):
    if DEBUG_TIMING:
        print(msg, flush=True)


# ─────────────────────────────────────────────────────────────
#  TOKEN
# ─────────────────────────────────────────────────────────────
def get_livekit_credentials(identity, room):
    resp = requests.post(
        TOKEN_URL,
        json={'identity': identity, 'room': room},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────
#  WEBCAM
# ─────────────────────────────────────────────────────────────
def open_webcam():
    backends = []
    if sys.platform.startswith('win'):
        backends.append(cv2.CAP_DSHOW)
    elif sys.platform.startswith('linux'):
        backends.append(cv2.CAP_V4L2)
    backends.append(cv2.CAP_ANY)

    for be in backends:
        cap = cv2.VideoCapture(0, be)
        if cap.isOpened():
            print(f"Webcam opened with backend {be}")
            return cap
        cap.release()
    return None


async def publish_webcam(room):
    global _cap
    cap = open_webcam()
    if cap is None:
        print("Webcam not accessible")
        return
    _cap = cap

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    ret, frame = await asyncio.to_thread(cap.read)
    if not ret:
        print("Webcam first-frame read failed")
        cap.release()
        return
    height, width, _ = frame.shape
    print(f"Webcam resolution: {width}x{height}")

    source = rtc.VideoSource(width, height)
    track = rtc.LocalVideoTrack.create_video_track("webcam", source)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_CAMERA
    options.video_encoding.max_bitrate = 1_200_000
    options.video_encoding.max_framerate = 15
    await room.local_participant.publish_track(track, options)
    print("Webcam track published")

    TARGET_FPS = 15
    FRAME_TIME = 1.0 / TARGET_FPS

    while not STOP.is_set():
        t0 = time.time()

        ret, frame = await asyncio.to_thread(cap.read)
        t_read = time.time()
        if not ret:
            await asyncio.sleep(0.02)
            continue

        rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        t_conv = time.time()

        video_frame = rtc.VideoFrame(
            width, height,
            rtc.VideoBufferType.RGBA,
            rgba.tobytes(),
        )
        source.capture_frame(video_frame)
        t_capture = time.time()

        if DEBUG_TIMING:
            log(f"[cam]  read={(t_read - t0)*1000:5.1f}ms  "
                f"conv={(t_conv - t_read)*1000:5.1f}ms  "
                f"cap={(t_capture - t_conv)*1000:5.1f}ms  "
                f"total={(t_capture - t0)*1000:5.1f}ms")

        elapsed = time.time() - t0
        if elapsed < FRAME_TIME:
            await asyncio.sleep(FRAME_TIME - elapsed)

    try:
        cap.release()
        print("Webcam released")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
#  SCREEN  —  full HD, high bitrate, screen-optimized
# ─────────────────────────────────────────────────────────────
def _make_mss():
    if hasattr(mss, 'MSS'):
        return mss.MSS()
    return mss.mss()


async def publish_screen(room):
    TARGET_FPS = 8
    FRAME_TIME = 1.0 / TARGET_FPS
    TARGET_W, TARGET_H = 1920, 1080

    with _make_mss() as sct:
        monitor = sct.monitors[1]

        shot = await asyncio.to_thread(sct.grab, monitor)
        frame = np.array(shot)[:, :, :3]
        small = cv2.resize(frame, (TARGET_W, TARGET_H))
        height, width, _ = small.shape
        print(f"Screen resolution: {width}x{height}")

        source = rtc.VideoSource(width, height, is_screencast=True)
        track = rtc.LocalVideoTrack.create_video_track("screen", source)
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_SCREENSHARE
        options.video_encoding.max_bitrate = 6_000_000
        options.video_encoding.max_framerate = TARGET_FPS
        await room.local_participant.publish_track(track, options)
        print("Screen track published")

        while not STOP.is_set():
            t0 = time.time()

            try:
                shot = await asyncio.to_thread(sct.grab, monitor)
                t_grab = time.time()

                frame = np.array(shot)[:, :, :3]
                small = cv2.resize(frame, (width, height))
                rgba = cv2.cvtColor(small, cv2.COLOR_BGR2RGBA)
                t_conv = time.time()

                video_frame = rtc.VideoFrame(
                    width, height,
                    rtc.VideoBufferType.RGBA,
                    rgba.tobytes(),
                )
                source.capture_frame(video_frame)
                t_capture = time.time()

                if DEBUG_TIMING:
                    log(f"[scr]  grab={(t_grab - t0)*1000:5.1f}ms  "
                        f"conv={(t_conv - t_grab)*1000:5.1f}ms  "
                        f"cap={(t_capture - t_conv)*1000:5.1f}ms  "
                        f"total={(t_capture - t0)*1000:5.1f}ms")
            except Exception as e:
                if not STOP.is_set():
                    print("Screen error:", e)

            elapsed = time.time() - t0
            if elapsed < FRAME_TIME:
                await asyncio.sleep(FRAME_TIME - elapsed)

    print("Screen capture stopped")


# ─────────────────────────────────────────────────────────────
#  AUDIO
# ─────────────────────────────────────────────────────────────
audio_q = queue.Queue(maxsize=4)


async def publish_audio(room):
    global _audio_stream
    CH, FR, CHUNK = 1, 48000, 1920   # mono, 48 kHz, 40 ms

    stats_lock = threading.Lock()
    stats = {'sent': 0, 'dropped': 0}
    last_stats_t = time.time()

    def callback(indata, frames, time_info, status):
        if status and not STOP.is_set():
            print("Audio status:", status)
        if STOP.is_set():
            return
        try:
            audio_q.put_nowait(indata.copy())
        except queue.Full:
            with stats_lock:
                stats['dropped'] += 1

    try:
        stream = sd.InputStream(
            channels=CH,
            samplerate=FR,
            blocksize=CHUNK,
            dtype='int16',
            callback=callback,
            latency='low',
        )
        stream.start()
        _audio_stream = stream
        print(f"Audio stream started: {FR} Hz, {CHUNK/FR*1000:.0f} ms chunks")
    except Exception as e:
        print("Mic open failed:", e)
        return

    source = rtc.AudioSource(FR, CH)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_MICROPHONE
    await room.local_participant.publish_track(track, options)
    print("Audio track published")

    while not STOP.is_set():
        try:
            chunk = audio_q.get(timeout=0.2)
        except queue.Empty:
            continue

        samples = chunk.flatten()
        frame = rtc.AudioFrame.create(FR, CH, len(samples))
        np.copyto(np.frombuffer(frame.data, dtype=np.int16), samples)
        await source.capture_frame(frame)

        if DEBUG_TIMING:
            with stats_lock:
                stats['sent'] += 1
                now = time.time()
                if now - last_stats_t >= 2.0:
                    log(f"[aud]  chunks/s={stats['sent']/2:.1f}  "
                        f"q={audio_q.qsize()}  drop={stats['dropped']}")
                    stats['sent'] = 0
                    stats['dropped'] = 0
                    last_stats_t = now

    try:
        stream.stop()
        stream.close()
        print("Audio stream closed")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
#  SHUTDOWN
# ─────────────────────────────────────────────────────────────
def shutdown(signum=None, frame=None):
    if STOP.is_set():
        return
    print("\nShutting down…")
    STOP.set()

    try:
        if _room is not None and _room.is_connected and _loop is not None:
            asyncio.run_coroutine_threadsafe(_room.disconnect(), _loop)
            print("LiveKit disconnect requested")
    except Exception:
        pass

    time.sleep(0.5)


def install_signal_handlers():
    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, shutdown)


# ─────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────
async def run_publisher():
    global _room

    creds = get_livekit_credentials(IDENTITY, ROOM_NAME)
    print(f"Got token, connecting to {creds['url']}")

    room = rtc.Room()
    _room = room

    await room.connect(creds['url'], creds['token'])
    print(f"Connected to LiveKit room: {room.name}")

    await asyncio.gather(
        publish_webcam(room),
        publish_screen(room),
        publish_audio(room),
    )

    try:
        await room.disconnect()
        print("LiveKit disconnected")
    except Exception:
        pass


def main():
    global _loop

    install_signal_handlers()

    print("Starting LiveKit publisher…")
    print(f"Student ID : {STUDENT_ID}")
    print(f"Room       : {ROOM_NAME}")
    print(f"Identity   : {IDENTITY}")

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    try:
        _loop.run_until_complete(run_publisher())
    except KeyboardInterrupt:
        shutdown()
    finally:
        _loop.close()

    print("Goodbye.")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        shutdown()
