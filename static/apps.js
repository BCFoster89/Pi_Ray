const telemetryBox = document.getElementById('telemetry');
const logBox = document.getElementById('log');
const horizonCanvas = document.getElementById('horizonCanvas');
const depthCanvas = document.getElementById('depthCanvas');
const hctx = horizonCanvas.getContext('2d');
const dctx = depthCanvas.getContext('2d');

// Motor buttons
const motorButtons = {
  dive: document.getElementById("btn-dive"),
  fwd: document.getElementById("btn-fwd"),
  aft: document.getElementById("btn-aft"),
  left: document.getElementById("btn-left"),
  right: document.getElementById("btn-right"),
  cw: document.getElementById("btn-cw"),
  ccw: document.getElementById("btn-ccw")
};

function updateTelemetry() {
  fetch('/telemetry')
    .then(r => r.json())
    .then(data => {
      // Telemetry display
      telemetryBox.innerHTML = `
        Roll: ${data.roll.toFixed(1)}°<br>
        Pitch: ${data.pitch.toFixed(1)}°<br>
        Yaw: ${data.yaw.toFixed(1)}°<br>
        Depth: ${data.depth_ft.toFixed(2)} ft<br>
        Accel: ${data.accel.map(v=>v.toFixed(2)).join(", ")}<br>
        Gyro: ${data.gyro.map(v=>v.toFixed(1)).join(", ")}
      `;

      // Horizon overlay
      drawHorizon(data.roll, data.pitch);

      // Depth gauge overlay
      drawDepth(data.depth_ft);

      // Motor highlights
      updateMotorHighlights(data.motors || {});
    });
}

function drawHorizon(roll, pitch) {
  const w = horizonCanvas.width = horizonCanvas.clientWidth;
  const h = horizonCanvas.height = horizonCanvas.clientHeight;
  hctx.clearRect(0, 0, w, h);

  hctx.save();
  hctx.translate(w/2, h/2);
  hctx.rotate(-roll * Math.PI/180);
  hctx.strokeStyle = "lime";
  hctx.lineWidth = 2;

  const spacing = 40;
  for (let p = -90; p <= 90; p += 10) {
    const y = (p - pitch) * spacing / 10;
    hctx.beginPath();
    hctx.moveTo(-40, y);
    hctx.lineTo(40, y);
    hctx.stroke();
  }

  hctx.restore();
}

function drawDepth(depth) {
  const w = depthCanvas.width = depthCanvas.clientWidth;
  const h = depthCanvas.height = depthCanvas.clientHeight;
  dctx.clearRect(0, 0, w, h);

  const barHeight = Math.min(h, depth * 10);
  dctx.fillStyle = "rgba(0,255,255,0.5)";
  dctx.fillRect(10, h - barHeight, 20, barHeight);

  dctx.fillStyle = "white";
  dctx.fillText(depth.toFixed(1) + " ft", 40, h - barHeight - 5);
}

function addLog(msg) {
  logBox.textContent += msg + "\n";
  logBox.scrollTop = logBox.scrollHeight;
}

function updateMotorHighlights(motors) {
  for (const [name, btn] of Object.entries(motorButtons)) {
    if (motors[name]) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  }
}

// Hook up motor buttons to backend
for (const [name, btn] of Object.entries(motorButtons)) {
  btn.addEventListener("click", () => {
    fetch(`/motor/${name}`, { method: "POST" })
      .then(() => addLog(`Motor command: ${name}`));
  });
}

// Update every 100ms
setInterval(updateTelemetry, 100);

// === HUD DRAWING ===
function drawHUD(sensor){
  let canvas = document.getElementById("overlay");
  let ctx = canvas.getContext("2d");
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;

  ctx.clearRect(0,0,canvas.width,canvas.height);
  let cx = canvas.width/2;
  let cy = canvas.height/2;

  // === Artificial Horizon ===
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate((-sensor.roll || 0) * Math.PI/180);
  let pitchOffset = (sensor.pitch || 0) * 5;
  ctx.strokeStyle = "#0ff";
  ctx.beginPath();
  ctx.moveTo(-300, pitchOffset);
  ctx.lineTo(300, pitchOffset);
  ctx.stroke();

  // Pitch ladder
  ctx.font = "14px Segoe UI";
  ctx.fillStyle = "#0ff";
  for(let p=-30;p<=30;p+=10){
    let offset = (p - (sensor.pitch||0)) * 5;
    ctx.beginPath();
    ctx.moveTo(-40, offset);
    ctx.lineTo(40, offset);
    ctx.stroke();
    ctx.fillText(p+"°", 50, offset+5);
  }
  ctx.restore();

  // === Heading Compass (top-center) ===
  let heading = sensor.yaw || 0;
  ctx.fillStyle = "#0ff";
  ctx.textAlign = "center";
  ctx.fillText(`Heading: ${Math.round(heading)}°`, cx, 30);
  ctx.beginPath();
  for(let i=-90;i<=90;i+=15){
    let mark = heading + i;
    if (mark<0) mark+=360;
    if (mark>=360) mark-=360;
    let x = cx + i*3;
    ctx.moveTo(x,50);
    ctx.lineTo(x,60);
    ctx.stroke();
    ctx.fillText(mark, x, 75);
  }

  // === Bottom-right telemetry ===
  ctx.fillStyle = "#0f0";
  ctx.textAlign = "right";
  ctx.fillText(`Depth: ${(sensor.depth_ft||0).toFixed(1)} ft`, canvas.width-20, canvas.height-60);
  ctx.fillText(`Pressure: ${(sensor.pressure||0).toFixed(1)} mbar`, canvas.width-20, canvas.height-40);
  ctx.fillText(`Water Temp: ${(sensor.temp_c||0).toFixed(1)} °C`, canvas.width-20, canvas.height-20);

  // === Bottom-left telemetry ===
  ctx.fillStyle = "#ff0";
  ctx.textAlign = "left";
  ctx.fillText(`Pitch: ${(sensor.pitch||0).toFixed(1)}°`, 20, canvas.height-60);
  ctx.fillText(`Roll: ${(sensor.roll||0).toFixed(1)}°`, 20, canvas.height-40);
  ctx.fillText(`IMU Temp: ${(sensor.imu_temp||0).toFixed(1)} °C`, 20, canvas.height-20);

  // === Top-left system info ===
  ctx.fillStyle = "#8cf";
  ctx.textAlign = "left";
  ctx.fillText(`Battery: ${(sensor.voltage||0).toFixed(2)} V`, 20, 30);
}
