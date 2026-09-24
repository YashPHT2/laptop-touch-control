"""
Laptop Screen + Touch Control Server  (v2 - professional edition)
==================================================================
Features:
  * Live screen stream (MJPEG) with the mouse cursor drawn on each frame,
    so you can always see the pointer on your phone.
  * Touch-to-click: tapping the screen view moves the cursor to that exact
    spot and clicks - like a real touchscreen.
  * Joystick mode for precise cursor movement.
  * Full keyboard: phone keyboard + special keys + shortcuts.
  * PIN lock (optional but recommended when using over the internet).
  * Live settings API (quality / fps / cursor overlay).
  * Works over the internet when both devices run Tailscale.

Usage:
    pip install -r requirements.txt
    python server.py
"""

import io
import json
import os
import secrets
import socket
import sys
import threading
import time

import mss
from flask import Flask, Response, jsonify, request, send_from_directory, session
from flask_sock import Sock
from PIL import Image, ImageDraw
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key as KbKey
from pynput.mouse import Button, Controller as MouseController

try:
    import qrcode
    HAVE_QR = True
except ImportError:
    HAVE_QR = False

HOST = os.environ.get("REMOTE_BIND", "0.0.0.0")  # set REMOTE_BIND=<tailscale-ip> to allow ONLY tailnet devices
PORT = 8080
JPEG_QUALITY = 60
CAPTURE_FPS = 30
MOUSE_TICK = 1 / 120.0
JOYSTICK_SPEED = 14                         # px per tick at full deflection
SECRET_KEY = os.environ.get("REMOTE_SECRET") or secrets.token_hex(16)

# ----------------------------------------------------------------------------
# Path handling - works both as a script and as a PyInstaller .exe
# ----------------------------------------------------------------------------
def resource_path(rel):
    """Where bundled files live (static/ is inside the .exe when frozen)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

def exe_dir():
    """Folder the .exe (or script) lives in - for remote_config.txt."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def load_pin():
    """PIN from REMOTE_PIN env var, else from remote_config.txt (PIN=....)."""
    pin = os.environ.get("REMOTE_PIN", "")
    if pin:
        return pin
    try:
        with open(os.path.join(exe_dir(), "remote_config.txt"),
                  encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.upper().startswith("PIN="):
                    return line[4:].strip()
    except OSError:
        pass
    return ""

PIN = load_pin()

app = Flask(__name__, static_folder=resource_path("static"), static_url_path="")
app.secret_key = SECRET_KEY
sock = Sock(app)
mouse = MouseController()
keyboard = KeyboardController()

_capture_lock = threading.Lock()            # guards _settings
_settings = {
    "quality": JPEG_QUALITY,                # 10-95
    "fps": CAPTURE_FPS,                     # 5-60
    "show_cursor": True,                    # draw cursor overlay on stream
    "scale": 1.0,                           # 0.25-1.0 downscale for bandwidth
}

_frame_lock = threading.Lock()
_latest_jpeg = None

_stream_lock = threading.Lock()
_stream_clients = 0                         # phones currently watching the stream

_joy_lock = threading.Lock()
_joy_vector = (0.0, 0.0)

_screen_w = 1920                            # updated by the capture thread
_screen_h = 1080

_pair_url = None                            # set at startup, used by /qr.png

SPECIAL_KEYS = {
    "enter": KbKey.enter, "backspace": KbKey.backspace, "tab": KbKey.tab,
    "escape": KbKey.esc, "space": KbKey.space, "up": KbKey.up,
    "down": KbKey.down, "left": KbKey.left, "right": KbKey.right,
    "delete": KbKey.delete, "home": KbKey.home, "end": KbKey.end,
    "pageup": KbKey.page_up, "pagedown": KbKey.page_down,
    "shift": KbKey.shift, "ctrl": KbKey.ctrl, "alt": KbKey.alt,
    "win": KbKey.cmd,
}

BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}

