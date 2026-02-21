#!/usr/bin/env python3
"""
PawiScribe v3.0.0 - Local Meeting Notetaker - Apple Style UI
Records audio (microphone + system audio), transcribes with Whisper.
Differentiates speakers using mic vs system audio energy.
100% offline - no API calls required

Author: PawiBot Team
License: MIT
"""

__version__ = "3.0.0"

import sys
import os
import io
import json
import wave
import threading
import datetime
import tempfile
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict

# Fix torch DLL loading on Windows (required for venvs / MS Store Python)
if sys.platform == "win32":
    _torch_lib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "Lib", "site-packages", "torch", "lib")
    if not os.path.isdir(_torch_lib):
        # Fallback: find torch in the current Python's site-packages
        try:
            import importlib.util
            _spec = importlib.util.find_spec("torch")
            if _spec and _spec.origin:
                _torch_lib = os.path.join(os.path.dirname(os.path.dirname(_spec.origin)), "torch", "lib")
        except Exception:
            _torch_lib = ""
    if os.path.isdir(_torch_lib):
        os.add_dll_directory(_torch_lib)

    # Ensure ffmpeg is on PATH (winget installs may not be in inherited PATH)
    _ffmpeg_winget = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Microsoft", "WinGet", "Packages"
    )
    if os.path.isdir(_ffmpeg_winget):
        for _root, _dirs, _files in os.walk(_ffmpeg_winget):
            if "ffmpeg.exe" in _files:
                if _root not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = _root + ";" + os.environ.get("PATH", "")
                break

try:
    import sounddevice as sd
    import numpy as np
    import scipy.io.wavfile as wavfile
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    RESEMBLYZER_AVAILABLE = True
except ImportError:
    RESEMBLYZER_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QTextEdit, QLabel, QProgressBar, QFileDialog,
        QMessageBox, QComboBox, QGroupBox, QCheckBox, QSpinBox,
        QDialog, QListWidget, QListWidgetItem, QFrame, QGraphicsDropShadowEffect,
        QSizePolicy, QScrollArea, QSpacerItem, QSplitter
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
    from PyQt6.QtGui import QFont, QClipboard, QColor
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    print("PyQt6 not available. Please install: pip install PyQt6")
    sys.exit(1)


# Apple Design System Colors
APPLE_BLUE = "#007AFF"
APPLE_GREEN = "#34C759"
APPLE_RED = "#FF3B30"
APPLE_ORANGE = "#FF9500"
APPLE_YELLOW = "#FFCC00"
APPLE_PURPLE = "#AF52DE"
APPLE_PINK = "#FF2D55"
APPLE_TEAL = "#5AC8FA"
APPLE_INDIGO = "#5856D6"

# Apple Grays
APPLE_GRAY_6 = "#F5F5F7"
APPLE_GRAY_5 = "#E5E5EA"
APPLE_GRAY_4 = "#D1D1D6"
APPLE_GRAY_3 = "#C7C7CC"
APPLE_GRAY_2 = "#AEAEB2"
APPLE_GRAY = "#8E8E93"
APPLE_LABEL = "#1D1D1F"
APPLE_SECONDARY_LABEL = "#6C6C70"
APPLE_TERTIARY_LABEL = "#AEAEB2"

# Card styling
CARD_BG = "#FFFFFF"
CARD_BORDER = "#E5E5EA"


@dataclass
class AudioDevice:
    """Represents an audio device"""
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int
    is_loopback: bool = False
    default_samplerate: float = 48000.0
    native_channels: int = 2
    
    def __str__(self):
        loopback_tag = " [LOOPBACK]" if self.is_loopback else ""
        return f"{self.name} ({self.hostapi}){loopback_tag}"


class AudioDeviceManager:
    """Manages audio device detection and selection"""
    
    def __init__(self):
        self.devices: List[AudioDevice] = []
        self.input_devices: List[AudioDevice] = []
        self.output_devices: List[AudioDevice] = []
        self.loopback_devices: List[AudioDevice] = []
        
    def scan_devices(self) -> Dict[str, List[AudioDevice]]:
        """Scan all audio devices and categorize them"""
        self.devices = []
        self.input_devices = []
        self.output_devices = []
        self.loopback_devices = []
        
        if not SOUNDDEVICE_AVAILABLE:
            return {'all': [], 'inputs': [], 'outputs': [], 'loopbacks': []}
        
        try:
            device_list = sd.query_devices()
            hostapis = sd.query_hostapis()
            
            for i, dev in enumerate(device_list):
                hostapi_name = hostapis[dev['hostapi']]['name'] if dev['hostapi'] < len(hostapis) else 'Unknown'
                
                device = AudioDevice(
                    index=i,
                    name=dev['name'],
                    hostapi=hostapi_name,
                    max_input_channels=dev['max_input_channels'],
                    max_output_channels=dev['max_output_channels']
                )
                
                # Detect loopback-capable input devices across all host APIs
                if dev['max_input_channels'] > 0:
                    name_lower = dev['name'].lower()
                    if any(keyword in name_lower for keyword in ['loopback', 'stereo mix', 'what u hear', 'what you hear']):
                        device.is_loopback = True
                        device.default_samplerate = dev.get('default_samplerate', 48000.0)
                        device.native_channels = dev['max_input_channels']
                        self.loopback_devices.append(device)
                
                self.devices.append(device)
                
                if dev['max_input_channels'] > 0 and not device.is_loopback:
                    self.input_devices.append(device)
                if dev['max_output_channels'] > 0:
                    self.output_devices.append(device)
                    
        except Exception as e:
            print(f"Error scanning devices: {e}")
        
        return {
            'all': self.devices,
            'inputs': self.input_devices,
            'outputs': self.output_devices,
            'loopbacks': self.loopback_devices
        }
    
    def get_default_input_device(self) -> Optional[AudioDevice]:
        """Get the default input device"""
        try:
            default = sd.query_devices(kind='input')
            for dev in self.input_devices:
                if dev.name == default['name']:
                    return dev
        except:
            pass
        return self.input_devices[0] if self.input_devices else None
    
    def get_default_loopback_device(self) -> Optional[AudioDevice]:
        """Get the first available loopback device"""
        if self.loopback_devices:
            return self.loopback_devices[0]
        return None
    
    def has_loopback_support(self) -> bool:
        """Check if loopback recording is available"""
        return len(self.loopback_devices) > 0


