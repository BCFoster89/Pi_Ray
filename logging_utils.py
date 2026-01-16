import time, sys
log_buffer = []

def log(msg):
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    log_buffer.append(entry)
    if len(log_buffer) > 300:
        log_buffer.pop(0)
    sys.__stdout__.write(entry + "\n")

print = log

if __name__ == "__main__":
    print("[TEST] Logging utils")
    log("Hello test log")
    log("Another log line")
    print("Log buffer:", log_buffer)