# ----------------------------------------------------------------------------
# Brute-force protection for the PIN
# ----------------------------------------------------------------------------
AUTH_MAX_TRIES = 5              # wrong tries before lockout
AUTH_LOCKOUT_SECS = 60          # first lockout length (doubles each time, max 1h)

_auth_lock = threading.Lock()
_auth_fail = {}                 # ip -> [fail_count, lockout_until_epoch, lockout_rounds]

def _auth_allowed(ip):
    with _auth_lock:
        rec = _auth_fail.get(ip)
        return not (rec and time.time() < rec[1])

def _auth_failed(ip):
    with _auth_lock:
        rec = _auth_fail.setdefault(ip, [0, 0.0, 0])
        rec[0] += 1
        if rec[0] >= AUTH_MAX_TRIES:
            dur = min(3600, AUTH_LOCKOUT_SECS * (2 ** rec[2]))
            rec[2] += 1
            rec[1] = time.time() + dur
            rec[0] = 0
            print(f"[security] {ip} locked out for {dur}s (too many wrong PINs)")

def _auth_success(ip):
    with _auth_lock:
        _auth_fail.pop(ip, None)

# ----------------------------------------------------------------------------
# Auth helpers
# ----------------------------------------------------------------------------
def pin_required():
    return bool(PIN)

def is_authed():
    return (not pin_required()) or session.get("auth") is True

def require_auth():
    """Return a 401 response when a PIN is set and the client is not authed."""
    if not is_authed():
        return jsonify({"ok": False, "error": "auth_required"}), 401
    return None

