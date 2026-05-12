"""keep_alive.py — Health check server para Render + UptimeRobot"""
from flask import Flask
from threading import Thread
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ KittyTimer — Online", 200

@app.route('/health')
def health():
    return "OK", 200

def run():
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True  # ← daemon=True para que no bloquee el proceso principal
    t.start()
