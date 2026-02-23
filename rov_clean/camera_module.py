# camera_module.py
import io, time, os, threading, shutil, subprocess
from datetime import datetime
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from PIL import Image, ImageDraw, ImageFont
from logger import log
from config import sensor_data

picam2 = None
camera_lock = threading.Lock()

# Recording state
recording = False
recording_start_time = None
current_recording_file = None
_recording_thread = None
_recording_stop_event = None

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

# Video resolution - 1080p for streaming, 720p for overlay recording (Pi3 performance)
VIDEO_SIZE = (1920, 1080)
RECORD_SIZE = (1280, 720)  # Lower res for overlay recording - better Pi3 performance
VIDEO_BITRATE = 8000000  # 8 Mbps
RECORD_FPS = 24  # Target FPS for overlay recording

# Load font once at module level
_font = None
_font_small = None
_font_large = None

def _get_fonts():
    """Load fonts lazily."""
    global _font, _font_small, _font_large
    if _font is None:
        try:
            _font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 20)
            _font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 16)
            _font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 28)
        except:
            _font = ImageFont.load_default()
            _font_small = _font
            _font_large = _font
    return _font, _font_small, _font_large

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

def draw_hud_overlay(img, rec_duration=None):
    """
    Draw HUD overlay on a PIL Image.
    Includes: telemetry bar, recording indicator, leak warning.
    """
    font, font_small, font_large = _get_fonts()
    w, h = img.size

    # Get current sensor data
    depth = sensor_data.get('depth_ft', 0.0)
    pitch = sensor_data.get('pitch', 0.0)
    roll = sensor_data.get('roll', 0.0)
    heading = sensor_data.get('yaw', 0.0)
    temp = sensor_data.get('temperature_f', 0.0)
    leak = sensor_data.get('leak_detected', False)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # === TELEMETRY BAR (bottom) ===
    bar_height = 35
    bar_y = h - bar_height

    # Semi-transparent background bar
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle([(0, bar_y), (w, h)], fill=(0, 0, 0, 160))
    img.paste(Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB'))

    draw = ImageDraw.Draw(img)

    telem = f"Depth: {depth:.1f}ft | Pitch: {pitch:.1f}° | Roll: {roll:.1f}° | HDG: {heading:.0f}° | Temp: {temp:.1f}°F | {timestamp}"
    bbox = draw.textbbox((0, 0), telem, font=font)
    text_w = bbox[2] - bbox[0]
    draw.text(((w - text_w) // 2, bar_y + 8), telem, font=font, fill=(255, 255, 255, 255))

    # === RECORDING INDICATOR (top left) ===
    if rec_duration is not None:
        mins = int(rec_duration // 60)
        secs = int(rec_duration % 60)
        draw.ellipse([20, 20, 35, 35], fill=(255, 0, 0, 255))
        draw.text((45, 18), f"REC {mins:02d}:{secs:02d}", font=font, fill=(255, 50, 50, 255))

    # === LEAK WARNING (top right) ===
    if leak:
        draw.rectangle([w - 150, 15, w - 10, 45], fill=(255, 0, 0, 200))
        draw.text((w - 145, 18), "LEAK!", font=font, fill=(255, 255, 255, 255))

    return img

def generate_frames():
    """Generator that yields JPEG frames from the Picamera2.

    Uses capture_array() for better performance instead of capture_file().
    Target: 30 FPS streaming.
    """
    cam = init_camera()

    # Track frame timing for performance monitoring
    last_frame_time = time.time()
    frame_count = 0
    fps_log_interval = 100  # Log FPS every 100 frames

    while True:
        try:
            # Use capture_array for faster frame capture (no disk I/O)
            frame_array = cam.capture_array()

            # Convert numpy array to JPEG bytes using PIL (faster than file I/O)
            # capture_array() returns RGBA; convert to RGB for JPEG compatibility
            img = Image.fromarray(frame_array).convert('RGB')

            # Encode to JPEG with reasonable quality (lower = faster, smaller)
            stream = io.BytesIO()
            img.save(stream, format='JPEG', quality=80)
            frame = stream.getvalue()

            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

            # Track FPS
            frame_count += 1
            if frame_count >= fps_log_interval:
                elapsed = time.time() - last_frame_time
                fps = frame_count / elapsed if elapsed > 0 else 0
                if fps < 20:  # Only log if FPS is low
                    log(f"[CAM] Stream FPS: {fps:.1f}")
                last_frame_time = time.time()
                frame_count = 0

        except Exception as e:
            log(f"[CAM] capture error: {e}")
            time.sleep(0.5)  # Brief pause on error before retry

def add_telemetry_overlay(filepath):
    """Add full HUD overlay to a captured image."""
    try:
        img = Image.open(filepath).convert('RGB')
        img = draw_hud_overlay(img, rec_duration=None)
        img.save(filepath, 'JPEG', quality=95)
        log(f"[CAM] HUD overlay added to image")
    except Exception as e:
        log(f"[CAM] Failed to add overlay: {e}")

def capture_still():
    """
    Capture a high-resolution still image with telemetry overlay.
    Uses current video stream frame to avoid blocking video.
    Returns the filename of the saved image.
    """
    global picam2

    # Generate filename outside lock
    depth = sensor_data.get('depth_ft', 0.0)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"ROV_{timestamp}_depth-{depth:.1f}ft.jpg"
    filepath = os.path.join(IMAGES_DIR, filename)

    # Quick capture from current stream (minimal lock time)
    with camera_lock:
        if picam2 is None:
            log("[CAM] Camera not initialized for still capture")
            return None
        try:
            # Capture from current video stream - no reconfiguration needed
            # This gives 1920x1080 instead of full 4608x2592 but doesn't block
            frame_array = picam2.capture_array()
        except Exception as e:
            log(f"[CAM] Still capture error: {e}")
            return None

    # All processing OUTSIDE lock to not block video stream
    try:
        img = Image.fromarray(frame_array).convert('RGB')
        img.save(filepath, 'JPEG', quality=95)
        log(f"[CAM] Still captured: {filename}")

        # Add telemetry overlay (also outside lock)
        add_telemetry_overlay(filepath)
        return filename

    except Exception as e:
        log(f"[CAM] Still save error: {e}")
        return None

def _recording_loop(filepath, stop_event, start_time):
    """
    Background thread: capture frames, draw HUD overlay, pipe to ffmpeg.
    Runs until stop_event is set.
    """
    global picam2

    try:
        # Start ffmpeg process to receive frames via pipe
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo',
            '-pix_fmt', 'rgb24',
            '-s', f'{RECORD_SIZE[0]}x{RECORD_SIZE[1]}',
            '-r', str(RECORD_FPS),
            '-i', 'pipe:0',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',  # Fast encoding for Pi3
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            filepath
        ]

        ffmpeg = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )

        frame_interval = 1.0 / RECORD_FPS
        last_frame_time = time.time()
        frames_written = 0

        while not stop_event.is_set():
            try:
                # Throttle to target FPS
                now = time.time()
                elapsed_since_last = now - last_frame_time
                if elapsed_since_last < frame_interval:
                    time.sleep(frame_interval - elapsed_since_last)

                last_frame_time = time.time()
                rec_duration = last_frame_time - start_time

                # Capture frame
                with camera_lock:
                    if picam2 is None:
                        continue
                    frame_array = picam2.capture_array()

                # Convert and resize for recording
                img = Image.fromarray(frame_array).convert('RGB')
                img = img.resize(RECORD_SIZE, Image.BILINEAR)

                # Draw HUD overlay
                img = draw_hud_overlay(img, rec_duration=rec_duration)

                # Write to ffmpeg
                ffmpeg.stdin.write(img.tobytes())
                frames_written += 1

            except Exception as e:
                if not stop_event.is_set():
                    log(f"[CAM] Recording frame error: {e}")
                break

        # Finalize
        if ffmpeg.stdin:
            ffmpeg.stdin.close()
        ffmpeg.wait(timeout=30)

        log(f"[CAM] Recording complete: {frames_written} frames written")

    except Exception as e:
        log(f"[CAM] Recording thread error: {e}")

def start_recording():
    """
    Start recording video with HUD overlay burned in.
    Captures frames in background thread, draws overlay, pipes to ffmpeg.
    Returns the filename being recorded to.
    """
    global recording, recording_start_time, current_recording_file, _recording_thread, _recording_stop_event

    if not FFMPEG_AVAILABLE:
        log("[CAM] Cannot record - ffmpeg not installed")
        return None

    if recording:
        return current_recording_file

    try:
        init_camera()  # Ensure camera is initialized

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"ROV_{timestamp}.mp4"
        filepath = os.path.join(RECORDINGS_DIR, filename)

        recording_start_time = time.time()
        current_recording_file = filename

        # Create stop event and start recording thread
        _recording_stop_event = threading.Event()
        _recording_thread = threading.Thread(
            target=_recording_loop,
            args=(filepath, _recording_stop_event, recording_start_time),
            daemon=True
        )
        _recording_thread.start()

        recording = True
        log(f"[CAM] Recording started: {filename} ({RECORD_SIZE[0]}x{RECORD_SIZE[1]} @ {RECORD_FPS}fps with HUD)")
        return filename

    except Exception as e:
        log(f"[CAM] Failed to start recording: {e}")
        recording = False
        return None

def stop_recording():
    """
    Stop the current recording.
    Signals background thread to stop and waits for ffmpeg to finalize.
    Returns the filename of the completed recording.
    """
    global recording, recording_start_time, current_recording_file, _recording_thread, _recording_stop_event

    if not recording:
        return None

    filename = current_recording_file
    filepath = os.path.join(RECORDINGS_DIR, filename) if filename else None
    duration = time.time() - recording_start_time if recording_start_time else 0

    # Signal thread to stop
    if _recording_stop_event:
        _recording_stop_event.set()

    # Wait for thread to finish
    if _recording_thread and _recording_thread.is_alive():
        _recording_thread.join(timeout=10)

    recording = False
    recording_start_time = None
    current_recording_file = None
    _recording_thread = None
    _recording_stop_event = None

    # Verify file
    if filepath and os.path.exists(filepath):
        file_size = os.path.getsize(filepath)
        log(f"[CAM] Recording saved: {filename} ({duration:.1f}s, {file_size/1024/1024:.1f}MB)")
    else:
        log(f"[CAM] WARNING: Recording file not found: {filename}")

    return filename

def get_recording_status():
    """Return current recording status (thread-safe)."""
    with camera_lock:
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
