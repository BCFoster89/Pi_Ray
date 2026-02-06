# winconpi5.py - PWM Controller Client for ROV
# Reads Xbox controller axes and sends PWM commands to the ROV
import pygame
import requests
import time
import json

# Initialize pygame
pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    raise RuntimeError("No joystick detected!")

controller = pygame.joystick.Joystick(0)
controller.init()

print(f"Controller: {controller.get_name()}")
print(f"Axes: {controller.get_numaxes()}, Buttons: {controller.get_numbuttons()}")

# Flask server base URL (replace with your Pi's IP if needed)
BASE_URL = "http://192.168.1.3:5000"
# BASE_URL = "http://127.0.0.1:5000"    # for local testing

# =============================================================================
# AXIS MAPPING - Adjust these based on your specific controller
# =============================================================================
# Common Xbox controller axis mapping:
# Axis 0: Left stick X (left=-1, right=+1)
# Axis 1: Left stick Y (up=-1, down=+1)
# Axis 2: Left trigger (released=-0.5, pressed=+0.5) - YOUR CONTROLLER
# Axis 3: Right stick X (left=-1, right=+1)
# Axis 4: Right stick Y (up=-1, down=+1)
# Axis 5: Right trigger (released=-0.5, pressed=+0.5) - YOUR CONTROLLER

AXIS_MAP = {
    'left_x': 0,     # Left stick horizontal (strafe/sway)
    'left_y': 1,     # Left stick vertical (forward/surge)
    'right_x': 3,    # Right stick horizontal (yaw/rotation)
    'right_y': 4,    # Right stick vertical (unused)
    'lt': 2,         # Left trigger (descend)
    'rt': 5,         # Right trigger (ascend)
}

# Trigger calibration - adjust these based on your controller
# Your triggers: released = -0.5, fully pressed = +0.5
TRIGGER_MIN = -0.5   # Value when trigger is released
TRIGGER_MAX = 0.5    # Value when trigger is fully pressed

# Button mapping for non-PWM functions
BUTTON_MAP = {
    7: 'lights',     # Start button → toggle LED
    6: 'estop',      # Back button → emergency stop
}

# =============================================================================
# CONFIGURATION
# =============================================================================
DEADBAND = 0.10           # Ignore inputs below this threshold
SEND_INTERVAL = 0.05      # 20Hz update rate (50ms)
SMOOTHING_ALPHA = 0.3     # EMA smoothing factor (0.0-1.0, higher = less smoothing)
CHANGE_THRESHOLD = 0.02   # Only send if values changed more than this

# =============================================================================
# STATE TRACKING
# =============================================================================
last_sent = {'surge': 0.0, 'sway': 0.0, 'yaw': 0.0, 'descend': 0.0, 'ascend': 0.0}
smoothed = {'surge': 0.0, 'sway': 0.0, 'yaw': 0.0, 'descend': 0.0, 'ascend': 0.0}
previous_buttons = [0] * controller.get_numbuttons()


def apply_deadband(value, deadband=DEADBAND):
    """Apply deadband and normalize the remaining range."""
    if abs(value) < deadband:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * (abs(value) - deadband) / (1.0 - deadband)


def normalize_trigger(raw_value):
    """
    Normalize trigger value from controller range to 0.0-1.0.
    Your controller: released = -0.5, fully pressed = +0.5
    Output: released = 0.0, fully pressed = 1.0
    """
    # Map from [TRIGGER_MIN, TRIGGER_MAX] to [0, 1]
    normalized = (raw_value - TRIGGER_MIN) / (TRIGGER_MAX - TRIGGER_MIN)
    # Clamp to valid range
    return max(0.0, min(1.0, normalized))


def smooth_value(key, new_value, alpha=SMOOTHING_ALPHA):
    """Apply exponential moving average smoothing."""
    smoothed[key] = alpha * new_value + (1.0 - alpha) * smoothed[key]
    return smoothed[key]


