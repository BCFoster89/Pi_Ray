async function pollMotorStatus(){
  try {
    let r = await fetch('/motor_status');
    let res = await r.json();

    let btnMap = {
      "y": "btn-y",
      "x": "btn-x",
      "b": "btn-b",
      "a": "btn-a",
      "right_trigger": "btn-rt",
      "left_trigger": "btn-lt",
      "dive": "btn-dive"
    };

    for (let group in btnMap){
      let btn = document.getElementById(btnMap[group]);
      if (!btn) continue;
      if (res[group] === "on"){
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    }
  } catch (e) {
    console.error("motor_status fetch failed", e);
  }
}

// poll every 300ms
setInterval(pollMotorStatus, 500);

async function update(){
  let r = await fetch('/status');
  let d = await r.json();
  d = d.sensor;

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

  drawHUD(d.roll, d.pitch, d.yaw, d.depth_ft);
  setTimeout(update,500);
}

function drawHUD(r, p, yaw, depth){
  let c = document.getElementById("overlay");
  let ctx = c.getContext("2d");
  ctx.clearRect(0,0,c.width,c.height);

  // === Pitch Ladder (shifted left side) ===
  ctx.save();
  ctx.translate(c.width/4, c.height/2);  // move ladder left
  ctx.rotate(-r*Math.PI/180);
  ctx.translate(0, p*3);

  ctx.strokeStyle="#fff"; ctx.lineWidth=2; ctx.font="14px sans-serif"; ctx.fillStyle="#fff";
  for(let i=-90;i<=90;i+=10){
    let y = i*3;
    ctx.beginPath();
    ctx.moveTo(-30,y); ctx.lineTo(30,y); ctx.stroke();
    if (i % 20 === 0) ctx.fillText(i+"°",-50,y+4);
  }
  ctx.restore();

  // === Fixed aircraft symbol (center) ===
  ctx.strokeStyle="#0ff"; ctx.lineWidth=2;
  ctx.beginPath(); ctx.moveTo(c.width/2-30,c.height/2); ctx.lineTo(c.width/2+30,c.height/2); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(c.width/2,c.height/2); ctx.lineTo(c.width/2,c.height/2-20); ctx.stroke();

  // === Roll arc (bigger radius) ===
  ctx.strokeStyle="#fff"; ctx.lineWidth=1;
  let arcRadius = 120;  // increased
  ctx.beginPath();
  ctx.arc(c.width/2, c.height/2-arcRadius, arcRadius, Math.PI, 2*Math.PI);
  ctx.stroke();

  // Roll marker
  ctx.save();
  ctx.translate(c.width/2, c.height/2-arcRadius);
  ctx.rotate(-r*Math.PI/180);
  ctx.beginPath(); ctx.moveTo(0,-arcRadius); ctx.lineTo(-6,-arcRadius+12); ctx.lineTo(6,-arcRadius+12); ctx.closePath();
  ctx.fillStyle="#fff"; ctx.fill();
  ctx.restore();

  // === Depth gauge (left side) ===
  let barHeight = c.height * 0.6;
  let barTop = c.height*0.2;
  let h = Math.min(barHeight, (depth/25)*barHeight);
  let grad=ctx.createLinearGradient(0,barTop,0,barTop+barHeight);
  grad.addColorStop(0,"#0ff");
  grad.addColorStop(1,"#004");
  ctx.fillStyle=grad;
  ctx.fillRect(20, barTop+barHeight-h, 30, h);

  ctx.strokeStyle="#fff"; ctx.strokeRect(20, barTop, 30, barHeight);
  ctx.fillStyle="#fff"; ctx.font="20px Roboto";
  ctx.fillText(depth+" ft", 60, barTop+20);

  // === Yaw compass tape (top center) ===
  let heading = yaw;
  ctx.save();
  ctx.translate(c.width/2, 50);
  ctx.strokeStyle="#fff"; ctx.fillStyle="#fff"; ctx.font="14px sans-serif";

  for (let i=-90; i<=90; i+=10){
    let hdg = heading + i;
    if (hdg > 180) hdg -= 360;
    if (hdg < -180) hdg += 360;
    let x = i*3;
    ctx.beginPath(); ctx.moveTo(x, -8); ctx.lineTo(x, 8); ctx.stroke();
    if (i % 30 === 0){
      ctx.fillText(hdg.toFixed(0), x-15, -15);
    }
  }

  ctx.restore();

  // Current heading readout
  ctx.fillStyle="#00d4ff"; ctx.font="20px Roboto";
  ctx.fillText("HDG: "+heading.toFixed(0)+"°", c.width/2-50, 25);

  // Roll/Pitch readouts (keep small)
  ctx.fillText("Roll: "+r.toFixed(1)+"°", 20, c.height-50);
  ctx.fillText("Pitch: "+p.toFixed(1)+"°", 20, c.height-20);
}

async function calulate(mode){
  await fetch(mode=='horizon'?'/cal_horizon':'/cal_depth');
}

async function toggleLED(){await fetch('/toggle_led')}
async function zeroIMU(){await fetch('/zero_imu')}
// Heartbeat loop for Pi status
async function heartbeatLoop(){
  let btn = document.getElementById("statusBtn");
  try {
    let r = await fetch('/heartbeat', { cache: "no-store" });
    if (r.ok){
      btn.textContent = "Pi Status: OK";
      btn.classList.remove("lost");
      btn.classList.add("ok");
    } else {
      btn.textContent = "Pi Status: LOST";
      btn.classList.remove("ok");
      btn.classList.add("lost");
    }
  } catch (e){
    btn.textContent = "Pi Status: LOST";
    btn.classList.remove("ok");
    btn.classList.add("lost");
  }
  setTimeout(heartbeatLoop, 2000);
}
heartbeatLoop();

// Example button actions
function toggleMotor(name){
  fetch(`/motor/${name}`).then(r => r.json()).then(console.log);
}

function calibrateDepth(){
  fetch('/cal_depth').then(r => r.text()).then(alert);
}

function calibrateHorizon(){
  fetch('/cal_horizon').then(r => r.text()).then(alert);
}

function zeroIMU(){
  fetch('/zero_imu').then(r => r.text()).then(alert);
}




async function motorCmd(name){
  let r = await fetch('/motor/'+name);
  let res = await r.json();

  let btnMap = {
    "y": "btn-y",
    "x": "btn-x",
    "b": "btn-b",
    "a": "btn-a",
    "right_trigger": "btn-rt",
    "left_trigger": "btn-lt",
    "dive": "btn-dive"
  };

  let btnId = btnMap[res.group];
  if (btnId){
    let btn = document.getElementById(btnId);
    if (res.state === "on"){
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  }
}

async function logLoop(){
  let r = await fetch('/logs');
  let logsElem = document.getElementById("logs");
  logsElem.innerHTML = await r.text();
  logsElem.scrollTop = logsElem.scrollHeight;
  setTimeout(logLoop,2000);
}

update();
logLoop();
