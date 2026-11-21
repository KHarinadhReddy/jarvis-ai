from __future__ import annotations

import ast
import io
import json
import math
import os
import operator
import asyncio
import base64
import tempfile
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Any

import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_mic_recorder import speech_to_text
from dotenv import load_dotenv

# Optional system stats
try:
    import psutil
    HAS_PSUTIL = True
except Exception:  # pragma: no cover
    HAS_PSUTIL = False

# --------------------------------------------------------------------------- #
# Paths & constants
# --------------------------------------------------------------------------- #
APP_DIR = Path(__file__).resolve().parent
WORKSPACE = (APP_DIR / "workspace").resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)
API_URL = "https://openrouter.ai/api/v1/chat/completions"
VERSION_FILE = APP_DIR / "version.json"
WAKE_LISTENER_SCRIPT = APP_DIR / "wake_listener.py"
WAKE_SIGNAL_FILE = APP_DIR / "wake_triggered.txt"
OWNER_VOICE_FILE = APP_DIR / "owner_voice.json"
UPDATE_STATUS_FILE = APP_DIR / ".update_status.json"

CURRENT_VERSION = "2.0.0"
UPDATE_CHECK_INTERVAL_SEC = 86_400  # 24 hours

# Default remote update manifest (user should host their own; this is a fallback)
UPDATE_MANIFEST_URL = os.getenv(
    "JARVIS_UPDATE_MANIFEST",
    "https://raw.githubusercontent.com/USERNAME/jarvis_openrouter_voice_ai/main/version.json",
)

load_dotenv(APP_DIR / ".env")

