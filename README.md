# Laptop Touch Control

**Control your Windows laptop from your phone.** See the screen live, tap anywhere to click exactly there, type with your phone keyboard, or drive the cursor with an on-screen joystick.

Works on your home Wi-Fi — or from anywhere in the world over [Tailscale](https://tailscale.com).

No account. No third-party servers. **Your screen never leaves your devices.**

![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Android-blue)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

<!--
  Screenshots: drop images into a screenshots/ folder, then uncomment this block.
  Recommended: lock screen, touch mode in use, keyboard panel (portrait phone).

<p align="center">
  <img src="screenshots/lock.png" width="24%">
  <img src="screenshots/touch-mode.png" width="24%">
  <img src="screenshots/keyboard.png" width="24%">
</p>
-->

---

## Features

| | Feature |
|---|---|
| 🖥️ | **Live screen** — MJPEG stream, up to 30 FPS, adjustable |
| 🎯 | **Tap to click** — tap the screen and the cursor clicks exactly there, like a real touchscreen |
| 🔴 | **Visible cursor** — a red marker is drawn on every frame so you never lose the pointer |
| 🕹️ | **Joystick mode** — hold the stick for smooth, continuous cursor movement (great for gaming/design) |
| 👆 | **Gestures** — long-press = right click, double-tap = double click, press-and-drag = drag/select |
| ⌨️ | **Keyboard** — type with your phone keyboard + Esc/Tab/Enter/arrows/Ctrl+C/V/Z/Alt+Tab/Win+D |
| 🔒 | **PIN lock** — with brute-force protection (5 tries, then exponential lockout) |
| 📷 | **QR pairing** — scan the code in the terminal and you are connected |
| 🌍 | **Anywhere access** — via Tailscale, no port forwarding needed |
| 🔋 | **Auto pause** — stops streaming and screen capture when you leave the app |
| 📴 | **Idle friendly** — the laptop stops capturing entirely when nobody is watching |

---

## Quick start

### Option A — prebuilt (easiest)

1. Grab **`LaptopControl.exe`** and **`LaptopControl.apk`** from the
   [Releases](../../releases) page.
2. Put the exe anywhere on your laptop and double-click it. A console window
   opens showing your addresses and a **QR code**.
   - First launch takes ~15-25 s (it unpacks itself). Normal.
   - Windows may warn about an unknown publisher → **More info → Run anyway**
     (it is an unsigned build).
   - Allow it through the firewall when asked (Private networks).
3. Install the APK on your Android phone (allow install from unknown sources).
4. Open the app → **Scan QR code** → point at the console. Connected.

> **Set a PIN first.** Create a file called `remote_config.txt` next to the exe:
> ```
> PIN=582914
> ```
> Without a PIN, anyone on your network who finds the address can control your laptop.

### Option B — run from source

```bash
pip install -r requirements.txt
python server.py
```

Then open the printed URL on your phone, or scan the QR with the app.

Optional environment variables:

| Variable | Meaning |
|---|---|
| `REMOTE_PIN=582914` | Require this PIN to control the laptop |
| `REMOTE_BIND=100.x.x.x` | Only listen on this interface (e.g. Tailscale only) |
| `REMOTE_SECRET=...` | Fixed Flask session secret |

---

## How it works

```
┌──────────────────┐        MJPEG screen stream (HTTP)        ┌─────────────────┐
│                  │  ──────────────────────────────────────▶ │                 │
│   LAPTOP         │                                          │   PHONE         │
│   server.py      │  ◀────────────────────────────────────── │   web page      │
│                  │     touch / keys / joystick (WebSocket)  │   or Android app│
└──────────────────┘                                          └─────────────────┘
```

- **`server.py`** captures the screen with `mss`, draws the cursor marker,
  encodes JPEG frames, and streams them. It also receives input events and
  replays them with `pynput` (real mouse + keyboard events).
- **`static/`** is the control UI — plain HTML/CSS/JS, no build step. It runs in
  any phone browser *and* inside the Android app's WebView.
- **`android-app/`** is a thin Kotlin shell: QR scanner to pair, then a
  full-screen WebView.

Because the UI is served by the laptop, it reloads fresh every time you open the
app — no APK update needed for UI changes.

---

## Access from anywhere (free)

1. Install **Tailscale** on the laptop and the phone, sign in with the same
   account.
2. Start the server — it prints your `100.x.x.x` address (and puts it in the QR).
3. Use that address from any network: mobile data, hotel Wi-Fi, anywhere.

Tailscale encrypts the traffic end-to-end (WireGuard) and only your own devices
can reach it. **Never port-forward port 8080 on your router** — that exposes the
server to the whole internet.

---

## Security — please read

Whoever has the **PIN** *and* can **reach the address** has full control of the
laptop (mouse + keyboard = everything you can do). Two gates protect you:

**1. Network reachability**
- Default: only devices on your own Wi-Fi / LAN.
- With Tailscale: only devices signed into *your* Tailscale account.
- Never port-forward the port. Use Tailscale instead.

**2. The PIN**
- Set it in `remote_config.txt` (or `REMOTE_PIN`).
- Rate limited: 5 wrong tries → 60 s lockout, doubling each round (max 1 h).
- The WebSocket control channel drops after 5 wrong tries.
- Every protected route returns 401 without it — nothing leaks.
- Use 6+ digits. `1234` is not a password.

**Known limitation:** over plain HTTP on an *untrusted* network the PIN travels
in cleartext. Over Tailscale the traffic is encrypted, so prefer it when you are
away from home. This is a personal-use tool, not a hardened enterprise product.

---

## Building it yourself

### Windows .exe
```bash
pip install pyinstaller
pyinstaller --onefile --console --name LaptopControl --icon app_icon.ico \
  --add-data "static;static" --hidden-import pynput.keyboard._win32 \
  --hidden-import pynput.mouse._win32 server.py
```
Output: `dist/LaptopControl.exe`

### Android APK
- Open the `android-app` folder in **Android Studio** and press
  *Build → Build APK(s)*, or
- let GitHub build it: every push triggers
  [`.github/workflows/build-android.yml`](.github/workflows/build-android.yml)
  and uploads the APK as a build artifact (no Android Studio needed).

See [`android-app/BUILD_GUIDE.md`](android-app/BUILD_GUIDE.md) for details.

---

## Project structure

```
.
├── server.py                  # capture + stream + input injection + PIN auth
├── static/
│   ├── index.html             # phone UI markup + SVG icons
│   ├── style.css              # design system (dark "emerald & charcoal")
│   └── app.js                 # touch gestures, socket, pause/resume
├── requirements.txt
├── remote_config.example.txt  # copy to remote_config.txt and set a PIN
├── start_server.bat           # convenience launcher (Windows)
├── app_icon.ico               # icon for the .exe and the app
├── LaptopControl.spec         # PyInstaller recipe
└── android-app/               # Kotlin WebView app (QR scanner + full screen)
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Phone cannot open the page | Allow Python/the exe through the firewall (Private networks); make sure both devices are on the same Wi-Fi or both on Tailscale |
| App connects but screen stays black | The laptop screen capture is blocked by DRM/protected content, or the stream was paused — switch away and back to the app to resume |
| Mouse feels laggy | Lower `CAPTURE_FPS` or `JPEG_QUALITY` at the top of `server.py`; keep the phone close to the router |
| Campus/office Wi-Fi blocks it | Many such networks isolate clients from each other. Use Tailscale (or your home Wi-Fi) |
| "Install from unknown sources" warning | Normal for an unsigned APK — allow it |
| SmartScreen "unknown publisher" on the exe | **More info → Run anyway** |

---

## Contributing

Issues and pull requests are welcome. Ideas that would fit nicely:
- pinch-to-zoom on the screen view
- two-finger swipe to scroll, two-finger tap for middle click
- H.264 / WebRTC video for lower latency
- audio streaming, file transfer

---

## License

[MIT](LICENSE) — use it, modify it, ship it.

## Disclaimer

Built for controlling **your own** computer from **your own** phone. Only remote
into machines you own or have explicit permission to access.
