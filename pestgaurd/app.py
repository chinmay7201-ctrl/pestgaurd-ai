"""
Crop Pest Acoustic Detection Array - DeviceX (Cyberstorm 2026)
ONE FILE = Phase 1 (simulated devices) + Phase 2 (API gateway) + Phase 3 (live dashboard)

Run:   pip install fastapi uvicorn numpy
       python app.py
Open:  http://localhost:8000
"""
import threading, time, random
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import numpy as np
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

API_KEY = "devicex-secret-123"      # gateway security: every API call needs this key
FS = 8000                           # samples per second read from the piezo sensor
N = 512                             # samples per window
PEST_BAND = (1500, 3000)            # Hz - band where larvae chewing shows up
CONFIRM_WINDOWS = 3                 # needs 3 hits in a row -> avoids false alarms

lock = threading.Lock()
alerts = deque(maxlen=30)


# ---------------------------------------------------------------- PHASE 1
class SensorNode:
    """A virtual stem-mounted piezo sensor node (one per crop zone)."""

    def __init__(self, dev_id, zone):
        self.id, self.zone = dev_id, zone
        self.power = True
        self.infested = False        # simulation switch (the hidden pest)
        self.threshold = 4.0         # sensitivity: how many times above baseline = pest
        self.battery = random.uniform(85, 100)
        self.wind = random.uniform(0.2, 0.6)
        self.hits = 0
        self.alert = False
        self.latest = {}
        self.history = deque(maxlen=60)
        self.recent_band = deque(maxlen=5)
        self.baseline = 1.0
        self.calibrate()

    def read_sensor(self, with_pest):
        """Fake the raw analog signal: loud wind + hiss + (maybe) very quiet chewing."""
        t = np.arange(N) / FS
        self.wind = min(1.2, max(0.1, self.wind + random.uniform(-0.1, 0.1)))
        sig = self.wind * np.sin(2 * np.pi * random.uniform(20, 150) * t)   # wind = low freq
        sig += 0.02 * np.random.randn(N)                                    # electronic noise
        if with_pest:                                                       # chewing bursts
            chew = random.uniform(0.07, 0.12) * np.sin(2 * np.pi * random.uniform(1800, 2600) * t)
            gate = (np.sin(2 * np.pi * random.uniform(8, 20) * t) > 0).astype(float)
            sig += chew * gate
        return sig

    def analyse(self, sig):
        """On-chip processing: band-pass filter + signature match. No cloud used."""
        spec = np.abs(np.fft.rfft(sig * np.hanning(N))) ** 2
        freqs = np.fft.rfftfreq(N, 1 / FS)
        band = (freqs >= PEST_BAND[0]) & (freqs <= PEST_BAND[1])
        band_energy = float(spec[band].sum())
        peak_hz = float(freqs[band][np.argmax(spec[band])])
        return band_energy, peak_hz

    def calibrate(self):
        self.baseline = float(np.mean([self.analyse(self.read_sensor(False))[0] for _ in range(5)]))

    def tick(self):
        if not self.power:
            self.latest = {"status": "OFFLINE"}
            return
        sig = self.read_sensor(self.infested)
        band_energy, peak_hz = self.analyse(sig)
        self.recent_band.append(band_energy)
        score = float(np.mean(self.recent_band)) / self.baseline   # smoothed over 5 windows
        self.hits = self.hits + 1 if score > self.threshold else 0
        was_alert = self.alert
        if self.hits >= CONFIRM_WINDOWS:
            self.alert = True
        elif score < self.threshold * 0.6:                          # clear only when well below
            self.alert = False
        if self.alert and not was_alert:
            alerts.appendleft({"time": datetime.now().strftime("%H:%M:%S"), "zone": self.zone,
                               "msg": f"Pest feeding detected at ~{peak_hz:.0f} Hz (score {score:.1f}x)"})
        if was_alert and not self.alert:
            alerts.appendleft({"time": datetime.now().strftime("%H:%M:%S"), "zone": self.zone,
                               "msg": "Signal back to normal"})
        self.battery = max(0, self.battery - 0.01)
        self.latest = {
            "status": "PEST DETECTED" if self.alert else "HEALTHY",
            "score": round(score, 2),
            "peak_hz": round(peak_hz) if score > self.threshold else None,
            "raw_level": round(float(np.sqrt(np.mean(sig ** 2))), 3),
            "wind": round(self.wind, 2),
            "battery": round(self.battery, 1),
        }
        self.history.append(round(score, 2))

    def state(self):
        return {"id": self.id, "zone": self.zone, "power": self.power, "threshold": self.threshold,
                "sim_pest": self.infested, **self.latest, "history": list(self.history)}