class DualAudioRecorder:
    """Records audio from microphone and/or system audio simultaneously"""
    
    def __init__(self):
        self.recording = False
        self.microphone_frames = []
        self.system_audio_frames = []
        self.sample_rate = 16000
        self.channels = 1
        self.dtype = np.float32
        
        self.device_manager = AudioDeviceManager()
        self.microphone_device: Optional[AudioDevice] = None
        self.loopback_device: Optional[AudioDevice] = None
        self.capture_microphone = True
        self.capture_system_audio = False
        self.mic_stream = None
        self.loopback_stream = None
        
    def scan_devices(self) -> Dict[str, List[AudioDevice]]:
        """Scan and return available devices"""
        return self.device_manager.scan_devices()
    
    def set_devices(self, microphone: Optional[AudioDevice] = None, 
                    loopback: Optional[AudioDevice] = None):
        """Set the devices to use for recording"""
        self.microphone_device = microphone
        self.loopback_device = loopback
    
    def set_capture_options(self, microphone: bool = True, system_audio: bool = False):
        """Configure what to capture"""
        self.capture_microphone = microphone
        self.capture_system_audio = system_audio
        
    def start_recording(self, duration_seconds=None):
        """Start recording audio from selected sources"""
        if not SOUNDDEVICE_AVAILABLE:
            raise RuntimeError("sounddevice not available")
        
        self.recording = True
        self.microphone_frames = []
        self.system_audio_frames = []
        
        if self.capture_microphone and self.microphone_device:
            self._start_microphone_stream()
        
        if self.capture_system_audio and self.loopback_device:
            self._start_loopback_stream()
        
        if not self.mic_stream and not self.loopback_stream:
            self.recording = False
            raise RuntimeError("No audio sources configured for recording")
    
    def _start_microphone_stream(self):
        """Start the microphone input stream"""
        def mic_callback(indata, frames_count, time_info, status):
            if self.recording:
                self.microphone_frames.append(indata.copy())
        
        try:
            print(f"Using microphone device: {self.microphone_device.name}")
            self.mic_stream = sd.InputStream(
                device=self.microphone_device.index,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                callback=mic_callback
            )
            self.mic_stream.start()
        except Exception as e:
            print(f"Error starting microphone stream: {e}")
            self.mic_stream = None
    
    def _start_loopback_stream(self):
        """Start the loopback stream for system audio capture.
        
        Records at the device's native sample rate and resamples to
        self.sample_rate in the callback so Whisper gets 16 kHz audio.
        """
        native_sr = self.loopback_device.default_samplerate
        native_ch = min(self.loopback_device.native_channels, 2)  # cap at stereo
        resample_ratio = native_sr / self.sample_rate  # e.g. 48000/16000 = 3

        def loopback_callback(indata, frames_count, time_info, status):
            if not self.recording:
                return
            audio = indata.copy()
            # Convert stereo to mono if needed
            if native_ch > 1:
                audio = audio.mean(axis=1, keepdims=True)
            # Resample to target rate (simple decimation for integer ratios)
            if resample_ratio > 1:
                step = int(resample_ratio)
                if abs(resample_ratio - step) < 0.01:  # clean integer ratio
                    audio = audio[::step]
                else:
                    # Non-integer ratio — use linear interpolation
                    n_out = int(len(audio) / resample_ratio)
                    indices = np.linspace(0, len(audio) - 1, n_out).astype(int)
                    audio = audio[indices]
            self.system_audio_frames.append(audio)
        
        try:
            print(f"Using loopback device: {self.loopback_device.name} "
                  f"(native {int(native_sr)}Hz/{native_ch}ch, resampling to {self.sample_rate}Hz)")
            self.loopback_stream = sd.InputStream(
                device=self.loopback_device.index,
                samplerate=native_sr,
                channels=native_ch,
                dtype=self.dtype,
                callback=loopback_callback
            )
            self.loopback_stream.start()
        except Exception as e:
            print(f"Error starting loopback stream: {e}")
            self.loopback_stream = None
    
    def stop_recording(self):
        """Stop recording and return the mixed audio data"""
        self.recording = False
        
        if self.mic_stream:
            self.mic_stream.stop()
            self.mic_stream.close()
            self.mic_stream = None
        
        if self.loopback_stream:
            self.loopback_stream.stop()
            self.loopback_stream.close()
            self.loopback_stream = None
        
        return self._mix_audio()
    
    def get_recent_audio(self, last_n_frames: int = 0) -> Optional[np.ndarray]:
        """Get audio collected so far without stopping recording.
        If last_n_frames > 0, only return the most recent N frames."""
        mic_data = None
        loopback_data = None

        mic_frames = list(self.microphone_frames)
        sys_frames = list(self.system_audio_frames)

        if last_n_frames > 0:
            mic_frames = mic_frames[-last_n_frames:] if mic_frames else []
            sys_frames = sys_frames[-last_n_frames:] if sys_frames else []

        if mic_frames:
            mic_data = np.concatenate(mic_frames, axis=0)
        if sys_frames:
            loopback_data = np.concatenate(sys_frames, axis=0)

        return self._mix(mic_data, loopback_data)

    def get_recent_audio_separate(self, last_n_frames: int = 0):
        """Get mic and system audio separately for speaker detection.
        Returns (mixed_audio, mic_energy, sys_energy)."""
        mic_data = None
        loopback_data = None

        mic_frames = list(self.microphone_frames)
        sys_frames = list(self.system_audio_frames)

        if last_n_frames > 0:
            mic_frames = mic_frames[-last_n_frames:] if mic_frames else []
            sys_frames = sys_frames[-last_n_frames:] if sys_frames else []

        if mic_frames:
            mic_data = np.concatenate(mic_frames, axis=0)
        if sys_frames:
            loopback_data = np.concatenate(sys_frames, axis=0)

        mic_energy = float(np.sqrt(np.mean(mic_data ** 2))) if mic_data is not None else 0.0
        sys_energy = float(np.sqrt(np.mean(loopback_data ** 2))) if loopback_data is not None else 0.0

        mixed = self._mix(mic_data, loopback_data)
        return mixed, mic_energy, sys_energy

    def _mix(self, mic_data, loopback_data) -> Optional[np.ndarray]:
        """Mix two audio arrays"""
        if mic_data is not None and loopback_data is not None:
            min_len = min(len(mic_data), len(loopback_data))
            mic_data = mic_data[:min_len]
            loopback_data = loopback_data[:min_len]
            mixed = mic_data * 0.6 + loopback_data * 0.6
            max_val = np.max(np.abs(mixed))
            if max_val > 1.0:
                mixed = mixed / max_val * 0.95
            return mixed
        elif mic_data is not None:
            return mic_data
        elif loopback_data is not None:
            return loopback_data
        return None

    def _mix_audio(self) -> Optional[np.ndarray]:
        """Mix microphone and system audio into a single track"""
        mic_data = None
        loopback_data = None
        
        if self.microphone_frames:
            mic_data = np.concatenate(self.microphone_frames, axis=0)
        
        if self.system_audio_frames:
            loopback_data = np.concatenate(self.system_audio_frames, axis=0)
        
        return self._mix(mic_data, loopback_data)
    
    def save_to_wav(self, audio_data: np.ndarray, filepath: str) -> str:
        """Save audio data to WAV file"""
        if audio_data.dtype == np.float32 or audio_data.dtype == np.float64:
            audio_data = (audio_data * 32767).astype(np.int16)
        wavfile.write(filepath, self.sample_rate, audio_data)
        return filepath


class TranscriptionWorker(QThread):
    """Worker thread for transcription to keep UI responsive"""
    
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, audio_path, model_size="base"):
        super().__init__()
        self.audio_path = audio_path
        self.model_size = model_size
        
    def run(self):
        try:
            self.progress.emit("Loading Whisper model...")
            
            if not WHISPER_AVAILABLE:
                self.error.emit("Whisper not installed. Run: pip install openai-whisper")
                return
            
            model = whisper.load_model(self.model_size)
            
            self.progress.emit("Transcribing audio... (this may take a while)")
            
            result = model.transcribe(
                self.audio_path,
                verbose=False,
                language="en"
            )
            
            transcript = result["text"].strip()
            
            if not transcript:
                self.error.emit("No speech detected in the recording.")
                return
            
            formatted_transcript = self.format_transcript(result)
            
            output = self.create_markdown_output(formatted_transcript)
            
            self.finished.emit(output)
            
        except Exception as e:
            self.error.emit(f"Transcription error: {str(e)}")
    
    def format_transcript(self, result):
        """Format transcript with segments"""
        segments = result.get("segments", [])
        if not segments:
            return result["text"]
        
        lines = []
        for seg in segments:
            start = seg.get("start", 0)
            text = seg.get("text", "").strip()
            if text:
                timestamp = f"[{self.format_time(start)}]"
                lines.append(f"{timestamp} {text}")
        
        return "\n".join(lines) if lines else result["text"]
    
    def format_time(self, seconds):
        """Format seconds as MM:SS"""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"
    
    def create_markdown_output(self, transcript):
        """Create formatted markdown output"""
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")
        
        output = f"""# Meeting Notes - {date_str}

**Date:** {date_str}  
**Time:** {time_str}  
**Duration:** (recorded via PawiScribe)

---

## Transcript

{transcript}

---

*Generated by PawiScribe - Local Meeting Notetaker*
"""
        return output


