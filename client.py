import asyncio
import base64
import queue
import signal
import sys
import threading
import time

import cv2
import mss
import numpy as np
import requests
import sounddevice as sd
from livekit import rtc

# --- CONFIG ---
TOKEN_URL = 'https://camera-mic-screen-share-caputure-in.onrender.com/token'
DEBUG_TIMING = False   # set True to re-enable per-frame timing logs

# Global shutdown flag
STOP = threading.Event()

# Shared resources for shutdown
_cap = None
_audio_stream = None
_room = None


def log(msg):
    if DEBUG_TIMING:
        print(msg, flush=True)


# ─────────────────────────────────────────────────────────────
#  TOKEN
# ─────────────────────────────────────────────────────────────
def get_livekit_credentials(identity):
    """Fetch a LiveKit JWT + URL from the Render token server."""
    resp = requests.post(
        TOKEN_URL,
        json={'identity': identity},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────
#  WEBCAM  —  publishes a video track to LiveKit
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
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

    # Warm up — first frame from DSHOW is slow
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
    await room.local_participant.publish_track(track, options)
    print("Webcam track published")

    TARGET_FPS = 10
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
#  SCREEN  —  publishes a video track to LiveKit
# ─────────────────────────────────────────────────────────────
def _make_mss():
    if hasattr(mss, 'MSS'):
        return mss.MSS()
    return mss.mss()


async def publish_screen(room):
    TARGET_FPS = 4
    FRAME_TIME = 1.0 / TARGET_FPS

    with _make_mss() as sct:
        monitor = sct.monitors[1]

        # Grab one frame to learn dimensions
        shot = await asyncio.to_thread(sct.grab, monitor)
        frame = np.array(shot)[:, :, :3]
        small = cv2.resize(frame, (480, 270))
        height, width, _ = small.shape
        print(f"Screen resolution: {width}x{height}")

        # is_screencast=True tells LiveKit to optimize for screen content
        source = rtc.VideoSource(width, height, is_screencast=True)
        track = rtc.LocalVideoTrack.create_video_track("screen", source)
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_SCREENSHARE
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
#  AUDIO  —  publishes an audio track to LiveKit
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
            # Drop-newest: discard the incoming chunk, keep queued audio.
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

    # Create the LiveKit audio source
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

        samples = chunk.flatten()  # 1D int16 array
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

    # Disconnect room
    try:
        if _room is not None and _room.is_connected:
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
_loop = None   # set in main() so shutdown() can schedule disconnect


async def run_publisher():
    global _room

    creds = get_livekit_credentials('publisher')
    print(f"Got token, connecting to {creds['url']}")

    room = rtc.Room()
    _room = room

    await room.connect(creds['url'], creds['token'])
    print(f"Connected to LiveKit room: {room.name}")

    # Publish all three tracks concurrently
    await asyncio.gather(
        publish_webcam(room),
        publish_screen(room),
        publish_audio(room),
    )

    # Clean disconnect when all publishers finish
    try:
        await room.disconnect()
        print("LiveKit disconnected")
    except Exception:
        pass


def main():
    global _loop

    install_signal_handlers()

    print("Starting LiveKit publisher…")
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
