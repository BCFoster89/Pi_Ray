# servo.py
"""Camera tilt servo controller — GPIO 14, hardware PWM, 50 Hz."""
import threading
import RPi.GPIO as GPIO
from logger import log

SERVO_PIN    = 14    # GPIO BCM pin — servo signal wire
SERVO_FREQ   = 50    # Hz — standard hobby servo
SERVO_CENTER = 7.5   # Duty % → ~1.5 ms pulse → neutral/center tilt
SERVO_RANGE  = 1.5   # Max duty % offset → ±1.0 input ≈ ±27° from center

_pwm  = None
_lock = threading.Lock()
_tilt = 0.0   # last commanded value (-1.0 to +1.0)


def init():
    """Initialize the servo PWM. Called once at server startup."""
    global _pwm
    try:
        GPIO.setup(SERVO_PIN, GPIO.OUT)
        _pwm = GPIO.PWM(SERVO_PIN, SERVO_FREQ)
        _pwm.start(SERVO_CENTER)
        log(f"[SERVO] Camera tilt on GPIO {SERVO_PIN} ({SERVO_FREQ} Hz)")
    except Exception as e:
        log(f"[SERVO] Init failed: {e}")
        _pwm = None


def set_tilt(value: float):
    """
    Set camera tilt position.
    value: -1.0 = full up, 0.0 = center, +1.0 = full down
    """
    global _tilt
    if _pwm is None:
        return
    value = max(-1.0, min(1.0, float(value)))
    duty = SERVO_CENTER + value * SERVO_RANGE
    with _lock:
        _pwm.ChangeDutyCycle(duty)
        _tilt = value


def center():
    """Return servo to neutral/center position."""
    set_tilt(0.0)


def get_tilt() -> float:
    """Return last commanded tilt value."""
    return _tilt


def cleanup():
    """Stop PWM on shutdown."""
    global _pwm
    if _pwm is not None:
        center()
        _pwm.stop()
        _pwm = None
