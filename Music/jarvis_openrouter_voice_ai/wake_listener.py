"""
J.A.R.V.I.S. Wake Listener — Background Process
================================================
Continuously monitors the system microphone for:
  1. Snap / clap transient (short, high-frequency energy spike)
  2. Owner voice verification (speaker-enrolled feature match)

When both are confirmed, it writes a signal file and launches the
Streamlit JARVIS UI (or focuses it) so the owner can speak a command.

Run independently:
    python wake_listener.py

Configuration lives in wake_config.json (created on first run).
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pyaudio
import scipy.signal

APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "wake_config.json"
OWNER_VOICE_FILE = APP_DIR / "owner_voice.json"
SIGNAL_FILE = APP_DIR / "wake_triggered.txt"
PID_FILE = APP_DIR / ".wake_listener.pid"

# --------------------------------------------------------------------------- #
# Audio / detection constants
# --------------------------------------------------------------------------- #
SAMPLE_RATE = 16000          # Hz — matches WebRTC VAD requirements
FRAME_MS = 30                # VAD frame size (10/20/30 ms)
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)  # 480 samples @ 16k
CHANNELS = 1
FORMAT = pyaudio.paInt16

# Snap / clap detection
SNAP_ENERGY_MULTIPLIER = 4.0     # spike must be Nx the running baseline
SNAP_HIGH_FRACTION = 0.35        # fraction of energy above 2 kHz
SNAP_MAX_DURATION_MS = 250       # snap/clap must end within this window
BASELINE_WINDOW_FRAMES = 100     # ~3 seconds of history for baseline

# Owner voice verification
ENROLL_DURATION_SEC = 5          # seconds to record during enrollment
VERIFY_DURATION_SEC = 3          # seconds to listen when snap detected
VOICE_SIMILARITY_THRESHOLD = 0.78  # cosine similarity threshold (0..1)
MFCC_COEFFS = 13

# --------------------------------------------------------------------------- #
# Feature extraction (lightweight, no torch / librosa)
# --------------------------------------------------------------------------- #

def _frame_signal(samples: np.ndarray, frame_size: int, hop: int) -> np.ndarray:
    """Split mono signal into overlapping frames."""
    if len(samples) < frame_size:
        return samples.reshape(1, -1)
    n_frames = 1 + (len(samples) - frame_size) // hop
    idx = np.arange(frame_size)[None, :] + np.arange(n_frames)[:, None] * hop
    return samples[idx]


def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)) + 1e-9)


def _spectral_centroid(frame: np.ndarray, sr: int = SAMPLE_RATE) -> float:
    """Brightness of the frame — snaps/claps are bright (high centroid)."""
    spec = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
    freqs = np.fft.rfftfreq(len(frame), d=1.0 / sr)
    mag = spec + 1e-9
    return float(np.sum(freqs * mag) / np.sum(mag))


def _high_freq_energy_fraction(frame: np.ndarray, sr: int = SAMPLE_RATE,
                                cutoff: float = 2000.0) -> float:
    """Fraction of energy above `cutoff` Hz — high for snaps/claps."""
    spec = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
    freqs = np.fft.rfftfreq(len(frame), d=1.0 / sr)
    mag = spec ** 2
    total = np.sum(mag) + 1e-9
    high = np.sum(mag[freqs >= cutoff])
    return float(high / total)


def _mfcc_like(samples: np.ndarray, sr: int = SAMPLE_RATE,
               n_mfcc: int = MFCC_COEFFS) -> np.ndarray:
    """
    Lightweight cepstral feature vector (DCT of log Mel energies).
    Good enough for speaker-enrollment verification without heavy deps.
    """
    if len(samples) < FRAME_SIZE:
        samples = np.pad(samples, (0, FRAME_SIZE - len(samples)))
    frames = _frame_signal(samples, FRAME_SIZE, FRAME_SIZE // 2)
    # Mel filterbank (simple, 20 filters)
    n_filt = 20
    fft_len = FRAME_SIZE
    freqs = np.fft.rfftfreq(fft_len, d=1.0 / sr)
    mel_min = 0.0
    mel_max = 2595.0 * np.log10(1.0 + (sr / 2) / 700.0)
    mel_pts = np.linspace(mel_min, mel_max, n_filt + 2)
    hz_pts = 700.0 * (10.0 ** (mel_pts / 2595.0) - 1.0)
    bin_idx = np.floor((fft_len + 1) * hz_pts / sr).astype(int)

    filterbank = np.zeros((n_filt, len(freqs)))
    for m in range(1, n_filt + 1):
        left, center, right = bin_idx[m - 1], bin_idx[m], bin_idx[m + 1]
        for k in range(left, center):
            filterbank[m - 1, k] = (k - left) / (center - left)
        for k in range(center, right):
            filterbank[m - 1, k] = (right - k) / (right - center)

    spec = np.abs(np.fft.rfft(frames * np.hanning(fft_len), axis=1)) ** 2
    mel_energies = np.log10(np.maximum(spec @ filterbank.T, 1e-9))
    # DCT-II
    dct = np.zeros((n_mfcc, mel_energies.shape[1]))
    for k in range(n_mfcc):
        dct[k] = np.sum(mel_energies * np.cos(np.pi * k * (np.arange(mel_energies.shape[1]) + 0.5) / mel_energies.shape[1])[None, :], axis=1)
    return dct.mean(axis=1)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)


# --------------------------------------------------------------------------- #
# Config / enrollment persistence
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    default = {
        "sample_rate": SAMPLE_RATE,
        "snap_energy_multiplier": SNAP_ENERGY_MULTIPLIER,
        "snap_high_fraction": SNAP_HIGH_FRACTION,
        "snap_max_duration_ms": SNAP_MAX_DURATION_MS,
        "voice_similarity_threshold": VOICE_SIMILARITY_THRESHOLD,
        "auto_launch_streamlit": True,
        "streamlit_cmd": [sys.executable, "-m", "streamlit", "run", "app.py"],
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            default.update(user_cfg)
        except Exception:
            pass
    return default


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def save_owner_voice(features: np.ndarray) -> None:
    data = {"features": features.tolist(), "sample_rate": SAMPLE_RATE}
    with open(OWNER_VOICE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_owner_voice() -> Optional[np.ndarray]:
    if not OWNER_VOICE_FILE.exists():
        return None
    try:
        with open(OWNER_VOICE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return np.array(data["features"], dtype=np.float64)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Audio recording helpers
# --------------------------------------------------------------------------- #

def record_seconds(sec: float, stream: pyaudio.Stream) -> np.ndarray:
    """Record `sec` seconds from an open stream, return int16 numpy array."""
    n_frames = int(SAMPLE_RATE / FRAME_SIZE * sec)
    chunks = []
    for _ in range(n_frames):
        data = stream.read(FRAME_SIZE, exception_on_overflow=False)
        chunks.append(np.frombuffer(data, dtype=np.int16))
    return np.concatenate(chunks) if chunks else np.array([], dtype=np.int16)


def normalize_audio(samples: np.ndarray) -> np.ndarray:
    f = samples.astype(np.float64) / 32768.0
    peak = np.max(np.abs(f)) + 1e-9
    return f / peak


# --------------------------------------------------------------------------- #
# Detector
# --------------------------------------------------------------------------- #

class WakeDetector:
    def __init__(self, cfg: dict, on_verified_callback=None):
        self.cfg = cfg
        self.on_verified_callback = on_verified_callback
        self._noise_floor = 1e-6      # adaptive noise floor for energy VAD
        self._vad_alpha = 0.95        # smoothing for noise floor
        self.audio = pyaudio.PyAudio()
        self.stream: Optional[pyaudio.Stream] = None
        self.running = False
        self._baseline_rms = []          # rolling RMS history
        self._snap_active = False
        self._snap_start_time = 0.0
        self._voice_level = 0.0          # 0..1 for UI
        self._owner_verified = False

    # -- audio device --
    def _open_stream(self):
        self.stream = self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=FRAME_SIZE,
        )

    def _close_stream(self):
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    # -- pure-Python energy-based VAD --
    def _is_speech_energy(self, frame: np.ndarray) -> bool:
        rms = _rms(frame)
        # Adaptive noise floor: rises slowly, falls quickly on loud sounds
        if rms > self._noise_floor:
            self._noise_floor = self._vad_alpha * self._noise_floor + (1 - self._vad_alpha) * rms
        else:
            self._noise_floor = 0.999 * self._noise_floor + 0.001 * rms
        # Speech if energy is well above the noise floor
        return rms > max(self._noise_floor * 3.0, 0.02)

    # -- snap / clap detection --
    def _is_snap(self, frame: np.ndarray, now: float) -> bool:
        rms = _rms(frame)

        # Update baseline
        self._baseline_rms.append(rms)
        if len(self._baseline_rms) > BASELINE_WINDOW_FRAMES:
            self._baseline_rms.pop(0)
        baseline = float(np.mean(self._baseline_rms)) + 1e-9

        # Energy spike?
        energy_ok = rms > baseline * self.cfg["snap_energy_multiplier"]
        if not energy_ok:
            self._snap_active = False
            return False

        # High-frequency content?
        hf_frac = _high_freq_energy_fraction(frame)
        hf_ok = hf_frac > self.cfg["snap_high_fraction"]

        # Brightness (spectral centroid)
        centroid = _spectral_centroid(frame)
        bright_ok = centroid > 1500.0

        if hf_ok and bright_ok:
            if not self._snap_active:
                self._snap_active = True
                self._snap_start_time = now
                return False  # wait for confirmation on next frames
            # Confirm still within duration window
            elapsed_ms = (now - self._snap_start_time) * 1000
            if elapsed_ms < self.cfg["snap_max_duration_ms"]:
                self._snap_active = False
                return True
        else:
            self._snap_active = False
        return False

    # -- owner voice verification --
    def _verify_owner(self) -> bool:
        """Record a short window and compare against enrolled voice."""
        ref = load_owner_voice()
        if ref is None:
            return False
        print("[Wake] Snap detected — verifying owner voice...")
        samples = record_seconds(VERIFY_DURATION_SEC, self.stream)
        norm = normalize_audio(samples)
        feat = _mfcc_like(norm)
        sim = _cosine_similarity(feat, ref)
        print(f"[Wake] Voice similarity: {sim:.3f} (threshold {self.cfg['voice_similarity_threshold']})")
        return sim >= self.cfg["voice_similarity_threshold"]

    # -- trigger --
    def _trigger(self):
        print("[Wake] Owner verified — triggering JARVIS.")
        self._owner_verified = True
        try:
            SIGNAL_FILE.write_text(
                json.dumps({"triggered_at": time.time(), "owner_verified": True}),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[Wake] Could not write signal file: {exc}")

        if self.cfg.get("auto_launch_streamlit", True):
            cmd = self.cfg.get("streamlit_cmd")
            if cmd:
                try:
                    subprocess.Popen(cmd, cwd=str(APP_DIR),
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                    print("[Wake] Launched Streamlit JARVIS UI.")
                except Exception as exc:
                    print(f"[Wake] Failed to launch Streamlit: {exc}")

        if self.on_verified_callback:
            try:
                self.on_verified_callback()
            except Exception:
                pass

    # -- main loop --
    def run(self):
        self.running = True
        self._open_stream()
        print(f"[Wake] Listening on device index=default (rate={SAMPLE_RATE}Hz)...")
        print("[Wake] Snap/clap + owner voice required to wake JARVIS.")
        try:
            while self.running:
                try:
                    raw = self.stream.read(FRAME_SIZE, exception_on_overflow=False)
                except Exception:
                    time.sleep(0.01)
                    continue

                frame = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
                norm_frame = normalize_audio(frame)
                now = time.time()

                # Voice level for UI
                self._voice_level = min(1.0, _rms(frame) * 3.0)

                # Energy VAD: skip silence
                if not self._is_speech_energy(norm_frame):
                    # Still track baseline during silence
                    self._baseline_rms.append(_rms(frame))
                    if len(self._baseline_rms) > BASELINE_WINDOW_FRAMES:
                        self._baseline_rms.pop(0)
                    continue

                if self._is_snap(frame, now):
                    if self._verify_owner():
                        self._trigger()
                        # Cooldown after trigger
                        time.sleep(3.0)
                    else:
                        print("[Wake] Snap detected but voice not verified — ignoring.")
                        self._snap_active = False
                        time.sleep(1.0)

        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            self._close_stream()
            self.audio.terminate()
            print("[Wake] Stopped.")

    def stop(self):
        self.running = False


# --------------------------------------------------------------------------- #
# Enrollment (standalone)
# --------------------------------------------------------------------------- #

def enroll_owner_voice(sec: float = ENROLL_DURATION_SEC):
    """Record enrollment sample and save owner voice features."""
    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=FORMAT, channels=CHANNELS, rate=SAMPLE_RATE,
        input=True, frames_per_buffer=FRAME_SIZE,
    )
    print(f"[Enroll] Recording {sec}s — speak clearly now...")
    samples = record_seconds(sec, stream)
    stream.stop_stream()
    stream.close()
    audio.terminate()

    norm = normalize_audio(samples)
    feat = _mfcc_like(norm)
    save_owner_voice(feat)
    print(f"[Enroll] Owner voice saved to {OWNER_VOICE_FILE}")
    return feat


# --------------------------------------------------------------------------- #
# Single-instance guard
# --------------------------------------------------------------------------- #

def is_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # raises if not alive
        return True
    except Exception:
        return False


def write_pid():
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def remove_pid():
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #

def main():
    cfg = load_config()
    save_config(cfg)  # ensure config file exists

    if is_running():
        print("[Wake] A wake listener instance is already running.")
        return

    write_pid()

    def _handle_signal(signum, frame):
        detector.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    detector = WakeDetector(cfg)
    try:
        detector.run()
    finally:
        remove_pid()


if __name__ == "__main__":
    main()
