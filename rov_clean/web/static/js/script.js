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
// === BUTTON FUNCTIONS ===
function toggleMotor(name){
  fetch(`/motor/${name}`)
    .then(r => r.json())
    .then(d => console.log("Motor:", d))
    .catch(console.error);
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

function toggleLED(){
  fetch('/toggle_led').then(r => r.text()).then(alert);
}

// === STATUS HEARTBEAT ===
async function heartbeatLoop(){
  let btn = document.getElementById("statusBtn");
  try {
    let r = await fetch('/heartbeat', { cache: "no-store" });
    if (r.ok){
      btn.textContent = "Pi Status: OK";
      btn.classList.remove("lost");
      btn.classList.add("ok");
    } else throw new Error("bad response");
  } catch {
    btn.textContent = "Pi Status: LOST";
    btn.classList.remove("ok");
    btn.classList.add("lost");
  }
  setTimeout(heartbeatLoop, 2000);
}
heartbeatLoop();

// === TELEMETRY + OVERLAY ===
async function updateOverlay() {
  try {
    let r = await fetch('/status', { cache: "no-store" });
    let data = await r.json();
    let sensor = data.sensor;

    // draw HUD
    drawHUD(sensor);

    // update telemetry card
   // Replace your existing telemetry section with this:
const telemetryEl = document.getElementById("telemetry");

// Define the order and labels you want
const displayOrder = [
  { key: 'depth_ft', label: 'Depth', unit: 'ft' },
  { key: 'pitch', label: 'Pitch', unit: '°' },
  { key: 'roll', label: 'Roll', unit: '°' },
  { key: 'heading', label: 'Heading', unit: '°' },
  { key: 'temp_c', label: 'Temp', unit: '°C' }
];

telemetryEl.textContent = displayOrder
  .map(item => {
    const val = sensor[item.key];
    // Format the number to 1 decimal place if it exists
    const displayVal = (typeof val === 'number') ? val.toFixed(1) : (val || '0.0');
    return `${item.label.padEnd(8)}: ${displayVal} ${item.unit}`;
  })
  .join('\n');

    //below repalced with above
    //document.getElementById("telemetry").textContent =
      //JSON.stringify(sensor, null, 2);

  } catch (e) {
    console.warn("Telemetry fetch failed", e);
  }
  setTimeout(updateOverlay, 200);
}
updateOverlay();

// === LOGS ===
async function updateLogs() {
  try {
    let r = await fetch('/logs', { cache: "no-store" });
    let text = await r.text();
    const logsEl = document.getElementById("logs");
    const logsCard = document.getElementById("logsCard");

    // Clean up <br> tags and show last 20 lines
    logsEl.textContent = text.split("<br>").slice(-20).join("\n");

    // AUTO-SCROLL: This pushes the view to the bottom
    logsCard.scrollTop = logsCard.scrollHeight;

  } catch (e) {
    console.warn("Log fetch failed", e);
  }
  setTimeout(updateLogs, 1000);
}
updateLogs();

// === HUD DRAWING ===
function drawHUD(sensor){
  let canvas = document.getElementById("overlay");
  let ctx = canvas.getContext("2d");
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;

  ctx.clearRect(0,0,canvas.width,canvas.height);
  let cx = canvas.width/2;
  let cy = canvas.height/2;

  // Horizon with roll & pitch
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate((-sensor.roll || 0) * Math.PI/180);
  let pitchOffset = (sensor.pitch || 0) * 5; // scale
  ctx.strokeStyle = "#ff0";
  ctx.beginPath();
  ctx.moveTo(-300, pitchOffset);
  ctx.lineTo(300, pitchOffset);
  ctx.stroke();

  // Pitch ladder
  ctx.font = "14px Segoe UI";
  ctx.fillStyle = "#ff0";
  for(let p=-30;p<=30;p+=10){
    let offset = -1 * (p - (sensor.pitch||0)) * 5;
    ctx.beginPath();
    ctx.moveTo(-40, offset);
    ctx.lineTo(40, offset);
    ctx.stroke();
    ctx.fillText(p+"°", 50, offset+5);
  }
  ctx.restore();

  // Heading tape top-center
  let heading = sensor.yaw || 0;
  ctx.fillStyle = "#ff0";
  ctx.font = "14px Arial"; // This sets the size to 30 pixels and makes it bold
  ctx.textAlign = "center";
  ctx.fillText(`Heading: ${Math.round(heading)}°`, cx, 30);
  ctx.beginPath();
  for(let i=-90;i<=90;i+=10){
    let mark = Math.round(heading + i); // Round the mark to remove decimals
    if (mark<0) mark+=360;
    if (mark>=360) mark-=360;
    let x = cx + i*3;
    ctx.moveTo(x,50);
    ctx.lineTo(x,60);
    ctx.stroke();
    ctx.fillText(mark, x, 75);
  }

  // Depth bottom-right
  ctx.fillStyle = "#ff0";
  ctx.font = "bold 20px Arial"; // This sets the size to 30 pixels and makes it bold
  ctx.textAlign = "left";
  ctx.fillText(`Depth: ${(sensor.depth_ft||0).toFixed(1)} ft`, 20, 40);
  
  // Roll & Pitch bottom-left
  ctx.fillStyle = "#ff0";
  ctx.font = "bold 16px Arial"; // This sets the size to 30 pixels and makes it bold
  ctx.textAlign = "left";
  ctx.fillText(`Pitch: ${(sensor.pitch||0).toFixed(1)}°`, 20, canvas.height-40);
  ctx.fillText(`Roll: ${(sensor.roll||0).toFixed(1)}°`, 20, canvas.height-20);
}
