"use strict";

/* ================= state ================= */
let mode = "touch";            // "touch" | "joystick"
let rightClickArmed = false;   // cursor button: next tap = right-click
let screenW = 1920, screenH = 1080;
let ws = null, wsOpen = false, manualClose = false;
let savedPin = localStorage.getItem("rtc_pin") || "";

const $ = id => document.getElementById(id);
const screenImg = $("screen");
const toastEl = $("toast");
const toolbar = $("toolbar");
const hudGrab = $("hud-grab");

function toast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add("show");
  clearTimeout(toastEl._t);
  toastEl._t = setTimeout(() => toastEl.classList.remove("show"), 1600);
}

function buzz(ms) { try { navigator.vibrate && navigator.vibrate(ms); } catch (_) {} }

/* visual confirmation ring where the finger tapped */
function tapRing(x, y, kind) {
  const el = document.createElement("div");
  el.className = "tap-ring" + (kind === "right" ? " right" : "");
  el.style.left = x + "px";
  el.style.top = y + "px";
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 500);
}

function setStatus(state) {   // "ok" | "warn" | "off"
  hudGrab.className = "";
  if (state !== "off") hudGrab.classList.add(state);
}

/* ================= HUD show/hide (grab handle ONLY) ================= */
/* Screen taps never open the toolbar, so the top of the laptop screen
   (browser tabs, menus) always stays clickable. The bar opens only from
   the grab pill and tucks itself away after 3.5s. */
let hudTimer = null;
function showHud() {
  toolbar.classList.remove("hud-hidden");
  hudGrab.classList.add("ghost");
  clearTimeout(hudTimer);
  hudTimer = setTimeout(() => {
    if (!kbPanel.classList.contains("open")) {
      toolbar.classList.add("hud-hidden");
      hudGrab.classList.remove("ghost");
    }
  }, 3500);
}
hudGrab.addEventListener("touchstart", e => {
  e.preventDefault();
  buzz(6);
  if (toolbar.classList.contains("hud-hidden")) {
    showHud();
  } else {
    clearTimeout(hudTimer);
    toolbar.classList.add("hud-hidden");
    hudGrab.classList.remove("ghost");
  }
}, { passive: false });
toolbar.addEventListener("touchstart", () => showHud(), { passive: true });
showHud();

/* ================= network (WebSocket + HTTP fallback) ================= */
function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(proto + "//" + location.host + "/ws");
  ws.onopen = () => {
    if (savedPin) ws.send(JSON.stringify({ type: "auth", pin: savedPin }));
    wsOpen = true;
    setStatus("ok");
  };
  ws.onmessage = e => {
    try {
      const m = JSON.parse(e.data);
      if (m.type === "auth" && m.ok === false) {
        toast("Wrong PIN - control blocked");
        setStatus("warn");
      }
    } catch (_) {}
  };
  ws.onclose = () => {
    wsOpen = false;
    setStatus("warn");
    if (!manualClose) setTimeout(connectWS, 1000);
    manualClose = false;
  };
  ws.onerror = () => { try { ws.close(); } catch (_) {} };
}

function send(payload) {
  const msg = JSON.stringify(payload);
  if (wsOpen && ws.readyState === 1) ws.send(msg);
  else fetch("/input", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: msg }).catch(() => {});
}

/* ================= PIN lock ================= */
async function checkAuth() {
  try {
    const r = await fetch("/auth/status");
    const s = await r.json();
    if (s.pin_required && !s.authed) {
      $("lock").classList.add("show");
      $("loader").classList.add("gone");
    } else {
      startStream();
    }
  } catch (_) {
    setStatus("warn");
    setTimeout(checkAuth, 2000);
  }
}

$("pin-go").addEventListener("click", async () => {
  const pin = $("pin-input").value;
  try {
    const r = await fetch("/auth", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: pin }) });
    if (r.ok) {
      savedPin = pin;
      localStorage.setItem("rtc_pin", pin);
      $("lock").classList.remove("show");
      $("pin-err").textContent = "";
      buzz(20);
      connectWS();
      startStream();
    } else if (r.status === 429) {
      $("pin-err").textContent = "Too many tries - locked out. Wait a minute.";
      shakeLock();
    } else {
      $("pin-err").textContent = "Wrong PIN";
      shakeLock();
    }
  } catch (_) {
    $("pin-err").textContent = "Cannot reach server";
  }
});

function shakeLock() {
  const el = $("lock-inner");
  buzz(60);
  el.classList.remove("shake");
  void el.offsetWidth;           // restart animation
  el.classList.add("shake");
}

$("pin-input").addEventListener("keydown", e => {
  if (e.key === "Enter") $("pin-go").click();
});

/* ================= screen stream (with pause / resume) ================= */
let streamLive = false;

