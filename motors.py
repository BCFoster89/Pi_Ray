import RPi.GPIO as GPIO
import time
from sensors import telemetry

# --- GPIO setup ---
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Motor pin groups (example — update to match your wiring)
MOTOR_PINS = {
    "fwd":  [5, 6],      # forward group
    "aft":  [13, 19],    # aft group
    "left": [20, 21],    # left group
    "right":[16, 26],    # right group
    "cw":   [12, 18],    # clockwise
    "ccw":  [23, 24],    # counter clockwise
    "dive": [7, 8]       # dive group
}

# Lights pin
LIGHT_PIN = 4

# Initialize all motor pins
for group, pins in MOTOR_PINS.items():
    for p in pins:
        GPIO.setup(p, GPIO.OUT)
        GPIO.output(p, GPIO.LOW)

# Initialize lights pin
GPIO.setup(LIGHT_PIN, GPIO.OUT)
GPIO.output(LIGHT_PIN, GPIO.LOW)

def set_group_state(group: str, state: bool):
    """Turn a motor group ON or OFF"""
    if group not in MOTOR_PINS:
        print(f"[MOTOR] Unknown motor group: {group}")
        return

    for p in MOTOR_PINS[group]:
        GPIO.output(p, GPIO.HIGH if state else GPIO.LOW)

    telemetry["motors"][group] = state
    print(f"[MOTOR] {group} -> {'ON' if state else 'OFF'}")

def toggle_motor(group: str):
    """Toggle motor group"""
    if group not in telemetry["motors"]:
        print(f"[MOTOR] Unknown group: {group}")
        return
    new_state = not telemetry["motors"][group]
    set_group_state(group, new_state)

def toggle_lights():
    """Toggle LED lights on/off"""
    current_state = GPIO.input(LIGHT_PIN)
    new_state = not current_state
    GPIO.output(LIGHT_PIN, GPIO.HIGH if new_state else GPIO.LOW)
    print(f"[LIGHTS] -> {'ON' if new_state else 'OFF'}")


if __name__ == "__main__":
    # Quick test
    toggle_motor("fwd")
    time.sleep(1)
    toggle_motor("fwd")

    toggle_lights()
    time.sleep(1)
    toggle_lights()

    GPIO.cleanup()
