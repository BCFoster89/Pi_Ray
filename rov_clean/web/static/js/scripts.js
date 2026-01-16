async function pollMotorStatus() {
  try {
    let r = await fetch('/motor_status');
    let res = await r.json();

    let btnMap = {
      "y": "btn-y", "x": "btn-x", "b": "btn-b", "a": "btn-a",
      "right_trigger": "btn-rt", "left_trigger": "btn-lt", "dive": "btn-dive"
    };

    for (let group in btnMap) {
      let btn = document.getElementById(btnMap[group]);
      if (!btn) continue;
      if (res[group] === "on") btn.classList.add("active");
      else btn.classList.remove("active");
    }
  } catch (e) { console.error("motor_status fetch failed", e); }
}
setInterval(pollMotorStatus, 300);

async function update() {
  let r = await fetch('/status');
  let d = (await r.json()).sensor;
  document.getElementById("tele").textContent = `
Pressure: ${d.pressure_inhg} inHg
Air Temp: ${d.temperature_f} °F
Depth: ${d.depth_ft} ft
Accel: X=${d.accel_x}g Y=${d.accel_y}g Z=${d.accel_z}g
Gyro: X=${d.gyro_x}°/s Y=${d.gyro_y}°/s Z=${d.gyro_z}°/s
IMU Temp: ${d.imu_temp_f} °F
Roll: ${d.roll}°
Pitch: ${d.pitch}°
Yaw: ${d.yaw}°`;
  setTimeout(update, 500);
}
update();

async function calulate(mode){ await fetch(mode=='horizon'?'/cal_horizon':'/cal_depth'); }
async function toggleLED(){ await fetch('/toggle_led'); }
async function zeroIMU(){ await fetch('/zero_imu'); }
async function motorCmd(name){
  let r = await fetch('/motor/'+name);
  let res = await r.json();
}
async function logLoop(){
  let r = await fetch('/logs');
  let logsElem = document.getElementById("logs");
  logsElem.innerHTML = await r.text();
  logsElem.scrollTop = logsElem.scrollHeight;
  setTimeout(logLoop,2000);
}
logLoop();
