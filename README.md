# PawiScribe - Local Meeting Notetaker

A 100% offline meeting notetaker for Windows that records audio (microphone + system audio), transcribes with OpenAI Whisper, and optionally summarizes with Ollama.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## ✨ Features

- 🎤 **Dual Audio Recording** - Record both microphone AND system audio simultaneously
- 🔊 **System Audio Capture** - Capture meeting audio from Teams/Zoom/Meet calls
- 🤖 **Local Transcription** - Uses OpenAI Whisper (runs entirely offline)
- 📝 **Smart Summaries** - Optional AI summaries via Ollama (local LLM)
- 📄 **Markdown Export** - Clean, shareable meeting notes
- 🔒 **100% Private** - No data leaves your computer
- 💻 **Windows Native** - Built for Windows 10/11 with WASAPI loopback support

## 🚀 Quick Start

### Prerequisites

- Windows 10 or 11
- Python 3.9 or higher ([Download](https://www.python.org/downloads/))
- (Optional) Ollama for AI summaries ([Download](https://ollama.com/))

### Installation

1. **Clone or download this repository:**
   ```bash
   git clone <repository-url>
   cd pawiscribe
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   
   > **Note:** First run will download the Whisper model (~150MB for base model)

4. **Enable Stereo Mix for system audio capture** (see [System Audio Setup](#-system-audio-setup) below)

5. **Run the application:**
   ```bash
   python main.py
   ```

## 🎧 System Audio Setup

To capture meeting audio from Teams/Zoom/Meet (not just your microphone), you need to enable **Stereo Mix** in Windows:

### Enabling Stereo Mix (Windows 10/11)

1. **Right-click** the speaker icon in your system tray → Click **"Sounds"**

2. Go to the **Recording** tab

3. **Right-click** in the empty area → Check **"Show Disabled Devices"**

4. Look for **"Stereo Mix"** or **"What U Hear"** in the list

5. **Right-click** on it → Click **"Enable"**

6. Click **"OK"** to save

![Stereo Mix Setup](docs/stereo-mix-setup.png)

### Alternative: VB-Cable (If Stereo Mix Not Available)

Some sound cards don't expose Stereo Mix. Use VB-Cable as an alternative:

1. Download [VB-Cable](https://vb-audio.com/Cable/) (free virtual audio cable)
2. Install and set as your default playback device
3. In PawiScribe, the microphone will capture the "cable" output
4. **Limitation:** You won't hear audio through your speakers while recording

### Alternative: VoiceMeeter (Advanced)

For more control over audio routing:

1. Download [VoiceMeeter Banana](https://vb-audio.com/Voicemeeter/banana.htm)
2. Route system audio to both your speakers and a virtual microphone
3. Select the virtual microphone in PawiScribe

## 📖 Usage

1. **Configure Audio Sources:**
   - Check **"Capture my microphone"** to record your voice
   - Check **"Capture system audio"** to record meeting sound (requires Stereo Mix)
   - Click **"Select Audio Devices..."** to choose specific devices

2. **Start Recording:** Click the green **"Start Recording"** button

3. **Join Your Meeting:** The app captures audio from both sources

4. **Stop:** Click **"Stop & Transcribe"** when done

5. **Wait:** Transcription happens locally (progress shown)

6. **Export:** Copy to clipboard or save as Markdown file

### Audio Source Indicators

- 🎤 **Microphone**: Your voice (via selected input device)
- 🔊 **System Audio**: Meeting audio from Teams/Zoom/Meet (via Stereo Mix loopback)

## ⚙️ Settings

- **Whisper Model:** Choose accuracy vs speed
  - `tiny` - Fastest, lowest accuracy
  - `base` - Balanced (recommended)
  - `small` - Better accuracy, slower
  - `medium/large` - Best accuracy, requires more RAM/CPU

- **Ollama Summary:** Check to enable AI-generated summaries (requires Ollama)

## 🔧 Advanced Setup

### Installing Ollama (Optional)

For AI-generated meeting summaries:

1. Download and install Ollama from [ollama.com](https://ollama.com/)
2. Open a terminal and pull a model:
   ```bash
   ollama pull llama3.2
   # or
   ollama pull phi4
   ```
3. Restart PawiScribe and enable "Use Ollama for Summary"

### Optimizing for CPU-Only Systems

If you don't have a GPU, use CPU-optimized PyTorch:

```bash
pip uninstall torch
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### Faster Transcription (Optional)

Replace `openai-whisper` with `faster-whisper` for 4x speedup:

```bash
pip uninstall openai-whisper
pip install faster-whisper
```

Then modify `main.py` line 20 to use faster_whisper.

## 🛠️ Troubleshooting

### "No loopback device found" warning

This means Stereo Mix is not enabled. Follow the [System Audio Setup](#-system-audio-setup) steps above.

### "No audio recorded" error

- Check that your microphone is connected and enabled in Windows
- Check Windows Privacy Settings → Microphone → Allow apps to access microphone
- Try a different microphone device via "Select Audio Devices..."

### "Stereo Mix not available" on your PC

Some sound cards (especially on laptops) don't expose Stereo Mix. Try:

- Update your audio drivers from the manufacturer's website
- Use VB-Cable or VoiceMeeter as alternatives (see above)
- Use the microphone-only mode (still captures your side of the conversation)

### Only one side of conversation is recorded

- Make sure both **"Capture my microphone"** AND **"Capture system audio"** are checked
- Verify Stereo Mix is enabled and selected as the system audio source
- Test by playing audio while recording - you should see the recording level indicator respond

### "Whisper model download fails"

Models are downloaded automatically on first use. If it fails:
```bash
python -c "import whisper; whisper.load_model('base')"
```

### "Ollama not found"

Make sure Ollama is installed and running. Test with:
```bash
ollama list
```

### Slow transcription

- Use a smaller model (`tiny` or `base`)
- Close other applications to free up RAM
- Consider using `faster-whisper` (see Advanced Setup)

## 📁 Output Format

Saved meeting notes look like this:

```markdown
# Meeting Notes - 2024-01-15

**Date:** 2024-01-15  
**Time:** 14:30  
**Duration:** (recorded via PawiScribe)

---

## Attendees

- (Speaker names not automatically detected)

---

## Summary

(Key points and decisions from the meeting)

---

## Transcript

[00:00] Welcome everyone to the weekly sync...
[00:45] Let's start with project updates...

---

*Generated by PawiScribe - Local Meeting Notetaker*
```

## 🏗️ Building an Executable

### Option 1: Download Pre-built Executable

**No Python installation required!**

Download `PawiScribe.exe` from the [Releases](https://github.com/yourusername/pawiscribe/releases) page and double-click to run.

See [INSTALL.txt](INSTALL.txt) for detailed installation instructions.

### Option 2: Build from Source (Windows)

To create a standalone `.exe` file from source:

```batch
# Install PyInstaller
pip install pyinstaller

# Build using the spec file (recommended)
pyinstaller pawiscribe.spec

# Or build with command line (simpler but less optimized):
pyinstaller --onefile --windowed --name PawiScribe --hidden-import=numpy --hidden-import=scipy --hidden-import=sounddevice --hidden-import=whisper --hidden-import=torch --hidden-import=PyQt6 main.py
```

The executable will be in `dist/PawiScribe.exe`

For convenience, use the provided build script:
```batch
build_exe.bat
```

### Build Requirements

- Windows 10/11 (building on Windows is required for Windows executables)
- Python 3.9+ with all dependencies installed (`pip install -r requirements.txt`)
- PyInstaller (`pip install pyinstaller`)
- ~2GB free disk space for build process
- ~5-15 minutes build time depending on system

### What's Included in the Executable

The standalone `.exe` includes:
- Python runtime
- All required libraries (PyQt6, Whisper, Torch, etc.)
- Configuration file
- **Excludes:** Whisper model files (downloaded on first run, ~150MB)

### Distribution Size

- **PawiScribe.exe**: ~200-500 MB (varies with compression)
- **First run download**: ~150 MB (Whisper model)
- **Total after first run**: ~350-650 MB

### Known Limitations of Standalone Build

1. **First Run Model Download**: The Whisper model (~150MB) is downloaded on first use, not bundled in the .exe
2. **Windows Defender**: May show SmartScreen warning since the app isn't code-signed
3. **Antivirus**: Some antivirus software may flag PyInstaller-built executables (false positive)
4. **Stereo Mix**: Still requires manual enable in Windows sound settings
5. **No macOS/Linux**: The .exe is Windows-only

## 📋 System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Windows 10 | Windows 11 |
| RAM | 4 GB | 8 GB+ |
| Storage | 500 MB | 2 GB (for models) |
| Microphone | Any | USB headset |
| Internet | Not required | For initial install only |
| Stereo Mix | Required for system audio | Native Windows support |

## 🤝 Contributing

Contributions welcome! Areas for improvement:

- Real-time transcription
- Speaker diarization (who spoke when)
- Better Windows integration
- Support for other platforms (macOS/Linux)

## 📄 License

MIT License - Feel free to use, modify, and distribute.

## 🙏 Credits

- [OpenAI Whisper](https://github.com/openai/whisper) - Speech recognition
- [Ollama](https://ollama.com/) - Local LLM inference
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) - GUI framework
- [python-sounddevice](https://python-sounddevice.readthedocs.io/) - Audio recording with WASAPI

---

**Made with ❤️ for private, offline productivity**
