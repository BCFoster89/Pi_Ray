# camera_module.py
import io, time, os, threading
from datetime import datetime
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from logger import log
from config import sensor_data

picam2 = None
camera_lock = threading.Lock()

# Recording state
recording = False
recording_start_time = None
current_recording_file = None
encoder = None
output = None

# Directories for saved files
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), 'recordings')
IMAGES_DIR = os.path.join(os.path.dirname(__file__), 'images')

# Ensure directories exist
os.makedirs(RECORDINGS_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)

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

def capture_still():
    """
    Capture a high-resolution still image.
    Returns the filename of the saved image.
    """
    global picam2

    with camera_lock:
        try:
            # Get current depth for filename
            depth = sensor_data.get('depth_ft', 0.0)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"ROV_{timestamp}_depth-{depth:.1f}ft.jpg"
            filepath = os.path.join(IMAGES_DIR, filename)

            # Stop current camera config
            if picam2 is not None:
                picam2.stop()

                # Configure for max resolution still capture
                # Pi Camera Module v3 max: 4608 x 2592
                still_config = picam2.create_still_configuration(
                    main={"size": (4608, 2592)},
                )
                picam2.configure(still_config)
                picam2.start()
                time.sleep(0.5)  # Allow camera to adjust

                # Capture the image
                picam2.capture_file(filepath)
                log(f"[CAM] Still captured: {filename}")

                # Reconfigure back to video mode
                picam2.stop()
                vc = picam2.create_video_configuration(
                    main={"size": (1280, 720)},
                    controls={"FrameRate": 30}
                )
                picam2.configure(vc)
                picam2.start()

                return filename
            else:
                log("[CAM] Camera not initialized for still capture")
                return None

        except Exception as e:
            log(f"[CAM] Still capture error: {e}")
            # Try to recover video mode
            try:
                if picam2 is not None:
                    picam2.stop()
                    vc = picam2.create_video_configuration(
                        main={"size": (1280, 720)},
                        controls={"FrameRate": 30}
                    )
                    picam2.configure(vc)
                    picam2.start()
            except:
                pass
            return None

def start_recording():
    """
    Start recording video with telemetry overlay.
    Returns the filename being recorded to.
    """
    global recording, recording_start_time, current_recording_file, encoder, output, picam2

    with camera_lock:
        if recording:
            return current_recording_file  # Already recording

        try:
            cam = init_camera()

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"ROV_{timestamp}.mp4"
            filepath = os.path.join(RECORDINGS_DIR, filename)

            # Create H264 encoder and output
            encoder = H264Encoder(bitrate=10000000)  # 10 Mbps for good quality
            output = FfmpegOutput(filepath)

            # Start recording
            cam.start_encoder(encoder, output)

            recording = True
            recording_start_time = time.time()
            current_recording_file = filename

            log(f"[CAM] Recording started: {filename}")
            return filename

        except Exception as e:
            log(f"[CAM] Failed to start recording: {e}")
            recording = False
            return None

def stop_recording():
    """
    Stop the current recording.
    Returns the filename of the completed recording.
    """
    global recording, recording_start_time, current_recording_file, encoder, output, picam2

    with camera_lock:
        if not recording:
            return None

        try:
            if picam2 is not None and encoder is not None:
                picam2.stop_encoder()

            filename = current_recording_file
            duration = time.time() - recording_start_time if recording_start_time else 0

            recording = False
            recording_start_time = None
            current_recording_file = None
            encoder = None
            output = None

            log(f"[CAM] Recording stopped: {filename} ({duration:.1f}s)")
            return filename

        except Exception as e:
            log(f"[CAM] Failed to stop recording: {e}")
            recording = False
            return None

def get_recording_status():
    """Return current recording status."""
    elapsed = 0
    if recording and recording_start_time:
        elapsed = time.time() - recording_start_time

    return {
        "recording": recording,
        "filename": current_recording_file,
        "elapsed_seconds": round(elapsed, 1)
    }

def list_recordings():
    """List all recorded video files."""
    try:
        files = os.listdir(RECORDINGS_DIR)
        return sorted([f for f in files if f.endswith('.mp4')], reverse=True)
    except:
        return []

def list_images():
    """List all captured image files."""
    try:
        files = os.listdir(IMAGES_DIR)
        return sorted([f for f in files if f.endswith('.jpg')], reverse=True)
    except:
        return []