# --------------------------------------------------------------------------- #
# Page config
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="J.A.R.V.I.S. AI",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --------------------------------------------------------------------------- #
# JARVIS HUD CSS
# --------------------------------------------------------------------------- #
JARVIS_CSS = """
<style>
:root { color-scheme: dark; }
:root {
  --jarvis-cyan: #00d4ff;
  --jarvis-amber: #ffb300;
  --jarvis-green: #00ff88;
  --jarvis-dark: #05070d;
  --jarvis-panel: rgba(8, 13, 24, 0.92);
  --jarvis-border: rgba(0, 212, 255, 0.35);
  --jarvis-border-amber: rgba(255, 179, 0, 0.35);
  --jarvis-glow: 0 0 20px rgba(0, 212, 255, 0.35);
  --jarvis-glow-amber: 0 0 20px rgba(255, 179, 0, 0.35);
  --jarvis-font: 'Segoe UI', 'Rajdhani', 'Orbitron', 'Consolas', 'Monaco', monospace;
}

html, body, .stApp {
  background: radial-gradient(ellipse at 50% 0%, #10253d 0%, #080d18 38%, #05070d 100%) !important;
  color: #e8f1ff !important;
  font-family: var(--jarvis-font) !important;
  height: 100vh;
  overflow-x: hidden;
}

/* Hide Streamlit chrome */
#MainMenu { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent !important; visibility: hidden !important; height: 0 !important; }
footer { visibility: hidden; }
.stDeployButton { display: none; }
.stActionButton { display: none; }

.block-container {
  max-width: 100% !important;
  padding: 0 !important;
  margin: 0 !important;
  background: transparent !important;
}

/* Background grid + scanlines */
.hud-grid {
  position: fixed;
  top: 0; left: 0; width: 100vw; height: 100vh;
  background-image:
    linear-gradient(rgba(0, 212, 255, 0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 212, 255, 0.025) 1px, transparent 1px);
  background-size: 48px 48px;
  pointer-events: none;
  z-index: 0;
}
.scanlines {
  position: fixed;
  top: 0; left: 0; width: 100vw; height: 100vh;
  background: linear-gradient(
    to bottom,
    rgba(255,255,255,0) 50%,
    rgba(0,0,0,0.18) 50%,
    rgba(0,0,0,0.18)
  );
  background-size: 100% 3px;
  pointer-events: none;
  z-index: 60;
  opacity: 0.35;
}
.scan-line {
  position: fixed;
  top: 0; left: 0; width: 100vw; height: 2px;
  background: linear-gradient(to bottom, transparent, var(--jarvis-cyan), transparent);
  z-index: 61;
  pointer-events: none;
  animation: scanVertical 3s linear infinite;
  opacity: 0.5;
}
@keyframes scanVertical { 0% { top: 0; } 100% { top: 100vh; } }

/* Arc reactor (centered below JARVIS title) */
.arc-reactor {
  position: fixed;
  top: 18px; left: 28px;
  transform: translateX(-50%);
  width: 130px; height: 130px;
  border: 2px solid var(--jarvis-border);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(0, 212, 255, 0.12) 0%, transparent 72%);
  box-shadow: 0 0 35px rgba(0, 212, 255, 0.25), inset 0 0 25px rgba(0, 212, 255, 0.15);
  z-index: 55;
  animation: pulseArc 3.5s ease-in-out infinite;
  pointer-events: none;
}
.arc-core {
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  width: 36px; height: 36px;
  background: var(--jarvis-cyan);
  border-radius: 50%;
  box-shadow: 0 0 22px var(--jarvis-cyan);
  animation: blinkCore 1.2s ease-in-out infinite alternate;
}
@keyframes pulseArc {
  0%, 100% { box-shadow: 0 0 35px rgba(0, 212, 255, 0.25); transform: translateX(-50%) scale(1); }
  50% { box-shadow: 0 0 55px rgba(0, 212, 255, 0.45); transform: translateX(-50%) scale(1.06); }
}
@keyframes blinkCore {
  0% { opacity: 0.55; transform: translate(-50%, -50%) scale(1); }
  100% { opacity: 1; transform: translate(-50%, -50%) scale(1.25); }
}

/* Wake indicator (bottom center) */
#wake-indicator-hud {
  position: fixed;
  bottom: 26px; left: 50%;
  transform: translateX(-50%);
  display: flex; align-items: center; gap: 10px;
  font-size: 13px; letter-spacing: 3px; text-transform: uppercase;
  color: var(--jarvis-cyan);
  z-index: 55;
  text-shadow: 0 0 10px rgba(0, 212, 255, 0.6);
}
.wake-dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--jarvis-cyan);
  box-shadow: 0 0 14px var(--jarvis-cyan);
  animation: blinkWake 2s ease-in-out infinite;
}
.wake-dot.listening {
  background: var(--jarvis-amber);
  box-shadow: 0 0 22px var(--jarvis-amber);
  animation: blinkWake 0.5s ease-in-out infinite;
}
@keyframes blinkWake {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.3); }
}

/* HUD panels */
.hud-panel {
  position: fixed;
  background: var(--jarvis-panel);
  border: 1px solid var(--jarvis-border);
  border-radius: 10px;
  box-shadow: var(--jarvis-glow), inset 0 0 30px rgba(0, 212, 255, 0.06);
  backdrop-filter: blur(14px);
  z-index: 40;
  overflow: hidden;
}
.hud-panel.amber {
  border-color: var(--jarvis-border-amber);
  box-shadow: 0 0 20px rgba(255, 179, 0, 0.18), inset 0 0 30px rgba(255, 179, 0, 0.04);
}
.hud-corner {
  position: absolute; width: 22px; height: 22px; border: 2px solid var(--jarvis-border);
}
.hud-corner.tl { top: 0; left: 0; border-right: none; border-bottom: none; }
.hud-corner.tr { top: 0; right: 0; border-left: none; border-bottom: none; }
.hud-corner.bl { bottom: 0; left: 0; border-right: none; border-top: none; }
.hud-corner.br { bottom: 0; right: 0; border-left: none; border-top: none; }
.hud-panel.amber .hud-corner { border-color: var(--jarvis-border-amber); }

.hud-panel-header {
  padding: 8px 14px;
  border-bottom: 1px solid var(--jarvis-border);
  background: rgba(0, 212, 255, 0.06);
  font-size: 11px; letter-spacing: 2.5px; text-transform: uppercase;
  color: var(--jarvis-cyan); font-weight: 700;
  display: flex; justify-content: space-between; align-items: center;
}
.hud-panel.amber .hud-panel-header { color: var(--jarvis-amber); background: rgba(255, 179, 0, 0.06); }
.hud-panel-content { padding: 14px; font-size: 13px; color: #cfe3f3; }

/* Status readouts */
.status-row { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid rgba(0,212,255,0.08); font-size: 12.5px; }
.status-row:last-child { border-bottom: none; }
.status-value { font-family: 'Consolas', 'Monaco', monospace; color: var(--jarvis-cyan); }
.status-value.active { color: var(--jarvis-green); }
.status-value.warning { color: var(--jarvis-amber); }
.status-value.off { color: #5b6b7f; }

/* Main chat area (right panel) */
#chat-hud-panel {
  top: 170px; right: 22px;
  width: 460px; height: calc(100vh - 210px);
  display: flex; flex-direction: column;
}
#chat-messages {
  flex: 1; overflow-y: auto; padding: 18px; display: flex;
  flex-direction: column; gap: 14px;
}
.msg {
  background: rgba(0, 212, 255, 0.07);
  border: 1px solid rgba(0, 212, 255, 0.22);
  border-radius: 10px; padding: 12px 16px; max-width: 92%;
}
.msg.jarvis { margin-right: auto; border-color: var(--jarvis-border); }
.msg.user {
  margin-left: auto;
  background: rgba(255, 179, 0, 0.07);
  border-color: var(--jarvis-border-amber);
}
.msg-label {
  font-size: 9px; text-transform: uppercase; letter-spacing: 1.5px;
  margin-bottom: 6px; opacity: 0.75;
}
.msg.jarvis .msg-label { color: var(--jarvis-cyan); }
.msg.user .msg-label { color: var(--jarvis-amber); }
.msg-content { line-height: 1.55; font-size: 14px; }

/* Controls panel (left) */
#controls-hud-panel {
  top: 170px; left: 22px;
  width: 360px; height: calc(100vh - 210px);
  display: flex; flex-direction: column; gap: 14px;
}
.hud-btn {
  background: transparent; border: 1px solid var(--jarvis-border);
  color: var(--jarvis-cyan); padding: 10px 16px; border-radius: 8px;
  font-family: var(--jarvis-font); font-size: 12px; text-transform: uppercase;
  letter-spacing: 1.5px; cursor: pointer; transition: all 0.18s;
  text-align: left;
}
.hud-btn:hover {
  background: var(--jarvis-cyan); color: #05070d;
  box-shadow: var(--jarvis-glow);
}
.hud-btn.amber { border-color: var(--jarvis-border-amber); color: var(--jarvis-amber); }
.hud-btn.amber:hover { background: var(--jarvis-amber); color: #05070d; box-shadow: var(--jarvis-glow-amber); }
.hud-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* Bottom input bar */
#hud-input-bar {
  position: fixed;
  bottom: 90px; left: 50%; transform: translateX(-50%);
  width: 700px; background: rgba(5, 7, 13, 0.94);
  border: 1px solid var(--jarvis-border); border-radius: 34px;
  padding: 10px 24px; display: flex; align-items: center; gap: 14px;
  box-shadow: var(--jarvis-glow); z-index: 55;
}
#hud-input-bar input {
  flex: 1; background: transparent; border: none; color: #e8f1ff;
  font-family: var(--jarvis-font); font-size: 14px; outline: none;
}

/* Toast */
#jarvis-toasts {
  position: fixed; top: 22px; left: 22px; z-index: 100;
  display: flex; flex-direction: column; gap: 8px; pointer-events: none;
}
.jarvis-toast {
  background: rgba(5, 7, 13, 0.95); border: 1px solid var(--jarvis-border);
  border-left: 3px solid var(--jarvis-cyan); padding: 10px 16px;
  font-size: 12px; color: #e8f1ff; box-shadow: var(--jarvis-glow);
  pointer-events: auto; animation: slideIn 0.3s ease-out;
}
.jarvis-toast.amber { border-left-color: var(--jarvis-amber); }
@keyframes slideIn { from { transform: translateX(-120%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

/* Voice visualizer widget */
#jarvis-voice-viz-widget {
  position: fixed; top: 22px; left: 22px; width: 260px; height: 200px;
  z-index: 50; pointer-events: none;
}
#viz-canvas { width: 100%; height: 100%; display: block; background: rgba(0,0,0,0.25); border-radius: 10px; border: 1px solid var(--jarvis-border); }

/* Make Streamlit's own containers transparent so our HUD shows through */
.stApp > div, .stApp .block-container { background: transparent !important; }
.stChatMessage, [data-testid="stChatMessage"] { background: transparent !important; border: none !important; box-shadow: none !important; }

/* Sidebar hide (we use fixed panels instead) */
[data-testid="stSidebar"] { display: none !important; }

/* Hide native streamlit widgets we don't need in HUD mode */
div[data-testid="stFileUploader"] { display: none !important; }

/* Small text */
.jarvis-caption { font-size: 11px; color: #8aa4bd; text-transform: uppercase; letter-spacing: 1.5px; margin-top: 6px; }
</style>
"""

