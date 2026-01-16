import time, sys

log_buffer = []

def log(msg):
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    log_buffer.append(entry)
    if len(log_buffer) > 300:
        log_buffer.pop(0)
    sys.__stdout__.write(entry + "\n")

# Override print globally here
print = log

if __name__ == "__main__":
    log("Logger test message.")
    print("Another test (overridden print).")
    print("Buffer length:", len(log_buffer))