# ----------------------------------------------------------------------------
# Screen capture thread (with cursor overlay)
# ----------------------------------------------------------------------------
def capture_loop():
    """Grab the primary monitor, draw the cursor on it, encode to JPEG."""
    global _latest_jpeg, _screen_w, _screen_h
    with mss.MSS() as sct:
        monitor = sct.monitors[1]
        _screen_w, _screen_h = monitor["width"], monitor["height"]
        while True:
            # nobody is watching - idle so the laptop stays cool and quiet
            with _stream_lock:
                watchers = _stream_clients
            if watchers == 0:
                time.sleep(0.25)
                continue

            start = time.perf_counter()
            with _capture_lock:
                quality = _settings["quality"]
                fps = _settings["fps"]
                show_cursor = _settings["show_cursor"]
                scale = _settings["scale"]

            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

            if show_cursor:
                cx, cy = mouse.position
                cx -= monitor["left"]
                cy -= monitor["top"]
                d = ImageDraw.Draw(img)
                r = 9
                d.ellipse((cx - r, cy - r, cx + r, cy + r),
                          outline=(255, 60, 60), width=3)
                d.ellipse((cx - 2, cy - 2, cx + 2, cy + 2),
                          fill=(255, 60, 60))

            if scale != 1.0:
                img = img.resize((int(img.width * scale),
                                  int(img.height * scale)),
                                 Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            with _frame_lock:
                _latest_jpeg = buf.getvalue()

            elapsed = time.perf_counter() - start
            frame_time = 1.0 / max(5, min(60, fps))
            if elapsed < frame_time:
                time.sleep(frame_time - elapsed)

# ----------------------------------------------------------------------------
# Joystick thread
# ----------------------------------------------------------------------------
def joystick_loop():
    while True:
        with _joy_lock:
            vx, vy = _joy_vector
        if vx != 0.0 or vy != 0.0:
            dx = JOYSTICK_SPEED * vx * abs(vx)
            dy = JOYSTICK_SPEED * vy * abs(vy)
            pos = mouse.position
            mouse.position = (pos[0] + dx, pos[1] + dy)
        time.sleep(MOUSE_TICK)

# ----------------------------------------------------------------------------
# Input event handling
# ----------------------------------------------------------------------------
def apply_event(data):
    """Apply one control event received from the phone."""
    etype = data.get("type")

    if etype == "joystick":
        global _joy_vector
        x = max(-1.0, min(1.0, float(data.get("x", 0))))
        y = max(-1.0, min(1.0, float(data.get("y", 0))))
        with _joy_lock:
            _joy_vector = (x, y)

    elif etype == "move":
        # {type:"move", nx:0..1, ny:0..1} - normalized screen position.
        nx = max(0.0, min(1.0, float(data.get("nx", 0))))
        ny = max(0.0, min(1.0, float(data.get("ny", 0))))
        mouse.position = (int(nx * _screen_w), int(ny * _screen_h))

    elif etype == "tap":
        # tap = move + click in one gesture
        nx = max(0.0, min(1.0, float(data.get("nx", 0))))
        ny = max(0.0, min(1.0, float(data.get("ny", 0))))
        button = BUTTONS.get(data.get("button", "left"), Button.left)
        mouse.position = (int(nx * _screen_w), int(ny * _screen_h))
        mouse.click(button)

    elif etype == "doubletap":
        nx = max(0.0, min(1.0, float(data.get("nx", 0))))
        ny = max(0.0, min(1.0, float(data.get("ny", 0))))
        mouse.position = (int(nx * _screen_w), int(ny * _screen_h))
        mouse.click(Button.left, 2)

    elif etype == "click":
        mouse.click(BUTTONS.get(data.get("button", "left"), Button.left))

    elif etype in ("mousedown", "mouseup"):
        b = BUTTONS.get(data.get("button", "left"), Button.left)
        if etype == "mousedown":
            mouse.press(b)
        else:
            mouse.release(b)

    elif etype == "scroll":
        mouse.scroll(int(data.get("dx", 0)), int(data.get("dy", 0)))

    elif etype == "key":
        key = str(data.get("key", ""))
        if not key:
            return
        special = SPECIAL_KEYS.get(key.lower())
        if special is not None:
            keyboard.press(special)
            keyboard.release(special)
        else:
            keyboard.type(key)

    elif etype == "combo":
        keys = [SPECIAL_KEYS.get(k.lower()) or k for k in data.get("keys", [])]
        if keys:
            for k in keys:
                keyboard.press(k)
            for k in reversed(keys):
                keyboard.release(k)

@sock.route("/ws")
def ws_input(ws):
    """Low-latency input channel. When a PIN is set, the first message
    must be {"type":"auth","pin":"...."}. Brute-force attempts close the
    connection."""
    authed = not pin_required()
    tries = 0
    while True:
        raw = ws.receive()
        if raw is None:
            break
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not authed:
            if msg.get("type") == "auth" and str(msg.get("pin", "")) == PIN:
                authed = True
                ws.send(json.dumps({"type": "auth", "ok": True}))
            else:
                tries += 1
                ws.send(json.dumps({"type": "auth", "ok": False}))
                if tries >= 5:
                    break          # too many wrong PINs -> drop connection
            continue
        try:
            apply_event(msg)
        except Exception:
            pass

# ----------------------------------------------------------------------------
# HTTP routes
# ----------------------------------------------------------------------------
def mjpeg_stream():
    """MJPEG generator - one stream per connected phone."""
    global _stream_clients
    with _stream_lock:
        _stream_clients += 1
    boundary = b"--frame"
    last_sent = None
    try:
        while True:
            with _frame_lock:
                frame = _latest_jpeg
            if frame is not None and frame is not last_sent:
                last_sent = frame
                yield (boundary + b"\r\nContent-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(frame)).encode() +
                       b"\r\n\r\n" + frame + b"\r\n")
            else:
                time.sleep(0.004)
    finally:
        # runs when the phone closes the page / goes to background
        with _stream_lock:
            _stream_clients -= 1

@app.route("/")
def index():
    return send_from_directory(resource_path("static"), "index.html")

@app.route("/auth", methods=["POST"])
def auth():
    """PIN login. POST {"pin": "1234"}. Rate-limited per IP."""
    if not pin_required():
        return jsonify({"ok": True, "pin_required": False})
    ip = request.remote_addr or "unknown"
    if not _auth_allowed(ip):
        return jsonify({"ok": False, "error": "locked_out"}), 429
    data = request.get_json(silent=True) or {}
    if str(data.get("pin", "")) == PIN:
        _auth_success(ip)
        session["auth"] = True
        return jsonify({"ok": True})
    _auth_failed(ip)
    return jsonify({"ok": False}), 401

@app.route("/auth/status")
def auth_status():
    return jsonify({"pin_required": pin_required(), "authed": is_authed()})

@app.route("/stream")
def stream():
    guard = require_auth()
    if guard:
        return guard
    return Response(mjpeg_stream(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/screen-info")
def screen_info():
    """Phone needs the real resolution to map touch coordinates."""
    guard = require_auth()
    if guard:
        return guard
    return jsonify({"width": _screen_w, "height": _screen_h})

@app.route("/settings", methods=["GET", "POST"])
def settings_api():
    guard = require_auth()
    if guard:
        return guard
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        with _capture_lock:
            if "quality" in data:
                _settings["quality"] = max(10, min(95, int(data["quality"])))
            if "fps" in data:
                _settings["fps"] = max(5, min(60, int(data["fps"])))
            if "show_cursor" in data:
                _settings["show_cursor"] = bool(data["show_cursor"])
            if "scale" in data:
                _settings["scale"] = max(0.25, min(1.0, float(data["scale"])))
    with _capture_lock:
        return jsonify(dict(_settings))

@app.route("/qr.png")
def qr_png():
    """QR code encoding the pair URL. Public on purpose: the URL is not
    a secret - the PIN protects control."""
    if not HAVE_QR or not _pair_url:
        return "QR unavailable (pip install qrcode[pil])", 501
    img = qrcode.make(_pair_url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")

@app.route("/input", methods=["POST"])
def handle_input():
    """HTTP fallback input channel."""
    guard = require_auth()
    if guard:
        return guard
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "bad json"}), 400
    apply_event(data)
    return jsonify({"ok": True})

# ----------------------------------------------------------------------------
# Startup
# ----------------------------------------------------------------------------
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def get_tailscale_ip():
    """Best-effort: ask the tailscale CLI for our 100.x address."""
    try:
        import subprocess
        out = subprocess.run(["tailscale", "ip", "-4"],
                             capture_output=True, text=True, timeout=5)
        ip = out.stdout.strip().splitlines()[0]
        if ip.startswith("100."):
            return ip
    except Exception:
        pass
    return None

if __name__ == "__main__":
    # the console QR needs block characters - force UTF-8 output on Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    threading.Thread(target=capture_loop, daemon=True).start()
    threading.Thread(target=joystick_loop, daemon=True).start()

    local_ip = get_local_ip()
    ts_ip = get_tailscale_ip()
    _pair_url = f"http://{ts_ip or local_ip}:{PORT}"

    print("=" * 60)
    print("  Laptop Screen + Touch Control server is running!")
    print("=" * 60)
    print(f"  Same Wi-Fi:   http://{local_ip}:{PORT}")
    if ts_ip:
        print(f"  Anywhere (Tailscale): http://{ts_ip}:{PORT}")
    else:
        print("  Anywhere: install Tailscale on laptop + phone,")
        print("            then use the 100.x.x.x address it gives you.")
    if pin_required():
        print("  PIN lock: ENABLED")
    else:
        print("  PIN lock: disabled (set REMOTE_PIN=1234 to enable)")
    print("-" * 60)
    print("  Scan this QR with the app (or phone camera) to pair:")
    print()
    if HAVE_QR:
        try:
            q = qrcode.QRCode(border=1)
            q.add_data(_pair_url)
            q.print_ascii(invert=True)
        except Exception as e:
            print(f"  (QR print failed: {e}) - QR image: {_pair_url}/qr.png")
    else:
        print(f"  (install qrcode[pil] for console QR) QR image: {_pair_url}/qr.png")
    print("=" * 60)
    print("  Press Ctrl+C to stop.")

    app.run(host=HOST, port=PORT, threaded=True)