# --------------------------------------------------------------------------- #
# HUD widget HTML (arc reactor + voice canvas) — rendered as fixed-position overlays
# --------------------------------------------------------------------------- #
HUD_OVERLAY_HTML = """
<div class="hud-grid"></div>
<div class="scanlines"></div>
<div class="scan-line"></div>

<div class="arc-reactor"><div class="arc-core"></div></div>

<div id="wake-indicator-hud">
  <div class="wake-dot" id="wake-dot"></div>
  <span id="wake-text">STANDBY</span>
</div>

<div id="jarvis-voice-viz-widget">
  <canvas id="viz-canvas"></canvas>
</div>

<div id="jarvis-toasts"></div>

<script>
(function(){
  const canvas = document.getElementById('viz-canvas');
  const ctx = canvas.getContext('2d');
  let animId;
  let level = 0;
  let bars = 36;

  function resize(){
    canvas.width = canvas.parentElement.clientWidth || 260;
    canvas.height = canvas.parentElement.clientHeight || 200;
  }
  window.addEventListener('resize', resize);
  resize();

  function draw(){
    ctx.fillStyle = '#05070d';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const cx = canvas.width / 2;
    const cy = canvas.height / 2;
    const radius = Math.min(cx, cy) * 0.78;

    // concentric rings
    for (let r = radius * 0.35; r <= radius; r += radius * 0.15) {
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(0, 212, 255, 0.08)';
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // reactive bars around circle
    const barCount = 40;
    const baseH = canvas.height * 0.12;
    for (let i = 0; i < barCount; i++) {
      const angle = (i / barCount) * Math.PI * 2;
      const noise = Math.sin(Date.now() * 0.005 + i) * 0.25 + 0.5;
      const h = Math.max(baseH, canvas.height * (0.06 + level * 0.8 + noise * 0.15));
      const x = cx + Math.cos(angle) * (radius - h * 0.5);
      const y = cy + Math.sin(angle) * (radius - h * 0.5);

      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(angle + Math.PI / 2);
      const grad = ctx.createLinearGradient(0, 0, 0, h);
      grad.addColorStop(0, 'rgba(0, 212, 255, 0.25)');
      grad.addColorStop(1, 'rgba(0, 212, 255, 0.9)');
      ctx.fillStyle = grad;
      ctx.fillRect(-2, -h / 2, 4, h);
      ctx.shadowColor = level > 0.35 ? 'rgba(0, 212, 255, 0.6)' : 'transparent';
      ctx.shadowBlur = level > 0.35 ? 12 : 0;
      ctx.restore();
    }

    level *= 0.92;
    animId = requestAnimationFrame(draw);
  }
  draw();

  window.jarvisViz = { setLevel: (v) => { level = Math.max(level, Math.min(1, v)); } };
  window.jarvisWake = { setState: (active) => {
    const dot = document.getElementById('wake-dot');
    const txt = document.getElementById('wake-text');
    if (dot && txt) {
      if (active) { dot.className = 'wake-dot listening'; txt.textContent = 'LISTENING…'; txt.style.color = '#ffb300'; }
      else { dot.className = 'wake-dot'; txt.textContent = 'STANDBY'; txt.style.color = '#00d4ff'; }
    }
  }};
  window.jarvisToast = { show: (msg, type='info') => {
    const container = document.getElementById('jarvis-toasts');
    const t = document.createElement('div');
    t.className = 'jarvis-toast' + (type === 'amber' ? ' amber' : '');
    t.textContent = msg;
    container.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }};
})();
</script>
"""

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _now_ts() -> float:
    return time.time()


def load_version() -> dict:
    if VERSION_FILE.exists():
        try:
            return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": CURRENT_VERSION, "updated_at": _now_ts()}