def read_axes():
    """Read and process all controller axes."""
    pygame.event.pump()

    # Read raw axis values for sticks
    left_x = controller.get_axis(AXIS_MAP['left_x'])
    left_y = controller.get_axis(AXIS_MAP['left_y'])
    right_x = controller.get_axis(AXIS_MAP['right_x'])

    # Read and normalize triggers
    # Triggers are separate: LT = descend, RT = ascend
    try:
        lt_raw = controller.get_axis(AXIS_MAP['lt'])
        rt_raw = controller.get_axis(AXIS_MAP['rt'])

        # Normalize triggers from [-0.5, +0.5] to [0, 1]
        descend_raw = normalize_trigger(lt_raw)
        ascend_raw = normalize_trigger(rt_raw)
    except (pygame.error, IndexError):
        descend_raw = 0.0
        ascend_raw = 0.0

    # Apply deadband to stick axes
    surge_raw = apply_deadband(-left_y)   # Invert Y: push up = forward = positive
    sway_raw = apply_deadband(left_x)     # Right = positive sway
    yaw_raw = apply_deadband(right_x)     # Right = positive yaw (turn right)

    # Apply deadband to triggers (already 0-1 range)
    descend_raw = descend_raw if descend_raw > DEADBAND else 0.0
    ascend_raw = ascend_raw if ascend_raw > DEADBAND else 0.0

    # Apply smoothing
    return {
        'surge': smooth_value('surge', surge_raw),
        'sway': smooth_value('sway', sway_raw),
        'yaw': smooth_value('yaw', yaw_raw),
        'descend': smooth_value('descend', descend_raw),
        'ascend': smooth_value('ascend', ascend_raw)
    }


def values_changed(new_vals, threshold=CHANGE_THRESHOLD):
    """Check if values changed enough to warrant sending an update."""
    for key in ['surge', 'sway', 'yaw', 'descend', 'ascend']:
        if abs(new_vals[key] - last_sent[key]) > threshold:
            return True
    return False


def send_pwm_command(values):
    """Send PWM command to ROV via POST request."""
    global last_sent
    try:
        r = requests.post(
            f"{BASE_URL}/motor/pwm",
            json=values,
            timeout=0.2
        )
        if r.status_code == 200:
            last_sent = values.copy()
            return True
        else:
            print(f"PWM command failed: {r.status_code}")
    except requests.exceptions.Timeout:
        print("Timeout sending PWM command")
    except requests.exceptions.ConnectionError:
        print("Connection error - is the ROV online?")
    except Exception as e:
        print(f"Error sending PWM command: {e}")
    return False


def check_buttons():
    """Handle button presses for lights and emergency stop."""
    global previous_buttons
    buttons = [controller.get_button(i) for i in range(controller.get_numbuttons())]

    for i, state in enumerate(buttons):
        if i in BUTTON_MAP and state and not previous_buttons[i]:
            action = BUTTON_MAP[i]
            try:
                if action == 'lights':
                    r = requests.get(f"{BASE_URL}/toggle_led", timeout=0.5)
                    print(f"Toggled LED: {r.text}")
                elif action == 'estop':
                    r = requests.get(f"{BASE_URL}/motor/all_stop", timeout=0.5)
                    print("*** EMERGENCY STOP ***")
                    # Reset smoothed values to prevent motor restart
                    for key in smoothed:
                        smoothed[key] = 0.0
            except Exception as e:
                print(f"Error handling button {i}: {e}")

    previous_buttons = buttons


def print_status(values):
    """Print current control values (for debugging)."""
    surge = values['surge']
    sway = values['sway']
    yaw = values['yaw']
    descend = values['descend']
    ascend = values['ascend']
    print(f"\rSurge: {surge:+.2f} | Sway: {sway:+.2f} | Yaw: {yaw:+.2f} | Desc: {descend:.2f} | Asc: {ascend:.2f}  ", end='')


# =============================================================================
# MAIN LOOP
# =============================================================================
print(f"\nPWM Controller ready. Sending to: {BASE_URL}")
print("=" * 60)
print("Controls:")
print("  Left stick Y  : Forward / Backward (surge)")
print("  Left stick X  : Strafe Left / Right (sway)")
print("  Right stick X : Rotate Left / Right (yaw)")
print("  Left trigger  : Descend (0-100%)")
print("  Right trigger : Ascend (0-100%)")
print("  Back button   : EMERGENCY STOP")
print("  Start button  : Toggle LED")
print("=" * 60)
print(f"Trigger calibration: min={TRIGGER_MIN}, max={TRIGGER_MAX}")
print("\nPress Ctrl+C to exit\n")

try:
    last_send_time = time.time()

    while True:
        values = read_axes()
        check_buttons()

        # Send update if values changed or enough time has passed
        now = time.time()
        if values_changed(values) or (now - last_send_time > 0.25):
            if send_pwm_command(values):
                last_send_time = now
                print_status(values)

        time.sleep(SEND_INTERVAL)

except KeyboardInterrupt:
    print("\n\nShutting down...")
    # Send zero command on exit to stop all motors
    try:
        zero_cmd = {'surge': 0.0, 'sway': 0.0, 'yaw': 0.0, 'descend': 0.0, 'ascend': 0.0}
        requests.post(f"{BASE_URL}/motor/pwm", json=zero_cmd, timeout=0.5)
        print("Motors stopped.")
    except:
        print("Could not send stop command.")
    print("Controller disconnected.")
finally:
    pygame.quit()
