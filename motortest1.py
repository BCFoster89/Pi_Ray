from gpiozero import PWMOutputDevice
from time import sleep

# --- CONFIGURATION ---
# Change '18' to the GPIO pin you are using (BCM numbering)
MOTOR_PIN = 18 

# Initialize the motor pin
# Default frequency is usually 100Hz
motor = PWMOutputDevice(MOTOR_PIN, active_high=True, initial_value=0, frequency=100)

print("--- Raspberry Pi PWM Motor Tester ---")
print("Commands: 'd' for Duty Cycle (0-100), 'f' for Frequency (Hz), 'q' to Quit")

try:
    while True:
        cmd = input("\nEnter command (d/f/q): ").lower()

        if cmd == 'd':
            val = float(input("Enter Duty Cycle (0 to 100): "))
            # gpiozero uses 0.0 to 1.0 for duty cycle
            motor.value = val / 100
            print(f"Duty Cycle set to {val}%")

        elif cmd == 'f':
            val = int(input("Enter Frequency in Hz (e.g., 50 to 2000): "))
            motor.frequency = val
            print(f"Frequency set to {val} Hz")

        elif cmd == 'q':
            print("Shutting down...")
            motor.value = 0
            break
        else:
            print("Invalid command. Use d, f, or q.")

except KeyboardInterrupt:
    print("\nInterrupted by user.")
finally:
    motor.close()