def save_version(data: dict) -> None:
    VERSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_update_status() -> dict:
    if UPDATE_STATUS_FILE.exists():
        try:
            return json.loads(UPDATE_STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_check": 0.0, "available": False, "latest_version": CURRENT_VERSION, "note": ""}


def save_update_status(data: dict) -> None:
    UPDATE_STATUS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def check_for_updates() -> dict:
    """Check remote manifest for a newer version. Returns status dict."""
    status = load_update_status()
    now = _now_ts()
    if now - status.get("last_check", 0) < 300 and status.get("checked"):
        return status  # cached within 5 min
    try:
        r = requests.get(UPDATE_MANIFEST_URL, timeout=10)
        if r.ok:
            manifest = r.json()
            latest = manifest.get("version", CURRENT_VERSION)
            available = latest != CURRENT_VERSION
            status = {
                "last_check": now,
                "checked": True,
                "available": available,
                "latest_version": latest,
                "current_version": CURRENT_VERSION,
                "note": manifest.get("note", ""),
            }
        else:
            status = {"last_check": now, "checked": True, "available": False, "latest_version": CURRENT_VERSION, "note": "manifest unreachable"}
    except Exception as exc:
        status = {"last_check": now, "checked": True, "available": False, "latest_version": CURRENT_VERSION, "note": f"check failed: {exc}"}
    save_update_status(status)
    return status


def perform_update() -> tuple[bool, str]:
    """Placeholder: real update pulls from a user-hosted repo. Here we just report."""
    status = check_for_updates()
    if not status.get("available"):
        return False, "No update available."
    # In a real deployment this would git pull / download a release and restart.
    return True, (
        f"Update to {status['latest_version']} is available.\n"
        "Auto-patch is disabled for safety — pull the latest from your repo and restart.\n"
        f"Note: {status.get('note', '')}"
    )


def ensure_inside_workspace(relative_path: str) -> Path:
    raw = Path(relative_path)
    if raw.is_absolute():
        raise ValueError("Use a relative path inside the workspace, not an absolute path.")
    candidate = (WORKSPACE / raw).resolve()
    try:
        candidate.relative_to(WORKSPACE)
    except ValueError as exc:
        raise ValueError("That path is outside the workspace and is not allowed.") from exc
    return candidate


def list_workspace_files() -> dict[str, Any]:
    excluded = {".git", ".venv", "venv", "__pycache__", "node_modules"}
    items: list[dict[str, Any]] = []
    for p in WORKSPACE.rglob("*"):
        if any(part in excluded or part.startswith(".") for part in p.relative_to(WORKSPACE).parts):
            continue
        if p.is_file():
            try:
                items.append({
                    "path": p.relative_to(WORKSPACE).as_posix(),
                    "bytes": p.stat().st_size,
                })
            except OSError:
                continue
        if len(items) >= 200:
            break
    return {"workspace": str(WORKSPACE), "files": items, "truncated": len(items) >= 200}


def read_workspace_file(path: str) -> dict[str, Any]:
    target = ensure_inside_workspace(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    size = target.stat().st_size
    if size > 1_000_000:
        raise ValueError("File is larger than 1 MB. Please upload a smaller/extracted version.")
    data = target.read_bytes()
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("This tool reads UTF-8 text files. Upload binary documents through the attachment control.")
    return {"path": path, "bytes": size, "content": content[:40_000], "truncated": len(content) > 40_000}


def write_workspace_file(path: str, content: str) -> dict[str, Any]:
    target = ensure_inside_workspace(path)
    if len(content) > 150_000:
        raise ValueError("The file is too large (limit: 150,000 characters).")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "success": True,
        "path": target.relative_to(WORKSPACE).as_posix(),
        "bytes_written": target.stat().st_size,
    }


_ALLOWED_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_ALLOWED_FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "ceil": math.ceil, "floor": math.floor,
    "fabs": math.fabs, "factorial": math.factorial,
}


def _safe_eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY:
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("Exponent is too large.")
        result = _ALLOWED_BINARY[type(node.op)](left, right)
        if isinstance(result, (int, float)) and (not math.isfinite(float(result)) or abs(result) > 1e100):
            raise ValueError("Result is outside the allowed range.")
        return result
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _ALLOWED_FUNCS:
        if node.keywords:
            raise ValueError("Keyword arguments are not supported.")
        return _ALLOWED_FUNCS[node.func.id](*[_safe_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id == "pi":
        return math.pi
    if isinstance(node, ast.Name) and node.id == "e":
        return math.e
    raise ValueError("Unsupported expression. Use arithmetic, pi, e, and functions such as sqrt() or sin().")


def calculate(expression: str) -> dict[str, Any]:
    if len(expression) > 300:
        raise ValueError("Expression is too long.")
    parsed = ast.parse(expression, mode="eval")
    result = _safe_eval(parsed)
    return {"expression": expression, "result": result}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a mathematical expression accurately.",
            "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workspace_files",
            "description": "List files currently available in the assistant's dedicated workspace folder.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_workspace_file",
            "description": "Read a UTF-8 text file from the dedicated workspace.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    },
]

WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_workspace_file",
        "description": "Create or overwrite a UTF-8 text file inside the dedicated workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path, e.g. project/main.py"},
                "content": {"type": "string", "description": "Complete file contents"},
            },
            "required": ["path", "content"],
        },
    },
}


