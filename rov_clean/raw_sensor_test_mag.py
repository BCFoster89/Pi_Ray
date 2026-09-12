import time
import board
import adafruit_lps28
import qwiic_lsm6dso
import adafruit_mmc56x3

i2c = board.I2C()
ps = adafruit_lps28.LPS28(i2c)

imu = qwiic_lsm6dso.QwiicLSM6DSO()
print("IMU connected:", imu.connected)
imu.begin()

mag = adafruit_mmc56x3.MMC5603(i2c)
print("Mag initialized")

for i in range(100):
    p = ps.pressure
    tc = ps.temperature
    ax, ay, az = imu.read_float_accel_all()
    gx, gy, gz = imu.read_float_gyro_all()
    t = imu.read_temp_c()
    mx, my, mz = mag.magnetic
    print(f"[{i:02d}] accel=({ax:+.3f},{ay:+.3f},{az:+.3f}) g  "
          f"gyro=({gx:+.2f},{gy:+.2f},{gz:+.2f}) dps  "
          f"imu_temp={t:.2f}C  press={p:.2f}hPa  press_temp={tc:.2f}C  "
          f"mag=({mx:+.1f},{my:+.1f},{mz:+.1f})")
    time.sleep(0.05)
