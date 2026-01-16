# camera_module.py
import io, time
from picamera2 import Picamera2
from logger import log

picam2 = None

def init_camera():
    """Initialize the Picamera2 instance lazily and return it."""
    global picam2
    if picam2 is None:
        try:
            picam2 = Picamera2()
            vc = picam2.create_video_configuration(
                main={"size": (1280, 720)},
                controls={"FrameRate": 30}
            )
            picam2.configure(vc)
            picam2.start()
            log("[CAM] Picamera2 initialized")
        except Exception as e:
            picam2 = None
            log(f"[CAM] Failed to init camera: {e}")
            raise
    return picam2

def generate_frames():
    """Generator that yields JPEG frames from the Picamera2."""
    cam = init_camera()
    stream = io.BytesIO()
    while True:
        try:
            cam.capture_file(stream, format="jpeg")
            stream.seek(0)
            frame = stream.read()
            stream.seek(0)
            stream.truncate()
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(1 / 30)
        except Exception as e:
            log(f"[CAM] capture error: {e}")
            time.sleep(1)