function startStream() {
  $("loader").classList.remove("gone");
  screenImg.onload = () => {
    streamLive = true;
    $("loader").classList.add("gone");
  };
  screenImg.src = "/stream?t=" + Date.now();
  fetch("/screen-info").then(r => r.json()).then(info => {
    screenW = info.width;
    screenH = info.height;
  }).catch(() => {});
}

function stopStream() {
  streamLive = false;
  screenImg.onload = null;
  screenImg.removeAttribute("src");   // drops the MJPEG connection
}

/* Pause when the app/tab loses focus - resume seamlessly when it returns.
   Fixes the black screen you got after switching apps. */
function pauseSession() {
  stopStream();
  manualClose = true;
  try { if (ws) ws.close(); } catch (_) {}
  wsOpen = false;
  send({ type: "joystick", x: 0, y: 0 });   // make sure the cursor stops
}

function resumeSession() {
  if (document.hidden) return;
  if (!ws || ws.readyState > WebSocket.OPEN) connectWS();
  if (!streamLive) startStream();
}

window.pauseSession = pauseSession;
window.resumeSession = resumeSession;

document.addEventListener("visibilitychange", () => {
  if (document.hidden) pauseSession();
  else resumeSession();
});
window.addEventListener("pageshow", resumeSession);
window.addEventListener("focus", resumeSession);
/* ================= touch-to-click ================= */
function touchToNorm(touch) {
  const r = screenImg.getBoundingClientRect();
  const x = (touch.clientX - r.left) / r.width;
  const y = (touch.clientY - r.top) / r.height;
  return { nx: Math.min(1, Math.max(0, x)), ny: Math.min(1, Math.max(0, y)) };
}

let tapTimer = null, lastTap = 0, pressTimer = null, pressed = false;
let dragging = false, lastMoveSent = 0, lastTapPos = null;

screenImg.addEventListener("touchstart", e => {
  if (mode !== "touch") return;
  e.preventDefault();
  const t = e.changedTouches[0];
  const now = performance.now();

  pressed = false;
  pressTimer = setTimeout(() => {
    pressed = true;
    const p = touchToNorm(t);
    send({ type: "tap", nx: p.nx, ny: p.ny, button: "right" });
    tapRing(t.clientX, t.clientY, "right");
    buzz(25);
    toast("Right click");
  }, 500);

  if (now - lastTap < 300 && lastTapPos) {
    clearTimeout(pressTimer);
    if (tapTimer) { clearTimeout(tapTimer); tapTimer = null; }
    const p = touchToNorm(t);
    send({ type: "doubletap", nx: p.nx, ny: p.ny });
    tapRing(t.clientX, t.clientY);
    buzz(15);
    lastTap = 0;
    lastTapPos = null;
    return;
  }
  lastTap = now;
  lastTapPos = { x: t.clientX, y: t.clientY };
  dragging = false;
}, { passive: false });

screenImg.addEventListener("touchmove", e => {
  if (mode !== "touch") return;
  e.preventDefault();
  const t = e.changedTouches[0];
  const p = touchToNorm(t);
  const now = performance.now();

  if (!dragging && lastTapPos) {
    const moved = Math.hypot(t.clientX - lastTapPos.x, t.clientY - lastTapPos.y);
    if (moved > 18) {
      clearTimeout(pressTimer);
      dragging = true;
      lastTap = 0;
      lastTapPos = null;
      send({ type: "move", nx: p.nx, ny: p.ny });
      send({ type: "mousedown", button: "left" });
    }
  }
  if (dragging && now - lastMoveSent > 33) {
    lastMoveSent = now;
    send({ type: "move", nx: p.nx, ny: p.ny });
  }
}, { passive: false });

screenImg.addEventListener("touchend", e => {
  if (mode !== "touch") return;
  e.preventDefault();
  clearTimeout(pressTimer);
  const t = e.changedTouches[0];
  const p = touchToNorm(t);

  if (pressed) { pressed = false; lastTap = 0; lastTapPos = null; return; }
  if (dragging) {
    dragging = false;
    send({ type: "mouseup", button: "left" });
    return;
  }
  if (lastTap === 0) return;

  const fx = t.clientX, fy = t.clientY;
  const armedRight = rightClickArmed;
  tapTimer = setTimeout(() => {
    tapTimer = null;
    lastTap = 0;
    lastTapPos = null;
    const btn = armedRight ? "right" : "left";
    if (armedRight) setRightClickArmed(false);
    send({ type: "tap", nx: p.nx, ny: p.ny, button: btn });
    tapRing(fx, fy, btn === "right" ? "right" : "left");
    buzz(8);
  }, 250);
}, { passive: false });

/* ================= joystick mode ================= */
const zone = $("joy-zone");
const knob = $("joy-knob");
const RADIUS = 47;
let joyActive = false, lastJoySent = 0;

