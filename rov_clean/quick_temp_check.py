# quick_temp_check.py — run directly on the Pi to sanity-check the LPS28 in isolation,
# bypassing the Flask app. Confirms the "Water" temperature source independently.
import time
import board, adafruit_lps28

i2c = board.I2C()
ps = adafruit_lps28.LPS28(i2c)
for _ in range(5):
    tc = ps.temperature
    print(f"pressure={ps.pressure:.2f} hPa  temp={tc:.2f} C ({tc * 9 / 5 + 32:.1f} F)")
    time.sleep(1)