class SpeakerTracker:
    """Tracks and distinguishes speakers using neural voice embeddings (d-vectors).

    Uses the resemblyzer VoiceEncoder to compute speaker embeddings from audio.
    Compares embeddings via cosine similarity — far more accurate than spectral
    features for distinguishing different voices (male vs female, etc.).

    Key design choices:
    - Stores ALL embeddings per speaker (no running-average drift)
    - Compares against the centroid of stored embeddings
    - Keeps a capped history (max 20 embeddings per speaker) for efficiency
    - Falls back to single-speaker mode if resemblyzer is not installed.
    """

    SIMILARITY_THRESHOLD = 0.69  # cosine similarity: same person ~0.75-0.95, diff male voices ~0.55-0.70
    MAX_EMBEDDINGS = 20          # max stored embeddings per speaker
    MIN_AUDIO_SECONDS = 0.8      # minimum audio duration for reliable embedding
    MIN_NEW_SPEAKER_SECONDS = 1.5  # need at least this much audio to create a new speaker
    CONSECUTIVE_MISSES_NEEDED = 2  # need N consecutive mismatches before creating a new speaker

    def __init__(self, sample_rate: int = 16000, device: str = None):
        self.sample_rate = sample_rate
        self.profiles: list = []   # [{"label": str, "embeddings": [np.ndarray], "centroid": np.ndarray}]
        self._next_id = 1
        self._encoder = None
        self._encoder_device = device  # "cpu" or "cuda"
        self._encoder_loaded = False
        self._miss_streak = 0         # consecutive chunks that didn't match any existing speaker
        self._pending_embeddings = [] # embeddings collected during miss streak

    def _get_encoder(self):
        """Lazy-load the VoiceEncoder (downloads model on first use)."""
        if self._encoder is None and RESEMBLYZER_AVAILABLE:
            device = self._encoder_device
            if device is None:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            self._encoder = VoiceEncoder(device)
            self._encoder_loaded = True
        return self._encoder

    def _embed(self, audio: np.ndarray):
        """Compute a speaker embedding from an audio array. Returns None on failure."""
        audio = audio.flatten().astype(np.float32)

        # Skip near-silent audio
        if np.sqrt(np.mean(audio ** 2)) < 1e-5:
            return None

        encoder = self._get_encoder()
        if encoder is None:
            return None

        try:
            processed = preprocess_wav(audio, source_sr=self.sample_rate)
            min_samples = int(self.MIN_AUDIO_SECONDS * 16000)  # resemblyzer always uses 16 kHz
            if len(processed) < min_samples:
                return None
            return encoder.embed_utterance(processed)
        except Exception:
            return None

    def _cosine_sim(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))

    def _update_centroid(self, profile: dict):
        """Recompute the centroid from stored embeddings."""
        embs = np.stack(profile["embeddings"])
        centroid = np.mean(embs, axis=0)
        centroid /= np.linalg.norm(centroid) + 1e-8
        profile["centroid"] = centroid

    def identify(self, audio: np.ndarray, audio_duration: float = 0.0) -> str:
        """Return a speaker label for the given audio chunk.
        
        Args:
            audio: audio samples
            audio_duration: duration in seconds (used to decide if enough for new speaker)
        """
        embedding = self._embed(audio)
        if embedding is None:
            return self.profiles[0]["label"] if self.profiles else "Speaker 1"

        # Compare against centroids of all known speakers
        best_match = None
        best_sim = -1.0
        for p in self.profiles:
            sim = self._cosine_sim(embedding, p["centroid"])
            if sim > best_sim:
                best_sim = sim
                best_match = p

        if best_match is not None and best_sim >= self.SIMILARITY_THRESHOLD:
            # Match — store embedding (capped) and recompute centroid
            best_match["embeddings"].append(embedding)
            if len(best_match["embeddings"]) > self.MAX_EMBEDDINGS:
                best_match["embeddings"].pop(0)  # drop oldest
            self._update_centroid(best_match)
            self._miss_streak = 0
            self._pending_embeddings = []
            return best_match["label"]
        else:
            # No match — but don't create a new speaker immediately
            self._miss_streak += 1
            self._pending_embeddings.append(embedding)

            # Only create a new speaker if:
            # 1. There are no profiles yet (first speaker), OR
            # 2. We have enough consecutive misses AND enough audio duration
            should_create = (
                not self.profiles or
                (
                    self._miss_streak >= self.CONSECUTIVE_MISSES_NEEDED and
                    audio_duration >= self.MIN_NEW_SPEAKER_SECONDS
                )
            )

            if should_create:
                # Average all pending embeddings for a more stable initial profile
                avg_emb = np.mean(np.stack(self._pending_embeddings), axis=0)
                avg_emb /= np.linalg.norm(avg_emb) + 1e-8
                label = f"Speaker {self._next_id}"
                self._next_id += 1
                self.profiles.append({
                    "label": label,
                    "embeddings": [avg_emb],
                    "centroid": avg_emb.copy(),
                })
                self._miss_streak = 0
                self._pending_embeddings = []
                return label
            else:
                # Not enough evidence for new speaker — assign to best existing match
                if best_match is not None:
                    return best_match["label"]
                return "Speaker 1"


