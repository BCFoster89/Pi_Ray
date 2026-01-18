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

// Fetch and draw telemetry overlay
async function updateOverlay() {
  try {
    let r = await fetch('/status', { cache: "no-store" });
    let data = await r.json();
    let sensor = data.sensor;

    drawHUD(sensor);
  } catch (e) {
    console.warn("Telemetry fetch failed", e);
  }
  setTimeout(updateOverlay, 200); // ~5 Hz
}

function drawHUD(sensor){
  let canvas = document.getElementById("overlay");
  let ctx = canvas.getContext("2d");
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;

  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle = "#0ff";
  ctx.fillStyle = "#0ff";
  ctx.lineWidth = 2;
  ctx.font = "16px Segoe UI";

  let cx = canvas.width/2;
  let cy = canvas.height/2;

  // === Artificial Horizon ===
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate((-sensor.roll || 0) * Math.PI/180);  // roll
  let pitchOffset = (sensor.pitch || 0) * 3;      // pitch scaling
  ctx.beginPath();
  ctx.moveTo(-200, pitchOffset);
  ctx.lineTo(200, pitchOffset);
  ctx.stroke();
  ctx.restore();

  // === Depth (bottom-right) ===
  ctx.fillStyle = "#0f0";
  ctx.textAlign = "right";
  ctx.fillText(`Depth: ${(sensor.depth_ft || 0).toFixed(1)} ft`, canvas.width - 20, canvas.height - 20);

  // === Heading Compass (top-center) ===
  let heading = sensor.yaw || 0;
  ctx.fillStyle = "#0ff";
  ctx.textAlign = "center";
  ctx.fillText(`Heading: ${Math.round(heading)}°`, cx, 30);

  // Draw compass tape
  ctx.beginPath();
  for(let i=-90;i<=90;i+=15){
    let mark = heading + i;
    if (mark < 0) mark += 360;
    if (mark >= 360) mark -= 360;
    let x = cx + i*3;  // scale for spacing
    ctx.moveTo(x,50);
    ctx.lineTo(x,60);
    ctx.fillText(mark, x, 75);
  }
  ctx.stroke();

  // === Pitch & Roll (bottom-left) ===
  ctx.fillStyle = "#ff0";
  ctx.textAlign = "left";
  ctx.fillText(`Pitch: ${(sensor.pitch||0).toFixed(1)}°`, 20, canvas.height - 40);
  ctx.fillText(`Roll: ${(sensor.roll||0).toFixed(1)}°`, 20, canvas.height - 20);
}

updateOverlay(); // start loop


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
