# servo.py
"""Camera tilt servo controller — GPIO 14, pigpio DMA PWM, rate control."""

import time, threading, subprocess
from logger import log

SERVO_PIN       = 14
CENTER_US       = 1500    # µs — neutral/center tilt (1.5 ms pulse)
RANGE_US        = 167     # µs — ±167 µs from center ≈ ±15° (30° total travel)
MIN_US          = 800     # hard safety floor
MAX_US          = 2200    # hard safety ceiling
RATE_US_PER_SEC = 150.0   # max speed: full 30° travel in ~2 s at full stick
RATE_TIMEOUT_S  = 1.0     # stop moving if no command received within this time

_pi      = None
_pos_us  = float(CENTER_US)   # current position (µs, float for precision)
_rate    = 0.0                 # joystick rate command (-1.0 to +1.0)
_rate_ts = 0.0                 # timestamp of last rate command


def _tilt_loop():
    """Background thread: accumulates position from rate at 50 Hz, auto-reconnects."""
    global _pos_us, _pi
    last          = time.time()
    _reconnect_ts = 0.0

    while True:
        time.sleep(0.02)
        try:
            # ── Reconnect if pigpiod died or never started ────────────
            if _pi is None or not _pi.connected:
                now = time.time()
                if now - _reconnect_ts > 5.0:
                    _reconnect_ts = now
                    try:
                        import pigpio
                        candidate = pigpio.pi()
                        if candidate.connected:
                            _pi = candidate
                            log("[SERVO] pigpio reconnected")
                        else:
                            subprocess.run(['sudo', 'pigpiod'], capture_output=True)
                    except Exception:
                        pass
                last = time.time()
                continue

            # ── Normal rate-accumulation step ─────────────────────────
            now = time.time()
            dt  = now - last
            last = now
            rate = _rate if (now - _rate_ts) < RATE_TIMEOUT_S else 0.0
            if rate != 0.0:
                _pos_us += rate * RATE_US_PER_SEC * dt
                _pos_us  = max(float(MIN_US), min(float(MAX_US), _pos_us))
                _pi.set_servo_pulsewidth(SERVO_PIN, int(_pos_us))

        except Exception as e:
            log(f"[SERVO] Loop error: {e}")
            last = time.time()


def init():
    """Initialize servo via pigpio DMA PWM. Called once at server startup."""
    global _pi, _pos_us, _rate, _rate_ts
    try:
        import pigpio
        _pi = pigpio.pi()
        if not _pi.connected:
            log("[SERVO] pigpiod not running — attempting auto-start")
            subprocess.run(['sudo', 'pigpiod'], capture_output=True)
            subprocess.run(['sudo', 'systemctl', 'start', 'pigpiod'], capture_output=True)
            time.sleep(0.8)
            _pi = pigpio.pi()
        if _pi.connected:
            _pos_us = float(CENTER_US)
            _rate   = 0.0
            threading.Thread(target=_tilt_loop, daemon=True).start()
            log(f"[SERVO] Camera tilt on GPIO {SERVO_PIN} via pigpio DMA (rate control)")
        else:
            log("[SERVO] pigpio daemon unavailable — servo disabled (will retry)")
            _pi = None
            threading.Thread(target=_tilt_loop, daemon=True).start()
    except Exception as e:
        log(f"[SERVO] Init failed: {e}")
        _pi = None
        threading.Thread(target=_tilt_loop, daemon=True).start()


def set_tilt(value: float):
    """
    Set camera tilt rate.
    value: -1.0 = tilt up at max speed, 0.0 = hold position, +1.0 = tilt down at max speed
    """
    global _rate, _rate_ts
    _rate    = max(-1.0, min(1.0, float(value)))
    _rate_ts = time.time()


def center():
    """Snap servo to center immediately (called by E-stop)."""
    global _rate, _rate_ts, _pos_us
    _rate    = 0.0
    _rate_ts = time.time()
    _pos_us  = float(CENTER_US)
    if _pi is not None:
        _pi.set_servo_pulsewidth(SERVO_PIN, CENTER_US)


def get_tilt() -> float:
    """Return current tilt position as -1.0 to +1.0."""
    return max(-1.0, min(1.0, (_pos_us - CENTER_US) / RANGE_US))


def cleanup():
    """Stop servo signal on shutdown."""
    if _pi is not None:
        _pi.set_servo_pulsewidth(SERVO_PIN, 0)  # 0 = stop signal, releases servo
