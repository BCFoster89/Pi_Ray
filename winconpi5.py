import pygame
import requests
import time

# Initialize pygame
pygame.init()

# Set up the joystick
pygame.joystick.init()
if pygame.joystick.get_count() == 0:
    raise RuntimeError("No joystick detected!")
controller = pygame.joystick.Joystick(0)
controller.init()

# Flask server base URL (replace with your Pi’s IP if needed)
BASE_URL = "http://192.168.1.3:5000"   # e.g., your Pi’s IP
# BASE_URL = "http://127.0.0.1:5000"    # for local testing

# Mapping: Xbox controller buttons → motor groups
button_to_motor = {
    0: "a",             # A button
    2: "x",             # X button
    3: "y",             # Y button
    1: "b",             # B button
    4: "left_trigger",  # LB (mapped to LT group)
    5: "right_trigger", # RB (mapped to RT group)
    7: "lights",         # Start → lights
    6: "dive"         # Start → lights
}

# Track previous button states
previous_buttons = [0] * controller.get_numbuttons()

print("Controller ready. Sending motor commands to:", BASE_URL)

try:
    while True:
        pygame.event.pump()
        buttons = [controller.get_button(i) for i in range(controller.get_numbuttons())]

        for i, state in enumerate(buttons):
            if i in button_to_motor and state != previous_buttons[i]:
                group = button_to_motor[i]
                if state:  # pressed
                    try:
                        if group == "lights":
                            r = requests.get(f"{BASE_URL}/toggle_led", timeout=0.5)
                            print("Pressed Start → toggled lights:", r.text)
                        else:
                            r = requests.get(f"{BASE_URL}/motor/{group}", timeout=0.5)
                            print(f"Pressed {i} → toggled motor group {group}: {r.text}")
                    except Exception as e:
                        print("Error sending command:", e)

            previous_buttons[i] = state

        time.sleep(0.05)

except KeyboardInterrupt:
    print("Exiting controller script.")