devices = {f"node-{i+1}": SensorNode(f"node-{i+1}", z)
           for i, z in enumerate(["Zone A - Maize", "Zone B - Sugarcane", "Zone C - Paddy", "Zone D - Cotton"])}


def device_loop():
    while True:
        with lock:
            for d in devices.values():
                d.tick()
        time.sleep(1)


# ---------------------------------------------------------------- PHASE 2
@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=device_loop, daemon=True).start()
    yield

app = FastAPI(title="Pest Detection Gateway", lifespan=lifespan)


def check_key(key):
    if key != API_KEY:
        raise HTTPException(401, "Invalid or missing API key")


class Command(BaseModel):
    action: str                     # power_on | power_off | set_threshold | recalibrate | sim_pest_on | sim_pest_off
    value: Optional[float] = None


@app.get("/api/telemetry")
def telemetry(x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    with lock:
        return {"devices": [d.state() for d in devices.values()], "alerts": list(alerts)}


@app.get("/api/devices/{dev_id}")
def one_device(dev_id: str, x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    if dev_id not in devices:
        raise HTTPException(404, "Unknown device")
    with lock:
        return devices[dev_id].state()


@app.post("/api/devices/{dev_id}/command")
def command(dev_id: str, cmd: Command, x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    if dev_id not in devices:
        raise HTTPException(404, "Unknown device")
    with lock:
        d = devices[dev_id]
        if cmd.action == "power_on":
            d.power = True
        elif cmd.action == "power_off":
            d.power, d.alert, d.hits = False, False, 0
            d.recent_band.clear()
        elif cmd.action == "set_threshold":
            if cmd.value is None or not 1.5 <= cmd.value <= 20:
                raise HTTPException(400, "value must be between 1.5 and 20")
            d.threshold = cmd.value
        elif cmd.action == "recalibrate":
            d.calibrate()
        elif cmd.action == "sim_pest_on":
            d.infested = True
        elif cmd.action == "sim_pest_off":
            d.infested = False
        else:
            raise HTTPException(400, "Unknown action")
        return {"ok": True, "device": dev_id, "action": cmd.action}


# ---------------------------------------------------------------- PHASE 3
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Pest Detection Dashboard</title>
<style>
body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#0b1410;color:#e6f2ec}
header{padding:16px 24px;border-bottom:1px solid #1f3a2e;display:flex;justify-content:space-between;align-items:center}
h1{font-size:20px;margin:0}#sum{font-size:14px;color:#8fb8a4}
#grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;padding:20px 24px}
.card{background:#12211a;border:2px solid #1f3a2e;border-radius:12px;padding:16px}
.card.bad{border-color:#ff4d4d;box-shadow:0 0 18px #ff4d4d55}.card.off{opacity:.55}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.zone{font-weight:600}.badge{font-size:12px;padding:3px 10px;border-radius:20px;background:#1e7a4c}
.bad .badge{background:#ff4d4d}.off .badge{background:#555}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;font-size:13px;color:#a9c9b9;margin:8px 0}
.stats b{color:#fff}canvas{width:100%;height:90px;background:#0b1410;border-radius:6px}
.btns{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
button{background:#1f3a2e;color:#e6f2ec;border:1px solid #2f5a46;border-radius:6px;padding:5px 9px;font-size:12px;cursor:pointer}
button:hover{background:#2f5a46}button.sim{border-color:#c98a1b;color:#ffcf70}
#alerts{margin:0 24px 24px;background:#12211a;border:1px solid #1f3a2e;border-radius:12px;padding:14px 18px}
#alerts h2{font-size:15px;margin:0 0 8px}#alerts div{font-size:13px;padding:3px 0;color:#a9c9b9}
</style></head><body>
<header><h1>Crop Pest Acoustic Detection Array</h1><div id="sum">connecting...</div></header>
<div id="grid"></div>
<div id="alerts"><h2>Alert log</h2><div id="log">No alerts yet</div></div>
<script>
const KEY="__KEY__", H={"X-API-Key":KEY,"Content-Type":"application/json"};
const grid=document.getElementById("grid"); let built=false, last={};
function cmd(id,action,value){fetch(`/api/devices/${id}/command`,{method:"POST",headers:H,body:JSON.stringify({action,value})}).then(tick)}
function build(ds){ds.forEach(d=>{const c=document.createElement("div");c.className="card";c.id=d.id;
 c.innerHTML=`<div class="top"><span class="zone">${d.zone} <small>(${d.id})</small></span><span class="badge"></span></div>
 <div class="stats"><span>Pest score: <b class="score"></b></span><span>Alert level: <b class="thr"></b></span>
 <span>Chew freq: <b class="hz"></b></span><span>Wind noise: <b class="wind"></b></span>
 <span>Raw level: <b class="raw"></b></span><span>Battery: <b class="bat"></b></span></div>
 <canvas width="600" height="180"></canvas>
 <div class="btns"><button onclick="cmd('${d.id}',last['${d.id}'].power?'power_off':'power_on')" class="pw"></button>
 <button onclick="cmd('${d.id}','set_threshold',Math.max(1.5,last['${d.id}'].threshold-0.5))">More sensitive</button>
 <button onclick="cmd('${d.id}','set_threshold',Math.min(20,last['${d.id}'].threshold+0.5))">Less sensitive</button>
 <button onclick="cmd('${d.id}','recalibrate')">Recalibrate</button>
 <button class="sim" onclick="cmd('${d.id}',last['${d.id}'].sim_pest?'sim_pest_off':'sim_pest_on')"></button></div>`;
 grid.appendChild(c)});built=true}
function draw(cv,h,thr){const x=cv.getContext("2d"),W=cv.width,Ht=cv.height;x.clearRect(0,0,W,Ht);
 const mx=Math.max(thr*1.5,...h,1),y=v=>Ht-8-(v/mx)*(Ht-16);
 x.strokeStyle="#ff4d4d";x.setLineDash([6,6]);x.beginPath();x.moveTo(0,y(thr));x.lineTo(W,y(thr));x.stroke();x.setLineDash([]);
 x.strokeStyle="#3ddc97";x.lineWidth=3;x.beginPath();h.forEach((v,i)=>{const px=i*(W/59);i?x.lineTo(px,y(v)):x.moveTo(px,y(v))});x.stroke()}
async function tick(){try{const r=await fetch("/api/telemetry",{headers:H});const j=await r.json();
 if(!built)build(j.devices);let bad=0,on=0;
 j.devices.forEach(d=>{last[d.id]=d;const c=document.getElementById(d.id),q=s=>c.querySelector(s);
  const isBad=d.status==="PEST DETECTED";if(isBad)bad++;if(d.power)on++;
  c.className="card"+(isBad?" bad":"")+(d.power?"":" off");q(".badge").textContent=d.status;
  q(".score").textContent=d.power?d.score+"x":"-";q(".thr").textContent=d.threshold+"x";
  q(".hz").textContent=d.peak_hz?d.peak_hz+" Hz":"none";q(".wind").textContent=d.power?d.wind:"-";
  q(".raw").textContent=d.power?d.raw_level:"-";q(".bat").textContent=d.power?d.battery+"%":"-";
  q(".pw").textContent=d.power?"Turn off":"Turn on";q(".sim").textContent=d.sim_pest?"Remove test pest":"Add test pest";
  draw(q("canvas"),d.history,d.threshold)});
 document.getElementById("sum").textContent=`${on}/${j.devices.length} nodes online | ${bad} zone(s) infested | live`;
 document.getElementById("log").innerHTML=j.alerts.length?j.alerts.map(a=>`<div>[${a.time}] <b>${a.zone}</b> - ${a.msg}</div>`).join(""):"No alerts yet";
 }catch(e){document.getElementById("sum").textContent="gateway unreachable"}}
tick();setInterval(tick,1000);
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return PAGE.replace("__KEY__", API_KEY)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