class RealtimeTranscriptionWorker(QThread):
    """Worker that transcribes audio chunks in real-time while recording."""

    new_text = pyqtSignal(str)       # emits each newly transcribed chunk
    full_text_update = pyqtSignal(str)  # emits full cleaned transcript (replaces display)
    model_ready = pyqtSignal()       # emits once the model is loaded
    error = pyqtSignal(str)

    CHUNK_SECONDS = 5                # transcribe every N seconds of new audio
    OVERLAP_SECONDS = 1              # overlap with previous chunk for continuity
    GEMINI_MODEL = "gemini-flash-lite-latest"
    GEMINI_CLEANUP_EVERY = 120       # run Gemini cleanup every N chunks (~10 min at 5s/chunk)

    def __init__(self, recorder: DualAudioRecorder, model_size: str = "base",
                 ai_cleanup: bool = False, gemini_api_key: str = ""):
        super().__init__()
        self.recorder = recorder
        self.model_size = model_size
        self.ai_cleanup = ai_cleanup
        self.gemini_api_key = gemini_api_key
        self._stop_flag = False
        self._model = None
        self._gemini_model = None
        self._gemini_thread = None     # background thread for async API calls
        self._speaker_tracker = SpeakerTracker(sample_rate=recorder.sample_rate)
        self._last_speaker = None
        self._prev_tail = ""          # last few words of previous chunk for de-duplication
        self._raw_chunks = []         # accumulated raw transcript chunks
        self._chunk_count = 0         # counter for Gemini cleanup interval

    def stop(self):
        self._stop_flag = True

    def _interruptible_sleep(self, seconds: float) -> bool:
        """Sleep in small intervals so the thread can respond to stop quickly.
        Returns True if interrupted (stop requested)."""
        intervals = int(seconds * 4)  # 250ms intervals
        for _ in range(intervals):
            if self._stop_flag:
                return True
            self.msleep(250)
        return self._stop_flag

    def run(self):
        try:
            if not WHISPER_AVAILABLE:
                self.error.emit("Whisper not installed.")
                return

            self._model = whisper.load_model(self.model_size)

            # Pre-load the speaker encoder so first chunk isn't slow
            self._speaker_tracker._get_encoder()

            # Qwen loads lazily on first cleanup pass (see _ensure_qwen_loaded)

            self.model_ready.emit()

            overlap_frames = int(self.OVERLAP_SECONDS * self.recorder.sample_rate / 1024)
            last_frame_count = 0

            while not self._stop_flag:
                if self._interruptible_sleep(self.CHUNK_SECONDS):
                    break

                current_mic = len(self.recorder.microphone_frames)
                current_sys = len(self.recorder.system_audio_frames)
                current_count = max(current_mic, current_sys)

                if current_count <= last_frame_count:
                    continue

                # Grab frames with overlap from previous chunk for smoother joins
                grab_from = max(0, last_frame_count - overlap_frames)
                new_frames = current_count - grab_from
                audio = self.recorder.get_recent_audio(last_n_frames=new_frames)
                last_frame_count = current_count

                if audio is None or len(audio) < self.recorder.sample_rate:
                    continue

                audio_np = audio.flatten().astype(np.float32)
                if self._stop_flag:
                    break
                self._transcribe_and_emit(audio_np)

            # Final pass: transcribe any remaining audio
            if not self._stop_flag or True:  # always do final pass
                remaining_mic = len(self.recorder.microphone_frames)
                remaining_sys = len(self.recorder.system_audio_frames)
                remaining_count = max(remaining_mic, remaining_sys)
                if remaining_count > last_frame_count:
                    new_frames = remaining_count - last_frame_count
                    audio = self.recorder.get_recent_audio(last_n_frames=new_frames)
                    if audio is not None and len(audio) >= self.recorder.sample_rate // 2:
                        audio_np = audio.flatten().astype(np.float32)
                        self._transcribe_and_emit(audio_np)

        except Exception as e:
            self.error.emit(f"Realtime transcription error: {str(e)}")

    def _transcribe_and_emit(self, audio_np: np.ndarray):
        """Transcribe an audio chunk, detect speaker per segment, and emit text."""
        try:
            use_fp16 = next(self._model.parameters()).is_cuda
            result = self._model.transcribe(
                audio_np,
                verbose=False,
                language="en",
                fp16=use_fp16,
            )

            segments = result.get("segments", [])
            if not segments:
                return

            sr = self.recorder.sample_rate
            output_parts = []

            for seg in segments:
                seg_text = seg["text"].strip()
                if not seg_text:
                    continue

                # Extract the audio slice for this segment using timestamps
                start_sample = int(seg["start"] * sr)
                end_sample = int(seg["end"] * sr)
                seg_audio = audio_np[start_sample:end_sample]

                seg_duration = seg["end"] - seg["start"]

                # Need enough audio for a reliable embedding
                if seg_duration < self._speaker_tracker.MIN_AUDIO_SECONDS:
                    # Too short — attribute to the last known speaker
                    speaker = self._last_speaker or "Speaker 1"
                else:
                    speaker = self._speaker_tracker.identify(seg_audio, audio_duration=seg_duration)

                if speaker != self._last_speaker:
                    self._last_speaker = speaker
                    output_parts.append(f"\n\n**{speaker}:** {seg_text}")
                else:
                    output_parts.append(seg_text)

            if output_parts:
                combined = " ".join(output_parts)
                # De-duplicate overlap
                combined = self._remove_overlap(combined)
                if combined.strip():
                    self._raw_chunks.append(combined)
                    self._chunk_count += 1
                    self.new_text.emit(combined)

                    # Run Gemini cleanup every ~10 min (async — doesn't block transcription)
                    if (self.ai_cleanup and GEMINI_AVAILABLE and
                            self._chunk_count % self.GEMINI_CLEANUP_EVERY == 0):
                        self._ensure_gemini_ready()
                        if self._gemini_model is not None:
                            if self._gemini_thread is None or not self._gemini_thread.is_alive():
                                snapshot = list(self._raw_chunks)
                                self._gemini_thread = threading.Thread(
                                    target=self._run_gemini_cleanup,
                                    args=(snapshot,),
                                    daemon=True,
                                )
                                self._gemini_thread.start()
                                print(f"Gemini periodic cleanup triggered (chunk {self._chunk_count})")

        except Exception as e:
            print(f"Realtime transcription chunk error: {e}")

    def get_raw_transcript(self) -> str:
        """Return the accumulated raw transcript for post-processing."""
        raw_text = " ".join(self._raw_chunks)
        raw_text = raw_text.replace(" \n\n", "\n\n").replace("\n\n ", "\n\n")
        return raw_text

    def _ensure_gemini_ready(self):
        """Configure Gemini client on first use."""
        if self._gemini_model is not None:
            return  # already configured
        if not self.gemini_api_key:
            print("No Gemini API key provided. AI cleanup disabled.")
            self.ai_cleanup = False
            return
        try:
            genai.configure(api_key=self.gemini_api_key)
            self._gemini_model = genai.GenerativeModel(self.GEMINI_MODEL)
            print(f"Gemini AI cleanup ready ({self.GEMINI_MODEL})")
        except Exception as e:
            print(f"Failed to configure Gemini: {e}. AI cleanup disabled.")
            self.ai_cleanup = False

    def _run_gemini_cleanup(self, chunks_snapshot: list):
        """Run Gemini to fix misheard words (runs in a background thread, periodic during recording)."""
        try:
            raw_text = " ".join(chunks_snapshot)
            raw_text = raw_text.replace(" \n\n", "\n\n").replace("\n\n ", "\n\n")

            words = raw_text.split()

            prompt = (
                "You are an expert post-processor for raw voice transcripts produced by Whisper (an automatic speech recognition system). "
                "Whisper converts speech to text but frequently mishears words, especially:\n"
                "• Technical jargon, product names, abbreviations (e.g., 'air i' → 'AI', 'Jamie and I' → 'Gemini', 'see you for' → 'C4')\n"
                "• Similar-sounding words used in wrong context (e.g., 'voltage strip' → 'raw transcript', 'soft working' → 'stopped working')\n"
                "• Domain-specific terms from gaming, programming, business, medicine, etc. that get turned into common English words\n"
                "• Compound words split or merged incorrectly\n"
                "• Numbers, acronyms, and proper nouns mangled into regular words\n\n"
                "How to fix:\n"
                "1. Read each sentence and ask: does this make sense in the context of what's being discussed?\n"
                "2. If a word/phrase seems out of place, think about what it SOUNDS like and what would make sense.\n"
                "3. Use surrounding context to determine the topic and fix accordingly.\n"
                "4. Be confident — if something reads as nonsense, it IS a recognition error. Fix it.\n"
                "5. Keep the exact same sentence structure, speaker labels (**Speaker N:**), and formatting.\n"
                "6. Do NOT rephrase, merge sentences, or restructure. Do NOT add commentary.\n"
                "7. Output ONLY the corrected transcript, nothing else.\n\n"
                f"Transcript:\n{raw_text}"
            )

            response = self._gemini_model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=len(words) + 500,
                ),
            )

            cleaned = response.text.strip()
            if cleaned and len(cleaned) > 20:
                self.full_text_update.emit(cleaned)
        except Exception as e:
            print(f"Gemini periodic cleanup error: {e}")

    def _remove_overlap(self, text: str) -> str:
        """Remove repeated text from the overlap region between chunks."""
        if not self._prev_tail:
            self._prev_tail = text
            return text

        # Compare last N words of previous chunk with start of current chunk
        prev_words = self._prev_tail.split()
        curr_words = text.split()
        max_overlap = min(len(prev_words), len(curr_words), 8)

        best = 0
        for length in range(1, max_overlap + 1):
            if prev_words[-length:] == curr_words[:length]:
                best = length

        if best > 0:
            text = " ".join(curr_words[best:])

        self._prev_tail = " ".join(curr_words) if curr_words else text
        return text


