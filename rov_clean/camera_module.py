# camera_module.py
import io, time, os, threading, shutil
from datetime import datetime
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from PIL import Image, ImageDraw, ImageFont
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

# Check for ffmpeg at startup
FFMPEG_AVAILABLE = shutil.which('ffmpeg') is not None
if FFMPEG_AVAILABLE:
    log("[CAM] ffmpeg found - video recording available")
else:
    log("[CAM] WARNING: ffmpeg not found - install with: sudo apt install ffmpeg")

# Video resolution - 1080p
VIDEO_SIZE = (1920, 1080)
VIDEO_BITRATE = 15000000  # 15 Mbps for 1080p

def init_camera():
    """Initialize the Picamera2 instance lazily and return it."""
    global picam2
    if picam2 is None:
        try:
            picam2 = Picamera2()
            vc = picam2.create_video_configuration(
                main={"size": VIDEO_SIZE},
                controls={"FrameRate": 30}
            )
            picam2.configure(vc)
            picam2.start()
            # Enable continuous autofocus for Pi Camera v3
            try:
                picam2.set_controls({"AfMode": 2, "AfSpeed": 1})
                log("[CAM] Autofocus enabled")
            except Exception:
                pass  # Camera may not support AF
            log(f"[CAM] Picamera2 initialized at {VIDEO_SIZE[0]}x{VIDEO_SIZE[1]}")
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

def add_telemetry_overlay(filepath):
    """Add telemetry text overlay to a captured image using Pillow."""
    try:
        img = Image.open(filepath)
        draw = ImageDraw.Draw(img)

        # Get current sensor data
        depth = sensor_data.get('depth_ft', 0.0)
        pitch = sensor_data.get('pitch', 0.0)
        roll = sensor_data.get('roll', 0.0)
        heading = sensor_data.get('yaw', 0.0)
        water_temp = sensor_data.get('temperature_f', 0.0)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Format telemetry string
        telemetry_text = (
            f"Depth: {depth:.1f} ft  |  Pitch: {pitch:.1f}°  |  Roll: {roll:.1f}°  |  "
            f"Heading: {heading:.0f}°  |  Water: {water_temp:.1f}°F  |  {timestamp}"
        )

        # Try to use a monospace font, fall back to default
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 36)
        except:
            font = ImageFont.load_default()

        # Calculate text size and position
        bbox = draw.textbbox((0, 0), telemetry_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        img_width, img_height = img.size
        bar_height = text_height + 20
        bar_y = img_height - bar_height

        # Draw semi-transparent black bar at bottom
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle(
            [(0, bar_y), (img_width, img_height)],
            fill=(0, 0, 0, 180)
        )

        # Composite the overlay
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        img = Image.alpha_composite(img, overlay)

        # Draw text
        draw = ImageDraw.Draw(img)
        text_x = (img_width - text_width) // 2
        text_y = bar_y + 10
        draw.text((text_x, text_y), telemetry_text, font=font, fill=(255, 255, 255, 255))

        # Convert back to RGB for JPEG save
        img = img.convert('RGB')
        img.save(filepath, 'JPEG', quality=95)
        log(f"[CAM] Telemetry overlay added to image")

    except Exception as e:
        log(f"[CAM] Failed to add telemetry overlay: {e}")

def capture_still():
    """
    Capture a high-resolution still image with telemetry overlay.
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

                # Add telemetry overlay
                add_telemetry_overlay(filepath)

                # Reconfigure back to video mode
                picam2.stop()
                vc = picam2.create_video_configuration(
                    main={"size": VIDEO_SIZE},
                    controls={"FrameRate": 30}
                )
                picam2.configure(vc)
                picam2.start()
                # Re-enable autofocus
                try:
                    picam2.set_controls({"AfMode": 2, "AfSpeed": 1})
                except:
                    pass

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
                        main={"size": VIDEO_SIZE},
                        controls={"FrameRate": 30}
                    )
                    picam2.configure(vc)
                    picam2.start()
            except:
                pass
            return None

def start_recording():
    """
    Start recording video.
    Returns the filename being recorded to.
    """
    global recording, recording_start_time, current_recording_file, encoder, output, picam2

    if not FFMPEG_AVAILABLE:
        log("[CAM] Cannot record - ffmpeg not installed")
        return None

    with camera_lock:
        if recording:
            return current_recording_file  # Already recording

        try:
            cam = init_camera()

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"ROV_{timestamp}.mp4"
            filepath = os.path.join(RECORDINGS_DIR, filename)

            # Create H264 encoder and output
            encoder = H264Encoder(bitrate=VIDEO_BITRATE)
            output = FfmpegOutput(filepath)

            # Start recording
            cam.start_encoder(encoder, output)

            recording = True
            recording_start_time = time.time()
            current_recording_file = filename

            log(f"[CAM] Recording started: {filename} ({VIDEO_SIZE[0]}x{VIDEO_SIZE[1]} @ {VIDEO_BITRATE//1000000}Mbps)")
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
            filepath = os.path.join(RECORDINGS_DIR, filename) if filename else None
            duration = time.time() - recording_start_time if recording_start_time else 0

            recording = False
            recording_start_time = None
            current_recording_file = None
            encoder = None
            output = None

            # Verify file was saved
            if filepath and os.path.exists(filepath):
                file_size = os.path.getsize(filepath)
                log(f"[CAM] Recording stopped: {filename} ({duration:.1f}s, {file_size/1024/1024:.1f}MB)")
            else:
                log(f"[CAM] WARNING: Recording file not found after stop: {filename}")

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
        "elapsed_seconds": round(elapsed, 1),
        "ffmpeg_available": FFMPEG_AVAILABLE
    }

def list_recordings():
    """List all recorded video files with sizes."""
    try:
        files = []
        for f in os.listdir(RECORDINGS_DIR):
            if f.endswith('.mp4'):
                filepath = os.path.join(RECORDINGS_DIR, f)
                size_mb = os.path.getsize(filepath) / 1024 / 1024
                files.append({"name": f, "size_mb": round(size_mb, 1)})
        return sorted(files, key=lambda x: x['name'], reverse=True)
    except:
        return []

def list_images():
    """List all captured image files."""
    try:
        files = os.listdir(IMAGES_DIR)
        return sorted([f for f in files if f.endswith('.jpg')], reverse=True)
    except:
        return []