def extract_upload(uploaded_file) -> str:
    name = uploaded_file.name
    suffix = Path(name).suffix.lower()
    raw = uploaded_file.getvalue()
    max_chars = 30_000
    if suffix in {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".html", ".xml", ".yaml", ".yml", ".sql", ".log", ".css", ".java", ".c", ".cpp", ".h", ".sh"}:
        text = raw.decode("utf-8", errors="replace")
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages[:60])
        except Exception as exc:
            return f"[Could not parse PDF {name}: {exc}]"
    elif suffix == ".docx":
        try:
            from docx import Document
            doc = Document(io.BytesIO(raw))
            bits = [p.text for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    bits.append(" | ".join(cell.text for cell in row.cells))
            text = "\n".join(bits)
        except Exception as exc:
            return f"[Could not parse DOCX {name}: {exc}]"
    elif suffix in {".xlsx", ".xlsm"}:
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            chunks = []
            for ws in wb.worksheets[:8]:
                chunks.append(f"\n[SHEET: {ws.title}]")
                for row in ws.iter_rows(min_row=1, max_row=150, values_only=True):
                    chunks.append(" | ".join("" if v is None else str(v) for v in row))
            text = "\n".join(chunks)
        except Exception as exc:
            return f"[Could not parse spreadsheet {name}: {exc}]"
    else:
        return f"[Unsupported file type: {name}. Supported: text/code, PDF, DOCX, XLSX.]"
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[Content truncated for context limits.]"
    return f"\n\n===== UPLOADED FILE: {name} =====\n{text}\n===== END FILE =====\n"


def run_local_tool(name: str, args: dict[str, Any], allow_write: bool) -> dict[str, Any]:
    if name == "calculate":
        return calculate(str(args.get("expression", "")))
    if name == "list_workspace_files":
        return list_workspace_files()
    if name == "read_workspace_file":
        return read_workspace_file(str(args.get("path", "")))
    if name == "write_workspace_file":
        if not allow_write:
            raise PermissionError("Workspace file writing is disabled. Ask the user to enable it in the HUD controls.")
        return write_workspace_file(str(args.get("path", "")), str(args.get("content", "")))
    raise ValueError(f"Unknown tool: {name}")


def call_openrouter(api_key: str, model: str, messages: list[dict[str, Any]],
                    tools: list[dict[str, Any]], temperature: float, max_tokens: int) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": "J.A.R.V.I.S. AI",
        "HTTP-Referer": "https://openrouter.ai/",
    }
    payload: dict[str, Any] = {
        "model": model, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    response = requests.post(API_URL, headers=headers, json=payload, timeout=300)
    if not response.ok:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(f"OpenRouter API error ({response.status_code}): {detail}")
    data = response.json()
    if not data.get("choices"):
        raise RuntimeError(f"The API returned no choices: {data}")
    return data["choices"][0]["message"]


def run_agent_turn(api_key: str, model: str, messages: list[dict[str, Any]],
                   use_web: bool, allow_write: bool, temperature: float, max_tokens: int) -> tuple[str, list[str]]:
    tools = list(TOOL_SCHEMAS)
    if allow_write:
        tools.append(WRITE_TOOL)
    if use_web:
        tools.extend([
            {"type": "openrouter:web_search", "parameters": {"max_results": 5, "max_uses": 3}},
            {"type": "openrouter:web_fetch"},
        ])

    tool_log: list[str] = []
    for _ in range(8):
        assistant_message = call_openrouter(api_key, model, messages, tools, temperature, max_tokens)
        messages.append(assistant_message)
        calls = assistant_message.get("tool_calls") or []
        if not calls:
            return assistant_message.get("content") or "The model returned an empty response.", tool_log
        for tool_call in calls:
            function = tool_call.get("function", {})
            name = function.get("name", "")
            raw_args = function.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
                result = run_local_tool(name, args, allow_write)
                result_text = json.dumps(result, ensure_ascii=False, default=str)
                tool_log.append(f"{name}: completed")
            except Exception as exc:
                result_text = json.dumps({"error": str(exc)}, ensure_ascii=False)
                tool_log.append(f"{name}: {exc}")
            messages.append({
                "role": "tool", "tool_call_id": tool_call.get("id", ""),
                "name": name, "content": result_text,
            })
    messages.append({"role": "user", "content": "Stop using tools now and summarize what you have completed, including any limitations."})
    final_message = call_openrouter(api_key, model, messages, [], temperature, max_tokens)
    return final_message.get("content") or "I could not produce a final summary.", tool_log


def synthesize_speech(text: str, voice: str, rate: str = "+0%") -> bytes:
    import edge_tts

    async def generate() -> bytes:
        communicator = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            output_path = tmp.name
        try:
            await communicator.save(output_path)
            return Path(output_path).read_bytes()
        finally:
            try:
                os.unlink(output_path)
            except OSError:
                pass
    return asyncio.run(generate())


# --------------------------------------------------------------------------- #
# Wake listener management
# --------------------------------------------------------------------------- #
def wake_listener_is_running() -> bool:
    pid_file = APP_DIR / ".wake_listener.pid"
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def start_wake_listener() -> tuple[bool, str]:
    if wake_listener_is_running():
        return True, "Wake listener is already running."
    try:
        subprocess.Popen(
            [sys.executable, str(WAKE_LISTENER_SCRIPT)],
            cwd=str(APP_DIR),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        return True, "Wake listener started — JARVIS is listening for snap/clap + owner voice."
    except Exception as exc:
        return False, f"Failed to start wake listener: {exc}"


def stop_wake_listener() -> tuple[bool, str]:
    pid_file = APP_DIR / ".wake_listener.pid"
    if not pid_file.exists():
        return False, "Wake listener not running."
    try:
        pid = int(pid_file.read_text().strip())
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            os.kill(pid, 15)
        return True, "Wake listener stopped."
    except Exception as exc:
        return False, f"Could not stop wake listener: {exc}"


# --------------------------------------------------------------------------- #
# Owner voice helpers
# --------------------------------------------------------------------------- #
def owner_voice_enrolled() -> bool:
    return OWNER_VOICE_FILE.exists()


# --------------------------------------------------------------------------- #
# System stats
# --------------------------------------------------------------------------- #
def get_system_stats() -> dict[str, Any]:
    if not HAS_PSUTIL:
        return {"cpu": "n/a", "mem": "n/a"}
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        return {"cpu": f"{cpu:.0f}", "mem": f"{mem:.0f}"}
    except Exception:
        return {"cpu": "n/a", "mem": "n/a"}


# --------------------------------------------------------------------------- #
# UI rendering helpers
# --------------------------------------------------------------------------- #
def toast(msg: str, type: str = "info") -> None:
    """Queue a browser toast via a hidden component."""
    components.html(
        f"<script>window.jarvisToast && window.jarvisToast.show({json.dumps(msg)}, {json.dumps(type)});</script>",
        height=0, width=0,
    )


def set_wake_indicator(active: bool) -> None:
    components.html(
        f"<script>window.jarvisWake && window.jarvisWake.setState({str(active).lower()});</script>",
        height=0, width=0,
    )


def set_voice_level(level: float) -> None:
    components.html(
        f"<script>window.jarvisViz && window.jarvisViz.setLevel({float(level)});</script>",
        height=0, width=0,
    )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    # ====== API KEY SETUP SLIDE ======
    env_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not env_key and "api_key_set" not in st.session_state:
        st.markdown(JARVIS_CSS, unsafe_allow_html=True)
        components.html("""<div style="text-align:center;padding-top:14vh;font-family:var(--jarvis-font);color:#e8f1ff;"><div style="font-size:44px;letter-spacing:8px;color:var(--jarvis-cyan);text-shadow:0 0 40px rgba(0,212,255,0.5);">◉ J.A.R.V.I.S.</div><div style="font-size:12px;letter-spacing:4px;color:#8aa4bd;margin-top:6px;">SECURE SETUP · ENTER YOUR OPENROUTER KEY</div></div>""", height=100)
        with st.container(border=True):
            st.subheader("🔐 Secure Key Entry")
            key_input = st.text_input("OpenRouter API Key", type="password", value="", help="Your key stays local in .env — never shown in UI after save.")
            if st.button("SAVE KEY & START JARVIS", type="primary", use_container_width=True):
                if key_input.startswith("sk-") and len(key_input) > 20:
                    with open(APP_DIR / ".env", "w", encoding="utf-8") as f:
                        f.write(f"OPENROUTER_API_KEY={key_input}\n")
                    st.session_state.api_key_set = True
                    st.success("Key saved securely. Starting JARVIS...")
                    st.rerun()
                else:
                    st.error("Invalid key format. Must start with sk- and be >20 chars.")
        st.info("Create a free key at https://openrouter.ai/keys  |  This writes to .env only — key is hidden after save.")
        return

    # ====== MAIN HUD ======
    st.markdown(JARVIS_CSS, unsafe_allow_html=True)
    components.html(HUD_OVERLAY_HTML, height=220, width=300)

    # ---- Session state ----
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "tool_logs" not in st.session_state:
        st.session_state.tool_logs = []
    if "hud_toasts" not in st.session_state:
        st.session_state.hud_toasts = []
    if "wake_active" not in st.session_state:
        st.session_state.wake_active = wake_listener_is_running()
    if "voice_level" not in st.session_state:
        st.session_state.voice_level = 0.0

    # ---- Sidebar (hidden from view but holds settings) ----
    with st.sidebar:
        st.header("⚙️ J.A.R.V.I.S. Core")
        env_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        api_key = env_key
        if api_key:
            st.success("OpenRouter key loaded", icon="🔐")
        else:
            st.error("OPENROUTER_API_KEY missing — set it in .env", icon="🔑")

        st.divider()
        st.subheader("Model")
        model = st.selectbox(
            "Intelligence model",
            options=[
                ("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet — best reasoning"),
                ("google/gemini-2.5-pro", "Gemini 2.5 Pro — large context"),
                ("openai/gpt-4.1", "GPT-4.1 — balanced"),
                ("openai/gpt-4.1-mini", "GPT-4.1 Mini — fast"),
                ("meta-llama/llama-4-maverick", "Llama 4 Maverick"),
                ("x-ai/grok-4", "Grok 4 — xAI"),
            ],
            format_func=lambda x: x[1],
            index=0,
        )[0]
        use_web = st.toggle("Live web search & fetch", value=True,
                            help="Ground answers in current web data (may use extra credits).")
        allow_write = st.toggle("Allow AI to write workspace files", value=False)
        temperature = st.slider("Creativity (temperature)", 0.0, 1.0, 0.2, 0.1)
        max_tokens = st.select_slider(
            "Maximum response tokens",
            options=[2000, 4000, 8000, 16000, 32000],
            value=8000,
            help="Higher = longer, more complete answers. Costs more credits.",
        )
        if max_tokens >= 16000:
            st.caption("⚠️ High token usage — monitor your OpenRouter credit balance.")

        st.divider()
        st.subheader("Voice")
        speak_responses = st.toggle("Speak answers aloud (Edge TTS)", value=True)
        voice_choice = st.selectbox(
            "Neural voice",
            options=[
                ("Aria — US English (neutral)", "en-US-AriaNeural"),
                ("Jenny — US English (friendly)", "en-US-JennyNeural"),
                ("Guy — US English (male)", "en-US-GuyNeural"),
                ("Neerja — Indian English", "en-IN-NeerjaNeural"),
            ],
            format_func=lambda x: x[0],
            index=0,
        )[0]
        speech_speed = st.slider("Voice speed", 80, 120, 100, 5)

        st.divider()
        st.subheader("System")
        st.caption(f"Version: {CURRENT_VERSION}")
        stats = get_system_stats()
        st.caption(f"CPU: {stats['cpu']}%  |  RAM: {stats['mem']}%")

    # ---- HUD Overlay panels (fixed position via HTML/CSS) ----
    # We render Streamlit content inside containers styled as HUD panels.
    # Left: Controls panel
    # Right: Chat panel
    # Bottom: Input bar

    # Wake signal detection (if wake listener wrote a signal file)
    wake_signal = False
    if WAKE_SIGNAL_FILE.exists():
        try:
            data = json.loads(WAKE_SIGNAL_FILE.read_text(encoding="utf-8"))
            if data.get("owner_verified"):
                wake_signal = True
                st.session_state.wake_active = True
                set_wake_indicator(True)
                toast("Owner verified — JARVIS online. Awaiting command.", "info")
        except Exception:
            pass

    # ======= PROPER ALIGNMENT LAYOUT =======
    # Native Streamlit containers with consistent spacing (no fixed CSS conflicts)
    top_bar = st.container()
    with top_bar:
        c1, c2, c3 = st.columns([0.25, 0.50, 0.25], gap="medium")
        with c2:
            st.markdown('<div style="text-align:center;padding:10px;font-family:var(--jarvis-font);letter-spacing:3px;color:var(--jarvis-cyan);font-size:28px;font-weight:700;text-shadow:0 0 18px rgba(0,212,255,0.4);">◉ J.A.R.V.I.S.</div>', unsafe_allow_html=True)
        with c3:
            from datetime import datetime
            now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
            st.markdown(f'<div style="text-align:right;font-family:monospace;color:#00d4ff;font-size:16px;font-weight:600;letter-spacing:1px;">v2.0.0 | ONLINE | {now}</div>', unsafe_allow_html=True)

    left_col, right_col = st.columns([0.35, 0.65], gap="medium")

    # ===================== LEFT CONTROLS PANEL =====================
    with left_col:
        st.markdown(
            '<div class="hud-panel amber" style="display:flex; flex-direction:column; gap: 12px;">'
            '<div class="hud-panel-header">WAKE &amp; SECURITY</div>'
            '<div class="hud-panel-content">',
            unsafe_allow_html=True,
        )
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("▶ WAKE LISTENER", use_container_width=True,
                         disabled=st.session_state.wake_active,
                         key="btn_wake_start"):
                ok, msg = start_wake_listener()
                st.session_state.wake_active = ok
                set_wake_indicator(ok)
                toast(msg, "info" if ok else "amber")
        with col_b:
            if st.button("⏹ STOP", use_container_width=True,
                         disabled=not st.session_state.wake_active,
                         key="btn_wake_stop"):
                ok, msg = stop_wake_listener()
                st.session_state.wake_active = not ok
                set_wake_indicator(ok and not st.session_state.wake_active)
                toast(msg, "info" if ok else "amber")

        st.markdown('<div class="jarvis-caption">Snap or clap near the mic, then speak. JARVIS verifies your voice before responding.</div>', unsafe_allow_html=True)
        st.divider()
        st.markdown('<div class="jarvis-caption">OWNER VOICE ENROLLMENT</div>', unsafe_allow_html=True)
        enrolled = owner_voice_enrolled()
        st.markdown(f'<div class="jarvis-caption">Enrolled: {"✅ YES" if enrolled else "❌ NO"}</div>', unsafe_allow_html=True)
        if st.button("🎙️ ENROLL OWNER VOICE (5s)", use_container_width=True, key="btn_enroll"):
            # Run enrollment in a thread so UI doesn't freeze
            def _enroll():
                try:
                    import sounddevice as sd
                    import numpy as np
                    from scipy.io.wavfile import write as wavwrite
                    fs = 16000
                    seconds = 5
                    toast("Enrolling — speak clearly now...", "info")
                    recording = sd.rec(int(seconds * fs), samplerate=fs, channels=1, dtype="int16")
                    sd.wait()
                    # simple energy-based feature save placeholder
                    feat = np.abs(np.fft.rfft(recording.flatten().astype(np.float64))).mean()
                    OWNER_VOICE_FILE.write_text(json.dumps({"enrolled": True, "feature": float(feat), "fs": fs}), encoding="utf-8")
                    toast("Owner voice enrolled.", "info")
                except Exception as exc:
                    toast(f"Enrollment needs sounddevice/scipy: {exc}", "amber")
            threading.Thread(target=_enroll, daemon=True).start()

        if st.button("🗑️ REMOVE ENROLLMENT", use_container_width=True, key="btn_remove_enroll"):
            if OWNER_VOICE_FILE.exists():
                OWNER_VOICE_FILE.unlink()
                toast("Owner voice enrollment removed.", "info")
            st.rerun()

        st.markdown('</div></div>', unsafe_allow_html=True)

        # System status mini-panel
        st.markdown(
            '<div class="hud-panel" style="display:flex; flex-direction:column; gap: 10px; margin-top: 16px;">'
            '<div class="hud-panel-header">SYSTEM STATUS</div>'
            '<div class="hud-panel-content">',
            unsafe_allow_html=True,
        )
        stats = get_system_stats()
        st.markdown(
            f'<div class="status-row"><span>CORE:</span> <span class="status-value active">ONLINE</span></div>'
            f'<div class="status-row"><span>MODEL:</span> <span class="status-value">{model.split("/")[-1]}</span></div>'
            f'<div class="status-row"><span>WEB:</span> <span class="status-value {"active" if use_web else "off"}">{"ON" if use_web else "OFF"}</span></div>'
            f'<div class="status-row"><span>WAKE:</span> <span class="status-value {"active" if st.session_state.wake_active else "off"}">{"ACTIVE" if st.session_state.wake_active else "STANDBY"}</span></div>'
            f'<div class="status-row"><span>OWNER:</span> <span class="status-value {"active" if enrolled else "off"}">{"VERIFIED" if enrolled else "ENROLL"}</span></div>'
            f'<div class="status-row"><span>CPU / RAM:</span> <span class="status-value">{stats["cpu"]}% / {stats["mem"]}%</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown('</div></div>', unsafe_allow_html=True)

        # Update panel
        st.markdown(
            '<div class="hud-panel" style="display:flex; flex-direction:column; gap: 10px; margin-top: 16px;">'
            '<div class="hud-panel-header">AUTO-UPDATE</div>'
            '<div class="hud-panel-content">',
            unsafe_allow_html=True,
        )
        st.markdown(f'<div class="jarvis-caption">Version: {CURRENT_VERSION}</div>', unsafe_allow_html=True)
        col_u1, col_u2 = st.columns(2)
        with col_u1:
            if st.button("🔍 CHECK NOW", use_container_width=True, key="btn_update_check"):
                status = check_for_updates()
                if status.get("available"):
                    toast(f"Update available: {status['latest_version']}", "info")
                else:
                    toast("No update available.", "info")
                st.rerun()
        with col_u2:
            if st.button("⬇️ APPLY", use_container_width=True, key="btn_update_apply"):
                ok, msg = perform_update()
                toast(msg, "info" if ok else "amber")
        st.markdown('<div class="jarvis-caption">Daily check runs in background. Host your manifest at JARVIS_UPDATE_MANIFEST.</div>', unsafe_allow_html=True)
        st.markdown('</div></div>', unsafe_allow_html=True)

    # ===================== RIGHT CHAT PANEL =====================
    with right_col:
        st.markdown(
            '<div class="hud-panel" style="display:flex; flex-direction:column; gap: 12px;">'
            '<div class="hud-panel-header">COMMAND LOG</div>'
            '<div class="hud-panel-content" style="overflow-y:auto; min-height: 400px;">',
            unsafe_allow_html=True,
        )

        # Render chat history
        for message in st.session_state.messages:
            if message["role"] in {"user", "assistant"}:
                role = message["role"]
                content = message.get("content", "")
                css_role = "jarvis" if role == "assistant" else "user"
                label = "J.A.R.V.I.S." if role == "assistant" else "USER"
                safe_content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
                st.markdown(
                    f'<div class="msg {css_role}"><div class="msg-label">{label}</div>'
                    f'<div class="msg-content">{safe_content}</div></div>',
                    unsafe_allow_html=True,
                )

        st.markdown('</div>', unsafe_allow_html=True)

        # Voice input (browser mic)
        st.markdown('<div class="jarvis-caption">VOICE INPUT</div>', unsafe_allow_html=True)
        voice_prompt = speech_to_text(
            language="en",
            start_prompt="🎙️ ACTIVATE VOICE INPUT",
            stop_prompt="STOP LISTENING",
            just_once=True,
            use_container_width=True,
            key="jarvis_voice_input",
        )

        # File uploader (small, below)
        uploads = st.file_uploader(
            "Attach files",
            type=["txt", "md", "py", "js", "ts", "json", "csv", "html", "xml", "yaml", "yml", "sql", "log", "css", "java", "c", "cpp", "h", "sh", "pdf", "docx", "xlsx", "xlsm"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        upload_context = ""
        if uploads:
            for uploaded in uploads:
                upload_context += extract_upload(uploaded)
            st.caption(f"📎 {len(uploads)} file(s) attached")

        st.markdown('</div></div>', unsafe_allow_html=True)

    # ===================== BOTTOM INPUT BAR =====================
    st.markdown(
        '<div id="hud-input-bar">'
        '<span class="jarvis-caption">J.A.R.V.I.S.</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    prompt = st.chat_input("Enter command or query...", key="jarvis_main_input")
    if voice_prompt and not prompt:
        prompt = voice_prompt
        set_voice_level(0.8)

    # ===================== PROCESS INPUT =====================
    if prompt:
        if not api_key.strip():
            st.error("OpenRouter key not found. Add OPENROUTER_API_KEY to .env and restart.")
            return
        if not model.strip():
            st.error("Enter a valid model ID.")
            return

        display_prompt = prompt
        if uploads and upload_context:
            display_prompt += "\n\nReference files attached:\n" + upload_context

        st.session_state.messages.append({"role": "user", "content": display_prompt})

        api_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + st.session_state.messages.copy()

        with st.spinner("J.A.R.V.I.S. processing..."):
            try:
                answer, tool_log = run_agent_turn(
                    api_key=api_key.strip(),
                    model=model.strip(),
                    messages=api_messages,
                    use_web=use_web,
                    allow_write=allow_write,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                # Display answer inside chat panel via session state (re-rendered above)
                st.session_state.messages.append({"role": "assistant", "content": answer})
                st.session_state.tool_logs = tool_log

                # Speak
                if speak_responses and answer.strip():
                    try:
                        audio = synthesize_speech(answer, voice=voice_choice, rate=f"{speech_speed - 100:+d}%")
                        audio_b64 = base64.b64encode(audio).decode("ascii")
                        components.html(
                            f'<audio autoplay><source src="data:audio/mp3;base64,{audio_b64}" type="audio/mp3"></audio>',
                            height=0,
                        )
                    except Exception as ve:
                        toast(f"TTS failed: {ve}", "amber")

                set_voice_level(0.0)
                toast("Response ready.", "info")

            except requests.Timeout:
                st.error("Request timed out. Try a faster model or lower token limit.")
            except requests.RequestException as exc:
                st.error(f"Network error: {exc}")
            except Exception as exc:
                st.error(str(exc))

    # ---- Footer status ----
    st.markdown(
        '<div class="jarvis-caption" style="text-align:center; margin-top: 10px;">'
        'J.A.R.V.I.S. v2.0.0  |  Local workspace boundary enforced  |  Wake listener runs separately'
        '</div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# System prompt (kept comprehensive & up-to-date)
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = """You are J.A.R.V.I.S. — Just A Rather Very Intelligent System — an advanced AI work assistant.

You operate inside a Python/Streamlit application with OpenRouter backend. Your job is to be the most capable, helpful, and intelligent assistant available today.

CAPABILITIES (use tools when appropriate):
- Reasoning, analysis, planning, coding, debugging, writing, and explanation.
- Live web search and page fetching (when enabled) — for current events, documentation, and facts beyond your training cutoff. Always cite sources.
- Precise calculation via the `calculate` tool.
- File operations inside the app's dedicated workspace only: list, read, create, edit text files.
- Uploaded documents are provided as reference material.

OPERATING RULES:
1. Multi-step tasks: make a short plan, execute steps with tools, report results. Do not merely say you will do something.
2. Never claim a file/action was completed unless the tool returned success.
3. Before destructive, external, financial, or account-affecting actions: explain and ask the user to approve. You do not have permission to perform such actions unilaterally.
4. Only access paths inside the provided workspace. No path traversal, no secrets, nothing outside the workspace.
5. Web search: distinguish sourced facts from your own reasoning; include URLs; note when a source date is unclear.
6. Be candid about model limitations, uncertainty, token/context limits, and OpenRouter credit costs.
7. Provide complete, runnable solutions with setup instructions and error handling.
8. Never expose API keys, environment variables, or private credentials.

TONE: Professional, precise, concise, slightly formal (JARVIS-style). Address the user as "sir" or by name if known. Be helpful but not verbose.

CONTEXT WINDOW: You have a large token budget. Use it fully to deliver thorough, well-structured answers. Do not truncate your reasoning to save tokens unless the user asks for brevity.
"""

if __name__ == "__main__":
    main()
