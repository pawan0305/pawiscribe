#!/usr/bin/env python3
"""
PawiScribe v2.0.0 - Local Meeting Notetaker - Apple Style UI
Records audio (microphone + system audio), transcribes with Whisper, and summarizes with Ollama (optional)
100% offline - no API calls required

Author: PawiBot Team
License: MIT
"""

__version__ = "2.0.0"

import sys
import os
import io
import wave
import threading
import datetime
import tempfile
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict

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
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QTextEdit, QLabel, QProgressBar, QFileDialog,
        QMessageBox, QComboBox, QGroupBox, QCheckBox, QSpinBox,
        QDialog, QListWidget, QListWidgetItem, QFrame, QGraphicsDropShadowEffect,
        QSizePolicy, QScrollArea, QSpacerItem
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
                
                if 'WASAPI' in hostapi_name and dev['max_input_channels'] > 0:
                    name_lower = dev['name'].lower()
                    if any(keyword in name_lower for keyword in ['loopback', 'stereo mix', 'what u hear']):
                        device.is_loopback = True
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
        """Start the WASAPI loopback stream for system audio"""
        def loopback_callback(indata, frames_count, time_info, status):
            if self.recording:
                self.system_audio_frames.append(indata.copy())
        
        try:
            print(f"Using loopback device: {self.loopback_device.name}")
            self.loopback_stream = sd.InputStream(
                device=self.loopback_device.index,
                samplerate=self.sample_rate,
                channels=self.channels,
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
    
    def _mix_audio(self) -> Optional[np.ndarray]:
        """Mix microphone and system audio into a single track"""
        mic_data = None
        loopback_data = None
        
        if self.microphone_frames:
            mic_data = np.concatenate(self.microphone_frames, axis=0)
        
        if self.system_audio_frames:
            loopback_data = np.concatenate(self.system_audio_frames, axis=0)
        
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
        else:
            return None
    
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
    
    def __init__(self, audio_path, model_size="base", use_ollama=False):
        super().__init__()
        self.audio_path = audio_path
        self.model_size = model_size
        self.use_ollama = use_ollama
        
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
            
            summary = ""
            if self.use_ollama:
                summary = self.generate_summary(transcript)
            
            output = self.create_markdown_output(formatted_transcript, summary)
            
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
    
    def generate_summary(self, transcript):
        """Generate summary using Ollama"""
        try:
            self.progress.emit("Generating summary with Ollama...")
            
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                return "(Ollama not available - skipping summary)"
            
            prompt = f"""Please provide a concise summary of the following meeting transcript. 
Include key points, decisions made, and action items.

Transcript:
{transcript[:4000]}

Summary:"""
            
            models_to_try = ["phi4", "llama3.2", "gemma2:2b", "llama3.1:latest"]
            available_model = None
            
            for model in models_to_try:
                check = subprocess.run(["ollama", "list"], capture_output=True, text=True)
                if model in check.stdout:
                    available_model = model
                    break
            
            if not available_model:
                return "(No suitable Ollama model found. Pull one with: ollama pull llama3.2)"
            
            result = subprocess.run(
                ["ollama", "run", available_model, prompt],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return f"(Summary generation failed: {result.stderr})"
                
        except subprocess.TimeoutExpired:
            return "(Summary generation timed out)"
        except Exception as e:
            return f"(Summary unavailable: {str(e)})"
    
    def create_markdown_output(self, transcript, summary=""):
        """Create formatted markdown output"""
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")
        
        output = f"""# Meeting Notes - {date_str}

**Date:** {date_str}  
**Time:** {time_str}  
**Duration:** (recorded via PawiScribe)

---

## Attendees

- (Speaker names not automatically detected)

---

## Summary

{summary if summary else "(No summary generated - Ollama not available or disabled)"}

---

## Transcript

{transcript}

---

*Generated by PawiScribe - Local Meeting Notetaker*
"""
        return output



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
        
        # Model and Ollama row
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
        
        self.ollama_checkbox = QCheckBox("Use Ollama Summary")
        self.ollama_checkbox.setStyleSheet(self.get_checkbox_style())
        options_row.addWidget(self.ollama_checkbox)
        
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
        
        output_header = QLabel("Meeting Notes")
        output_header.setStyleSheet(f"""
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
            font-size: 11px;
            font-weight: 600;
            color: {APPLE_SECONDARY_LABEL};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        """)
        output_layout.addWidget(output_header)
        
        self.output_text = QTextEdit()
        self.output_text.setPlaceholderText("Transcript will appear here after recording...")
        self.output_text.setReadOnly(True)
        self.output_text.setMinimumHeight(200)
        self.output_text.setStyleSheet(self.get_textedit_style())
        output_layout.addWidget(self.output_text)
        
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
            self.ollama_checkbox.setEnabled(False)
            self.recording_seconds = 0
            self.timer.start(1000)
            self.update_timer()
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
        audio_data = self.recorder.stop_recording()
        self.is_recording = False
        self.record_button.set_recording(False)
        self.record_label.setText("Tap to Record")
        self.timer_label.setVisible(False)
        
        if audio_data is None or len(audio_data) == 0:
            QMessageBox.warning(self, "Warning", "No audio recorded!")
            self.reset_ui()
            return
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_audio_path = os.path.join(self.temp_dir, f"recording_{timestamp}.wav")
        self.recorder.save_to_wav(audio_data, self.current_audio_path)
        self.start_transcription()
    
    def start_transcription(self):
        """Start the transcription worker thread"""
        model_size = self.model_combo.currentText()
        use_ollama = self.ollama_checkbox.isChecked()
        self.worker = TranscriptionWorker(self.current_audio_path, model_size, use_ollama)
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
        self.ollama_checkbox.setEnabled(True)
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
        self.ollama_checkbox.setEnabled(True)
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
        self.current_output = ""
        self.copy_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.status_label.setText("Ready to record")
    
    def closeEvent(self, event):
        """Clean up on close"""
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
