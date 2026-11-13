# PestGuard AI - Autonomous Crop Pest Acoustic Detection Array
Cyberstorm 2026, DeviceX - Problem 10

## What it does
Detects pest chewing vibrations inside crop stems and alerts the farmer by zone, with no cloud processing.

## Phases
1. Device simulation: 4 virtual sensor nodes generate wind noise, hiss and pest chewing signals (app.py), plus a single-node circuit in Wokwi.
2. API gateway: FastAPI endpoints for telemetry and remote commands, secured with an API key.
3. Live dashboard: real-time charts and alerts per zone.

## Run
pip install fastapi uvicorn numpy
python app.py
Open http://127.0.0.1:8000

## Wokwi simulation
https://wokwi.com/projects/480557389545852929

## Team
 syeda saniyah , pushpalatha kn , chinmayee hr
 
