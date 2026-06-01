# servo.py
"""Camera tilt servo controller — GPIO 14, pigpio DMA PWM, 50 Hz."""

import time, subprocess
from logger import log

SERVO_PIN = 14
CENTER_US = 1500   # µs — neutral/center tilt (1.5 ms pulse)
RANGE_US  = 300    # µs — ±300 µs from center ≈ ±27° (matches previous range)
MIN_US    = 800    # hard safety floor
MAX_US    = 2200   # hard safety ceiling

_pi   = None   # pigpio.pi() instance
_tilt = 0.0    # last commanded value (-1.0 to +1.0)


def init():
    """Initialize servo via pigpio DMA PWM. Called once at server startup."""
    global _pi, _tilt
    try:
        import pigpio
        _pi = pigpio.pi()
        if not _pi.connected:
            log("[SERVO] pigpiod not running — attempting auto-start")
            subprocess.run(['sudo', 'pigpiod'], capture_output=True)
            time.sleep(0.6)
            _pi = pigpio.pi()
        if _pi.connected:
            _pi.set_servo_pulsewidth(SERVO_PIN, CENTER_US)
            _tilt = 0.0
            log(f"[SERVO] Camera tilt on GPIO {SERVO_PIN} via pigpio DMA")
        else:
            log("[SERVO] pigpio daemon unavailable — servo disabled")
            _pi = None
    except Exception as e:
        log(f"[SERVO] Init failed: {e}")
        _pi = None


def set_tilt(value: float):
    """
    Set camera tilt position.
    value: -1.0 = full up, 0.0 = center, +1.0 = full down
    """
    global _tilt
    if _pi is None:
        return
    _tilt = max(-1.0, min(1.0, float(value)))
    width = int(CENTER_US + _tilt * RANGE_US)
    width = max(MIN_US, min(MAX_US, width))
    _pi.set_servo_pulsewidth(SERVO_PIN, width)


def center():
    """Return servo to neutral/center position."""
    global _tilt
    _tilt = 0.0
    if _pi is not None:
        _pi.set_servo_pulsewidth(SERVO_PIN, CENTER_US)


def get_tilt() -> float:
    """Return last commanded tilt value."""
    return _tilt


def cleanup():
    """Stop servo signal on shutdown."""
    if _pi is not None:
        _pi.set_servo_pulsewidth(SERVO_PIN, 0)  # 0 = stop signal, releases servo