function joyVector(touch) {
  const r = zone.getBoundingClientRect();
  const cx = r.left + r.width / 2;
  const cy = r.top + r.height / 2;
  let dx = touch.clientX - cx;
  let dy = touch.clientY - cy;
  const dist = Math.hypot(dx, dy);
  if (dist > RADIUS) { dx *= RADIUS / dist; dy *= RADIUS / dist; }
  knob.style.transform = "translate(calc(-50% + " + dx + "px), calc(-50% + " + dy + "px))";
  return { x: dx / RADIUS, y: dy / RADIUS };
}

zone.addEventListener("touchstart", e => {
  e.preventDefault();
  joyActive = true;
  buzz(8);
  const v = joyVector(e.changedTouches[0]);
  send({ type: "joystick", x: v.x, y: v.y });
}, { passive: false });

zone.addEventListener("touchmove", e => {
  e.preventDefault();
  if (!joyActive) return;
  const now = performance.now();
  if (now - lastJoySent < 16) return;
  lastJoySent = now;
  const v = joyVector(e.changedTouches[0]);
  send({ type: "joystick", x: v.x, y: v.y });
}, { passive: false });

function joyEnd(e) {
  e.preventDefault();
  joyActive = false;
  knob.style.transform = "translate(-50%, -50%)";
  send({ type: "joystick", x: 0, y: 0 });
}
zone.addEventListener("touchend", joyEnd, { passive: false });
zone.addEventListener("touchcancel", joyEnd, { passive: false });

/* ================= segmented mode control ================= */
function setMode(m, quiet) {
  mode = m;
  localStorage.setItem("rtc_mode", m);   // remembered for next time
  $("seg-touch").classList.toggle("on", m === "touch");
  $("seg-stick").classList.toggle("on", m === "joystick");
  zone.classList.toggle("show", m === "joystick");
  if (!quiet) {
    buzz(8);
    toast(m === "touch" ? "Touch mode - tap the screen to click"
                        : "Stick mode - move the cursor with the stick");
  }
}
$("seg-touch").addEventListener("click", () => setMode("touch"));
$("seg-stick").addEventListener("click", () => setMode("joystick"));

/* ================= right-click arm toggle ================= */
function setRightClickArmed(on) {
  rightClickArmed = on;
  $("btn-rtoggle").style.color = on ? "var(--amber)" : "";
  $("btn-rtoggle").style.borderColor = on ? "rgba(251,191,36,0.5)" : "";
  toast(on ? "Next tap = right click" : "Right-click mode off");
}
$("btn-rtoggle").addEventListener("click", () => setRightClickArmed(!rightClickArmed));

/* ================= click / scroll buttons ================= */
function bindClick(id, button) {
  const el = $(id);
  const fire = e => { e.preventDefault(); buzz(8); send({ type: "click", button: button }); };
  el.addEventListener("touchstart", fire, { passive: false });
}
bindClick("cbtn-left", "left");
bindClick("cbtn-right", "right");

function bindScroll(id, dy) {
  $(id).addEventListener("touchstart", e => {
    e.preventDefault(); buzz(6); send({ type: "scroll", dx: 0, dy: dy });
  }, { passive: false });
}
bindScroll("btn-scup", 1);
bindScroll("btn-scdn", -1);

/* ================= keyboard sheet ================= */
const kbPanel = $("kb-panel");
const kbInput = $("kb-input");

$("btn-kb").addEventListener("click", () => {
  kbPanel.classList.toggle("open");
  $("btn-kb").style.color = kbPanel.classList.contains("open") ? "var(--accent)" : "";
  showHud(); if (kbPanel.classList.contains("open")) kbInput.focus();
  else kbInput.blur();
});

kbInput.addEventListener("input", () => {
  const text = kbInput.value;
  if (text) {
    for (const ch of text) send({ type: "key", key: ch });
    kbInput.value = "";
  }
});
kbInput.addEventListener("keydown", e => {
  if (e.key === "Backspace") { send({ type: "key", key: "backspace" }); e.preventDefault(); }
  else if (e.key === "Enter") { send({ type: "key", key: "enter" }); e.preventDefault(); }
});

document.querySelectorAll(".kbtn").forEach(btn => {
  btn.addEventListener("touchstart", e => {
    e.preventDefault();
    buzz(6);
    if (btn.dataset.combo) {
      send({ type: "combo", keys: btn.dataset.combo.split(",") });
    } else if (btn.dataset.key) {
      send({ type: "key", key: btn.dataset.key });
    }
  }, { passive: false });
});

/* ================= boot ================= */
connectWS();
checkAuth();
const savedMode = localStorage.getItem("rtc_mode");
if (savedMode === "joystick") setMode("joystick", true);