class DeviceSelectorDialog(QDialog):
    """Dialog for selecting audio devices - Apple Style"""
    
    def __init__(self, device_manager: AudioDeviceManager, parent=None):
        super().__init__(parent)
        self.device_manager = device_manager
        self.selected_mic = None
        self.selected_loopback = None
        
        self.setWindowTitle("Select Audio Devices")
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {APPLE_GRAY_6};
            }}
            QGroupBox {{
                font-weight: 600;
                font-size: 13px;
                color: {APPLE_LABEL};
                border: none;
                margin-top: 15px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 0px;
                padding: 0px 5px 0px 5px;
            }}
            QListWidget {{
                background-color: {CARD_BG};
                border: 1px solid {CARD_BORDER};
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 6px;
            }}
            QListWidget::item:selected {{
                background-color: {APPLE_BLUE};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {APPLE_GRAY_5};
            }}
            QPushButton {{
                background-color: {APPLE_BLUE};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: 500;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: #0051D5;
            }}
            QPushButton:pressed {{
                background-color: #003EAA;
            }}
            QLabel {{
                color: {APPLE_SECONDARY_LABEL};
                font-size: 12px;
            }}
        """)
        
        self.setup_ui()
        self.load_devices()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Title
        title = QLabel("Select Audio Devices")
        title.setStyleSheet(f"font-size: 18px; font-weight: 600; color: {APPLE_LABEL};")
        layout.addWidget(title)
        
        # Microphone section
        mic_group = QGroupBox("Microphone (Your Voice)")
        mic_layout = QVBoxLayout(mic_group)
        mic_layout.setSpacing(8)
        
        self.mic_list = QListWidget()
        self.mic_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.mic_list.setMaximumHeight(120)
        mic_layout.addWidget(self.mic_list)
        layout.addWidget(mic_group)
        
        # System audio section
        loopback_group = QGroupBox("System Audio (Meeting Sound)")
        loopback_layout = QVBoxLayout(loopback_group)
        loopback_layout.setSpacing(8)
        
        self.loopback_list = QListWidget()
        self.loopback_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.loopback_list.setMaximumHeight(100)
        loopback_layout.addWidget(self.loopback_list)
        
        info_label = QLabel(
            "Tip: If no loopback devices appear, enable 'Stereo Mix' in Windows:\n"
            "Right-click speaker icon → Sounds → Recording → Show Disabled Devices → Enable 'Stereo Mix'"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {APPLE_ORANGE}; font-size: 11px; padding: 8px; background-color: #FFF5E6; border-radius: 6px;")
        loopback_layout.addWidget(info_label)
        
        layout.addWidget(loopback_group)
        
        layout.addStretch()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {APPLE_GRAY_5};
                color: {APPLE_LABEL};
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                font-weight: 500;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {APPLE_GRAY_4};
            }}
        """)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("Done")
        ok_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {APPLE_BLUE};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: #0051D5;
            }}
        """)
        ok_btn.clicked.connect(self.accept_selection)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)
    
    def load_devices(self):
        """Load available devices into lists"""
        devices = self.device_manager.scan_devices()
        
        self.mic_list.clear()
        for dev in devices['inputs']:
            item = QListWidgetItem(str(dev))
            item.setData(Qt.ItemDataRole.UserRole, dev)
            self.mic_list.addItem(item)
            if dev.index == sd.default.device[0]:
                self.mic_list.setCurrentItem(item)
        
        self.loopback_list.clear()
        for dev in devices['loopbacks']:
            item = QListWidgetItem(str(dev))
            item.setData(Qt.ItemDataRole.UserRole, dev)
            self.loopback_list.addItem(item)
            self.loopback_list.setCurrentItem(item)
        
        if not devices['loopbacks']:
            item = QListWidgetItem("(No loopback devices found - see tip below)")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(QColor(APPLE_TERTIARY_LABEL))
            self.loopback_list.addItem(item)
    
    def accept_selection(self):
        """Get selected devices and close"""
        mic_item = self.mic_list.currentItem()
        if mic_item:
            self.selected_mic = mic_item.data(Qt.ItemDataRole.UserRole)
        
        loopback_item = self.loopback_list.currentItem()
        if loopback_item:
            self.selected_loopback = loopback_item.data(Qt.ItemDataRole.UserRole)
        
        self.accept()


class RecordButton(QPushButton):
    """Custom circular record button with Apple-style design"""
    
    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setFixedSize(80, 80)
        self.is_recording = False
        self.update_style()
        
    def update_style(self):
        if self.is_recording:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {APPLE_RED};
                    color: white;
                    border: none;
                    border-radius: 20px;
                    font-size: 14px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: #E02C20;
                }}
                QPushButton:pressed {{
                    background-color: #C41E14;
                }}
            """)
            self.setText("Stop")
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {APPLE_RED};
                    color: white;
                    border: 4px solid #FF6B6B;
                    border-radius: 40px;
                    font-size: 0px;
                }}
                QPushButton:hover {{
                    background-color: #E02C20;
                    border: 4px solid #FF8585;
                }}
                QPushButton:pressed {{
                    background-color: #C41E14;
                }}
            """)
            self.setText("")
    
    def set_recording(self, recording):
        self.is_recording = recording
        self.update_style()


class PawiScribeApp(QMainWindow):
    """Main application window - Apple Style Design"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PawiScribe")
        self.setMinimumSize(900, 850)
        
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {APPLE_GRAY_6};
            }}
        """)
        
        self.recorder = DualAudioRecorder()
        self.is_recording = False
        self.temp_dir = tempfile.mkdtemp()
        self.current_audio_path = None
        self.current_output = ""
        self.realtime_worker = None
        self.realtime_texts = []
        self.gemini_api_key = ""
        
        # Load config
        self._load_config()
        
        self.selected_mic_device = None
        self.selected_loopback_device = None
        
        self.setup_ui()
        self.check_dependencies()
        self.scan_devices()
        
    def create_card(self):
        """Create a card widget with Apple-style design"""
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {CARD_BG};
                border: 1px solid {CARD_BORDER};
                border-radius: 12px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(0, 0, 0, 15))
        card.setGraphicsEffect(shadow)
        return card

    def _load_config(self):
        """Load settings from config.json."""
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.gemini_api_key = cfg.get("gemini_api_key", "")
                if self.gemini_api_key:
                    print("Gemini API key loaded from config.json")
                else:
                    print("No Gemini API key in config.json — AI cleanup will be disabled")
        except Exception as e:
            print(f"Could not load config.json: {e}")
    
    def get_checkbox_style(self):
        return f"""
            QCheckBox {{
                font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                font-size: 14px;
                font-weight: 400;
                color: {APPLE_LABEL};
                spacing: 10px;
            }}
            QCheckBox::indicator {{
                width: 20px;
                height: 20px;
                border: 2px solid {APPLE_GRAY_4};
                border-radius: 5px;
                background-color: white;
            }}
            QCheckBox::indicator:checked {{
                background-color: {APPLE_BLUE};
                border-color: {APPLE_BLUE};
            }}
            QCheckBox::indicator:hover {{
                border-color: {APPLE_GRAY_3};
            }}
        """
    
    def get_button_style(self, color=APPLE_BLUE, hover_color="#0051D5"):
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: #003EAA;
            }}
            QPushButton:disabled {{
                background-color: {APPLE_GRAY_4};
                color: {APPLE_GRAY};
            }}
        """
    
    def get_secondary_button_style(self):
        return f"""
            QPushButton {{
                background-color: {APPLE_GRAY_5};
                color: {APPLE_LABEL};
                border: 1px solid {CARD_BORDER};
                border-radius: 8px;
                padding: 10px 20px;
                font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {APPLE_GRAY_4};
            }}
            QPushButton:pressed {{
                background-color: {APPLE_GRAY_3};
            }}
        """
    
    def get_combo_style(self):
        return f"""
            QComboBox {{
                background-color: white;
                border: 1px solid {CARD_BORDER};
                border-radius: 8px;
                padding: 8px 12px;
                font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                font-size: 13px;
                color: {APPLE_LABEL};
                min-width: 120px;
            }}
            QComboBox:hover {{
                border-color: {APPLE_GRAY_3};
            }}
            QComboBox:focus {{
                border-color: {APPLE_BLUE};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {APPLE_GRAY};
            }}
            QComboBox QAbstractItemView {{
                background-color: white;
                border: 1px solid {CARD_BORDER};
                border-radius: 8px;
                selection-background-color: {APPLE_BLUE};
                selection-color: white;
                padding: 4px;
            }}
        """
    
    def get_textedit_style(self):
        return f"""
            QTextEdit {{
                background-color: {CARD_BG};
                border: 1px solid {CARD_BORDER};
                border-radius: 8px;
                padding: 12px;
                font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                font-size: 14px;
                color: {APPLE_LABEL};
                line-height: 1.5;
            }}
            QTextEdit:focus {{
                border-color: {APPLE_BLUE};
            }}
        """
    
    def setup_ui(self):
        """Setup the user interface with Apple-style design"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        
        container = QWidget()
        container.setStyleSheet(f"background-color: {APPLE_GRAY_6};")
        scroll.setWidget(container)
        self.setCentralWidget(scroll)
        
        layout = QVBoxLayout(container)
        layout.setSpacing(20)
        layout.setContentsMargins(32, 32, 32, 32)
        
        # ===== HEADER SECTION =====
        header_container = QWidget()
        header_container.setStyleSheet(f"background: transparent;")
        header_layout = QVBoxLayout(header_container)
        header_layout.setSpacing(8)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel("PawiScribe")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif;
            font-size: 34px;
            font-weight: 700;
            color: {APPLE_LABEL};
            letter-spacing: -0.5px;
        """)
        header_layout.addWidget(title_label)
        
        subtitle = QLabel("Local Meeting Notetaker")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 15px;
            font-weight: 400;
            color: {APPLE_SECONDARY_LABEL};
        """)
        header_layout.addWidget(subtitle)
        
        offline_badge = QLabel("100% Offline")
        offline_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        offline_badge.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 12px;
            font-weight: 500;
            color: {APPLE_GREEN};
            padding: 4px 12px;
        """)
        header_layout.addWidget(offline_badge)
        
        layout.addWidget(header_container)
        layout.addSpacing(10)
        
        # ===== RECORD BUTTON SECTION =====
        record_container = QWidget()
        record_container.setStyleSheet("background: transparent;")
        record_layout = QVBoxLayout(record_container)
        record_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.record_button = RecordButton()
        self.record_button.clicked.connect(self.toggle_recording)
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(6)
        shadow.setColor(QColor(255, 59, 48, 80))
        self.record_button.setGraphicsEffect(shadow)
        
        record_layout.addWidget(self.record_button, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.record_label = QLabel("Tap to Record")
        self.record_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.record_label.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 15px;
            font-weight: 500;
            color: {APPLE_SECONDARY_LABEL};
            margin-top: 12px;
        """)
        record_layout.addWidget(self.record_label)
        
        self.timer_label = QLabel("00:00")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setStyleSheet(f"""
            font-family: 'SF Mono', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
            font-size: 48px;
            font-weight: 200;
            color: {APPLE_LABEL};
            margin-top: 8px;
        """)
        self.timer_label.setVisible(False)
        record_layout.addWidget(self.timer_label)
        
        layout.addWidget(record_container)
        layout.addSpacing(16)
        
        # ===== SETTINGS CARD =====
        settings_card = self.create_card()
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setSpacing(16)
        settings_layout.setContentsMargins(20, 20, 20, 20)
        
        settings_header = QLabel("Settings")
        settings_header.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 11px;
            font-weight: 600;
            color: {APPLE_SECONDARY_LABEL};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        """)
        settings_layout.addWidget(settings_header)
        
        # Audio sources
        sources_layout = QHBoxLayout()
        sources_layout.setSpacing(24)
        
        self.mic_checkbox = QCheckBox("Microphone")
        self.mic_checkbox.setChecked(True)
        self.mic_checkbox.setStyleSheet(self.get_checkbox_style())
        sources_layout.addWidget(self.mic_checkbox)
        
        self.system_audio_checkbox = QCheckBox("System Audio")
        self.system_audio_checkbox.setChecked(False)
        self.system_audio_checkbox.setStyleSheet(self.get_checkbox_style())
        self.system_audio_checkbox.stateChanged.connect(self.on_system_audio_toggled)
        sources_layout.addWidget(self.system_audio_checkbox)
        
        sources_layout.addStretch()
        settings_layout.addLayout(sources_layout)
        
        # Device selection row
        device_row = QHBoxLayout()
        self.device_button = QPushButton("Select Devices...")
        self.device_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {APPLE_BLUE};
                border: 1px solid {CARD_BORDER};
                border-radius: 8px;
                padding: 8px 16px;
                font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {APPLE_GRAY_5};
                border-color: {APPLE_GRAY_4};
            }}
        """)
        self.device_button.clicked.connect(self.show_device_selector)
        device_row.addWidget(self.device_button)
        
        self.device_status_label = QLabel("Scanning...")
        self.device_status_label.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 12px;
            color: {APPLE_SECONDARY_LABEL};
        """)
        device_row.addWidget(self.device_status_label)
        device_row.addStretch()
        
        settings_layout.addLayout(device_row)
        
        # Model row
        options_row = QHBoxLayout()
        options_row.setSpacing(16)
        
        model_label = QLabel("Model:")
        model_label.setStyleSheet(f"font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif; font-size: 13px; color: {APPLE_LABEL};")
        options_row.addWidget(model_label)
        
        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "base", "small", "medium", "large"])
        self.model_combo.setCurrentText("base")
        self.model_combo.setStyleSheet(self.get_combo_style())
        options_row.addWidget(self.model_combo)
        
        self.realtime_checkbox = QCheckBox("Live Transcription")
        self.realtime_checkbox.setChecked(True)
        self.realtime_checkbox.setStyleSheet(self.get_checkbox_style())
        options_row.addWidget(self.realtime_checkbox)

        self.ai_cleanup_checkbox = QCheckBox("AI Cleanup")
        self.ai_cleanup_checkbox.setChecked(True)
        self.ai_cleanup_checkbox.setToolTip("Use Gemini Flash Lite to fix misheard words in real-time")
        self.ai_cleanup_checkbox.setStyleSheet(self.get_checkbox_style())
        options_row.addWidget(self.ai_cleanup_checkbox)
        
        options_row.addStretch()
        settings_layout.addLayout(options_row)
        
        layout.addWidget(settings_card)
        
        # ===== STATUS & PROGRESS =====
        self.status_label = QLabel("Ready to record")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 14px;
            font-weight: 500;
            color: {APPLE_SECONDARY_LABEL};
            padding: 8px;
        """)
        layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background-color: {APPLE_GRAY_5};
                height: 4px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {APPLE_BLUE};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self.progress_bar)
        
        # ===== OUTPUT CARD =====
        output_card = self.create_card()
        output_layout = QVBoxLayout(output_card)
        output_layout.setSpacing(16)
        output_layout.setContentsMargins(20, 20, 20, 20)
        
        # Splitter for side-by-side raw vs AI-cleaned transcripts
        self.transcript_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.transcript_splitter.setMinimumHeight(200)
        self.transcript_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {APPLE_GRAY_4};
                width: 2px;
            }}
        """)

        # --- Left pane: Raw transcript ---
        raw_pane = QWidget()
        raw_layout = QVBoxLayout(raw_pane)
        raw_layout.setContentsMargins(0, 0, 4, 0)
        raw_layout.setSpacing(6)
        raw_header = QLabel("Raw Transcript")
        raw_header.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 11px;
            font-weight: 600;
            color: {APPLE_SECONDARY_LABEL};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        """)
        raw_layout.addWidget(raw_header)
        self.output_text = QTextEdit()
        self.output_text.setPlaceholderText("Raw transcript will appear here...")
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet(self.get_textedit_style())
        raw_layout.addWidget(self.output_text)
        self.transcript_splitter.addWidget(raw_pane)

        # --- Right pane: AI-cleaned transcript ---
        ai_pane = QWidget()
        ai_layout = QVBoxLayout(ai_pane)
        ai_layout.setContentsMargins(4, 0, 0, 0)
        ai_layout.setSpacing(6)
        ai_header = QLabel("AI Cleaned")
        ai_header.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 11px;
            font-weight: 600;
            color: {APPLE_BLUE};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        """)
        ai_layout.addWidget(ai_header)
        self.ai_output_text = QTextEdit()
        self.ai_output_text.setPlaceholderText("AI-cleaned transcript will appear here...")
        self.ai_output_text.setReadOnly(True)
        self.ai_output_text.setStyleSheet(self.get_textedit_style())
        ai_layout.addWidget(self.ai_output_text)
        self.transcript_splitter.addWidget(ai_pane)

        self.transcript_splitter.setSizes([500, 500])  # equal split
        output_layout.addWidget(self.transcript_splitter)
        
        # Action buttons
        action_layout = QHBoxLayout()
        action_layout.setSpacing(12)
        
        self.copy_button = QPushButton("Copy")
        self.copy_button.setStyleSheet(self.get_secondary_button_style())
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        self.copy_button.setEnabled(False)
        action_layout.addWidget(self.copy_button)
        
        self.save_button = QPushButton("Save as .md")
        self.save_button.setStyleSheet(self.get_button_style(APPLE_BLUE, "#0051D5"))
        self.save_button.clicked.connect(self.save_markdown)
        self.save_button.setEnabled(False)
        action_layout.addWidget(self.save_button)
        
        self.clear_button = QPushButton("Clear")
        self.clear_button.setStyleSheet(self.get_secondary_button_style())
        self.clear_button.clicked.connect(self.clear_output)
        action_layout.addWidget(self.clear_button)
        
        action_layout.addStretch()
        output_layout.addLayout(action_layout)
        
        layout.addWidget(output_card)
        layout.addStretch()
        
        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_timer)
        self.recording_seconds = 0
    
    def scan_devices(self):
        """Scan for available audio devices"""
        try:
            devices = self.recorder.scan_devices()
            self.selected_mic_device = self.recorder.device_manager.get_default_input_device()
            self.selected_loopback_device = self.recorder.device_manager.get_default_loopback_device()
            self.update_device_status()
        except Exception as e:
            self.device_status_label.setText(f"Device scan failed: {e}")
    
    def update_device_status(self):
        """Update the device status label"""
        mic_name = self.selected_mic_device.name if self.selected_mic_device else "Not found"
        loopback_name = self.selected_loopback_device.name if self.selected_loopback_device else "Not available"
        has_loopback = self.selected_loopback_device is not None
        status_text = f"Mic: {mic_name[:30]}{'...' if len(mic_name) > 30 else ''}"
        if has_loopback:
            status_text += f" | System: {loopback_name[:20]}{'...' if len(loopback_name) > 20 else ''}"
        self.device_status_label.setText(status_text)
    
    def on_system_audio_toggled(self, state):
        """Handle system audio checkbox toggle"""
        self.update_device_status()
    
    def show_device_selector(self):
        """Show the device selector dialog"""
        dialog = DeviceSelectorDialog(self.recorder.device_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.selected_mic:
                self.selected_mic_device = dialog.selected_mic
            if dialog.selected_loopback:
                self.selected_loopback_device = dialog.selected_loopback
            self.update_device_status()
    
    def check_dependencies(self):
        """Check if required dependencies are available"""
        warnings = []
        if not SOUNDDEVICE_AVAILABLE:
            warnings.append("sounddevice not installed (required for recording)")
        if not WHISPER_AVAILABLE:
            warnings.append("openai-whisper not installed (required for transcription)")
        if warnings:
            msg = "Missing dependencies:\n" + "\n".join(warnings)
            msg += "\n\nInstall with: pip install -r requirements.txt"
            QMessageBox.warning(self, "Missing Dependencies", msg)
    
    def toggle_recording(self):
        """Toggle recording state"""
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()
    
    def start_recording(self):
        """Start recording audio"""
        if not SOUNDDEVICE_AVAILABLE:
            QMessageBox.critical(self, "Error", "sounddevice not available. Install with: pip install sounddevice")
            return
        if not self.mic_checkbox.isChecked() and not self.system_audio_checkbox.isChecked():
            QMessageBox.warning(self, "No Audio Source", "Please select at least one audio source.")
            return
        
        capture_mic = self.mic_checkbox.isChecked()
        capture_system = self.system_audio_checkbox.isChecked()
        
        if capture_system and not self.selected_loopback_device:
            reply = QMessageBox.question(
                self, "System Audio Not Available",
                "No loopback device detected. Record with microphone only?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            capture_system = False
            self.system_audio_checkbox.setChecked(False)
        
        self.recorder.set_capture_options(microphone=capture_mic, system_audio=capture_system)
        self.recorder.set_devices(
            microphone=self.selected_mic_device if capture_mic else None,
            loopback=self.selected_loopback_device if capture_system else None
        )
        
        try:
            self.recorder.start_recording()
            self.is_recording = True
            self.record_button.set_recording(True)
            self.record_label.setText("Tap to Stop")
            self.timer_label.setVisible(True)
            self.mic_checkbox.setEnabled(False)
            self.system_audio_checkbox.setEnabled(False)
            self.device_button.setEnabled(False)
            self.model_combo.setEnabled(False)
            self.realtime_checkbox.setEnabled(False)
            self.ai_cleanup_checkbox.setEnabled(False)
            self.recording_seconds = 0
            self.timer.start(1000)
            self.update_timer()

            # Start real-time transcription if enabled
            if self.realtime_checkbox.isChecked():
                self.realtime_texts = []
                self.output_text.clear()
                self.output_text.setPlaceholderText("")
                self.ai_output_text.clear()
                self.ai_output_text.setPlaceholderText("Waiting for AI cleanup pass...")
                self.realtime_worker = RealtimeTranscriptionWorker(
                    self.recorder, self.model_combo.currentText(),
                    ai_cleanup=self.ai_cleanup_checkbox.isChecked(),
                    gemini_api_key=self.gemini_api_key
                )
                self.realtime_worker.new_text.connect(self.on_realtime_text)
                self.realtime_worker.full_text_update.connect(self.on_full_text_update)
                self.realtime_worker.model_ready.connect(self.on_realtime_model_ready)
                self.realtime_worker.error.connect(self.on_transcription_error)
                self.realtime_worker.start()
                self.status_label.setText("Loading model...")
                self.status_label.setStyleSheet(f"""
                    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                    font-size: 14px;
                    font-weight: 500;
                    color: {APPLE_ORANGE};
                    padding: 8px;
                """)
            else:
                self.status_label.setText("Recording...")
                self.status_label.setStyleSheet(f"""
                    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                    font-size: 14px;
                    font-weight: 500;
                    color: {APPLE_RED};
                    padding: 8px;
                """)
        except Exception as e:
            QMessageBox.critical(self, "Recording Error", str(e))

    def on_realtime_model_ready(self):
        """Called when the Whisper model finishes loading during recording."""
        self.status_label.setText("Recording — Live transcription active")
        self.status_label.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 14px;
            font-weight: 500;
            color: {APPLE_GREEN};
            padding: 8px;
        """)

    def on_realtime_text(self, text):
        """Handle new text from real-time transcription."""
        if not text.strip():
            return
        self.realtime_texts.append(text)
        # Join with space but preserve newlines from speaker changes
        display = " ".join(self.realtime_texts)
        # Clean up extra spaces around newlines
        display = display.replace(" \n\n", "\n\n").replace("\n\n ", "\n\n")
        self.output_text.setPlainText(display)
        # Auto-scroll to bottom
        scrollbar = self.output_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.copy_button.setEnabled(True)
        self.save_button.setEnabled(True)

    def on_full_text_update(self, cleaned_text):
        """Handle full transcript replacement from Gemini cleanup — goes to AI pane only."""
        if not cleaned_text.strip():
            return
        # Show cleaned version in the AI pane (raw pane stays untouched)
        self.ai_output_text.setPlainText(cleaned_text)
        # Auto-scroll to bottom
        scrollbar = self.ai_output_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _post_process_gemini(self, raw_transcript: str):
        """Run a single Gemini call to clean up the entire transcript (background thread)."""
        try:
            genai.configure(api_key=self.gemini_api_key)
            model = genai.GenerativeModel("gemini-flash-lite-latest")

            words = raw_transcript.split()
            prompt = (
                "You are an expert post-processor for raw voice transcripts produced by Whisper (an automatic speech recognition system). "
                "Your task has TWO parts:\n\n"

                "═══ PART 1: TRANSCRIPT CORRECTION ═══\n"
                "Whisper converts speech to text but frequently mishears words, especially:\n"
                "• Technical jargon, product names, abbreviations (e.g., 'air i' → 'AI', 'Jamie and I' → 'Gemini', 'see you for' → 'C4')\n"
                "• Similar-sounding words used in wrong context (e.g., 'voltage strip' → 'raw transcript', 'soft working' → 'stopped working')\n"
                "• Domain-specific terms from gaming, programming, business, medicine, etc. that get turned into common English words\n"
                "• Compound words split or merged incorrectly\n"
                "• Numbers, acronyms, and proper nouns mangled into regular words\n\n"

                "How to fix:\n"
                "1. Read each sentence and ask: does this make sense in the context of what's being discussed?\n"
                "2. If a word/phrase seems out of place, think about what it SOUNDS like and what would make sense.\n"
                "3. Use surrounding context to determine the topic (e.g., if they're discussing a video game, "
                "words like 'levees' probably mean 'levies', 'CV' means 'CB/casus belli', 'burger ones' means 'Burgundian').\n"
                "4. Be confident — if something reads as nonsense, it IS a recognition error. Fix it.\n"
                "5. Keep the exact same sentence structure, speaker labels (**Speaker N:**), and formatting.\n"
                "6. Do NOT rephrase, merge sentences, or restructure the text.\n\n"

                "═══ PART 2: MEETING SUMMARY ═══\n"
                "After the corrected transcript, add a concise summary section with:\n"
                "• A brief overview of what was discussed (2-4 sentences)\n"
                "• Key topics or decisions mentioned\n"
                "• Action items if any were mentioned\n"
                "• Number of participants detected\n\n"

                "═══ OUTPUT FORMAT ═══\n"
                "Output EXACTLY in this format (no other commentary):\n\n"
                "## Corrected Transcript\n\n"
                "[corrected transcript here, preserving all Speaker labels and line breaks]\n\n"
                "---\n\n"
                "## Meeting Summary\n\n"
                "**Overview:** [2-4 sentence summary]\n\n"
                "**Key Topics:**\n"
                "- [topic 1]\n"
                "- [topic 2]\n\n"
                "**Action Items:**\n"
                "- [item, or 'None identified']\n\n"
                "**Participants:** [N speaker(s) detected]\n\n"

                f"═══ RAW TRANSCRIPT ═══\n{raw_transcript}"
            )

            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=len(words) + 1000,
                ),
            )

            cleaned = response.text.strip()
            if cleaned and len(cleaned) > 20:
                self._gemini_result = cleaned
            else:
                self._gemini_result = "__FAILED__"
        except Exception as e:
            print(f"Gemini post-process error: {e}")
            self._gemini_result = "__FAILED__"

    def _check_gemini_done(self):
        """Timer callback to check if the background Gemini cleanup finished."""
        if hasattr(self, '_gemini_result') and self._gemini_result:
            result = self._gemini_result
            self._gemini_result = None
            self._gemini_poll_timer.stop()

            if result != "__FAILED__":
                self.ai_output_text.setPlainText(result)
                self.status_label.setText("Transcription complete! (AI cleaned)")
            else:
                self.ai_output_text.setPlainText("AI cleanup failed — see raw transcript")
                self.status_label.setText("Transcription complete (AI cleanup failed)")

            self.status_label.setStyleSheet(f"""
                font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                font-size: 14px;
                font-weight: 500;
                color: {APPLE_GREEN};
                padding: 8px;
            """)
            self.reset_ui_controls()
    
    def update_timer(self):
        """Update the recording timer display"""
        self.recording_seconds += 1
        mins = self.recording_seconds // 60
        secs = self.recording_seconds % 60
        self.timer_label.setText(f"{mins:02d}:{secs:02d}")
    
    def stop_recording(self):
        """Stop recording and start transcription"""
        if not self.is_recording:
            return
        self.timer.stop()
        self.status_label.setText("Processing...")

        # Stop realtime worker first so it can do a final pass
        if self.realtime_worker and self.realtime_worker.isRunning():
            self.realtime_worker.stop()
            if not self.realtime_worker.wait(15000):  # 15s for final transcription
                print("Warning: realtime worker did not finish in time")
            self.realtime_worker = None

        audio_data = self.recorder.stop_recording()
        self.is_recording = False
        self.record_button.set_recording(False)
        self.record_label.setText("Tap to Record")
        self.timer_label.setVisible(False)
        
        if audio_data is None or len(audio_data) == 0:
            QMessageBox.warning(self, "Warning", "No audio recorded!")
            self.reset_ui()
            return

        # If realtime was on, we already have the transcript — generate final output
        if self.realtime_checkbox.isChecked() and self.realtime_texts:
            full_transcript = " ".join(self.realtime_texts)
            now = datetime.datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M")

            output = f"""# Meeting Notes - {date_str}

**Date:** {date_str}  
**Time:** {time_str}  
**Duration:** {self.recording_seconds // 60}m {self.recording_seconds % 60}s

---

## Transcript

{full_transcript}

---

*Generated by PawiScribe - Local Meeting Notetaker (Live Transcription)*
"""
            self.current_output = output
            self.output_text.setPlainText(output)
            self.copy_button.setEnabled(True)
            self.save_button.setEnabled(True)

            # Run Gemini cleanup as a single post-processing pass
            if (self.ai_cleanup_checkbox.isChecked() and GEMINI_AVAILABLE
                    and self.gemini_api_key):
                self.status_label.setText("Running AI cleanup...")
                self.status_label.setStyleSheet(f"""
                    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                    font-size: 14px;
                    font-weight: 500;
                    color: {APPLE_ORANGE};
                    padding: 8px;
                """)
                self.ai_output_text.setPlainText("Running AI cleanup...")
                self._gemini_result = None
                # Run in background thread so UI stays responsive
                self._gemini_cleanup_thread = threading.Thread(
                    target=self._post_process_gemini,
                    args=(full_transcript,),
                    daemon=True,
                )
                self._gemini_cleanup_thread.start()
                # Poll every 500ms for completion
                self._gemini_poll_timer = QTimer(self)
                self._gemini_poll_timer.timeout.connect(self._check_gemini_done)
                self._gemini_poll_timer.start(500)
            else:
                self.status_label.setText("Transcription complete!")
                self.status_label.setStyleSheet(f"""
                    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
                    font-size: 14px;
                    font-weight: 500;
                    color: {APPLE_GREEN};
                    padding: 8px;
                """)
                self.reset_ui_controls()
            return

        # Otherwise, do the normal batch transcription
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_audio_path = os.path.join(self.temp_dir, f"recording_{timestamp}.wav")
        self.recorder.save_to_wav(audio_data, self.current_audio_path)
        self.start_transcription()

    def reset_ui_controls(self):
        """Re-enable all settings controls after recording."""
        self.record_button.set_recording(False)
        self.record_button.setEnabled(True)
        self.mic_checkbox.setEnabled(True)
        self.system_audio_checkbox.setEnabled(True)
        self.device_button.setEnabled(True)
        self.model_combo.setEnabled(True)
        self.realtime_checkbox.setEnabled(True)
        self.ai_cleanup_checkbox.setEnabled(True)
        self.timer_label.setVisible(False)

    def start_transcription(self):
        """Start the transcription worker thread"""
        model_size = self.model_combo.currentText()
        self.worker = TranscriptionWorker(self.current_audio_path, model_size)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_transcription_finished)
        self.worker.error.connect(self.on_transcription_error)
        self.progress_bar.setVisible(True)
        self.record_button.setEnabled(False)
        self.worker.start()
    
    def on_progress(self, message):
        """Handle progress updates"""
        self.status_label.setText(message)
    
    def on_transcription_finished(self, output):
        """Handle transcription completion"""
        self.current_output = output
        self.output_text.setPlainText(output)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Transcription complete!")
        self.status_label.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 14px;
            font-weight: 500;
            color: {APPLE_GREEN};
            padding: 8px;
        """)
        self.copy_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.record_button.setEnabled(True)
        self.model_combo.setEnabled(True)
        self.mic_checkbox.setEnabled(True)
        self.system_audio_checkbox.setEnabled(True)
        self.device_button.setEnabled(True)
        try:
            if self.current_audio_path and os.path.exists(self.current_audio_path):
                os.remove(self.current_audio_path)
        except:
            pass
    
    def on_transcription_error(self, error_message):
        """Handle transcription errors"""
        self.progress_bar.setVisible(False)
        self.status_label.setText("Error occurred")
        self.status_label.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 14px;
            font-weight: 500;
            color: {APPLE_RED};
            padding: 8px;
        """)
        QMessageBox.critical(self, "Transcription Error", error_message)
        self.reset_ui()
    
    def reset_ui(self):
        """Reset UI to initial state"""
        self.record_button.set_recording(False)
        self.record_button.setEnabled(True)
        self.record_label.setText("Tap to Record")
        self.timer_label.setVisible(False)
        self.mic_checkbox.setEnabled(True)
        self.system_audio_checkbox.setEnabled(True)
        self.device_button.setEnabled(True)
        self.model_combo.setEnabled(True)
        self.realtime_checkbox.setEnabled(True)
        self.ai_cleanup_checkbox.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Ready to record")
        self.status_label.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 14px;
            font-weight: 500;
            color: {APPLE_SECONDARY_LABEL};
            padding: 8px;
        """)
    
    def copy_to_clipboard(self):
        """Copy output to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.current_output)
        self.status_label.setText("Copied to clipboard!")
        QTimer.singleShot(2000, lambda: self.status_label.setText("Ready"))
    
    def save_markdown(self):
        """Save output as markdown file"""
        default_name = f"meeting_notes_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M')}.md"
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Meeting Notes", default_name, "Markdown Files (*.md);;All Files (*)"
        )
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(self.current_output)
                self.status_label.setText(f"Saved!")
                QTimer.singleShot(2000, lambda: self.status_label.setText("Ready"))
            except Exception as e:
                QMessageBox.critical(self, "Save Error", str(e))
    
    def clear_output(self):
        """Clear the output area"""
        self.output_text.clear()
        self.ai_output_text.clear()
        self.current_output = ""
        self.copy_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.status_label.setText("Ready to record")
    
    def closeEvent(self, event):
        """Clean up on close"""
        if self.realtime_worker and self.realtime_worker.isRunning():
            self.realtime_worker.stop()
            if not self.realtime_worker.wait(10000):  # 10s grace period
                self.realtime_worker.terminate()  # force kill as last resort
                self.realtime_worker.wait(2000)
        try:
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except:
            pass
        event.accept()


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    font = QFont("-apple-system", 10)
    app.setFont(font)
    window = PawiScribeApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
