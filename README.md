# PawiScribe - Real-Time Meeting Notetaker

A real-time meeting notetaker for Windows that captures microphone + system audio, transcribes live with OpenAI Whisper on GPU, differentiates speakers using neural voice embeddings, and cleans up transcripts with Google Gemini AI.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![CUDA](https://img.shields.io/badge/CUDA-Supported-green.svg)

## Features

- **Real-Time Transcription** — Live speech-to-text as you speak, 5-second chunked processing
- **Dual Audio Capture** — Records microphone AND system audio simultaneously (Teams/Zoom/Meet)
- **GPU Accelerated** — Whisper runs on CUDA for fast transcription
- **Speaker Diarization** — Neural voice embeddings (resemblyzer) differentiate speakers automatically
- **AI Transcript Cleanup** — Google Gemini corrects speech recognition errors and generates meeting summaries
- **Periodic AI Cleanup** — Cleans transcript every ~10 minutes during long meetings, plus a final pass with meeting summary
- **Dual-Pane UI** — Side-by-side view of raw transcript and AI-cleaned version
- **Privacy-First** — Audio stays local; only text is sent to Gemini API (optional)
- **Markdown Export** — Save or copy meeting notes as clean Markdown

## Quick Start

### Prerequisites

- Windows 10 or 11
- Python 3.9+ ([Download](https://www.python.org/downloads/))
- NVIDIA GPU recommended (CUDA support for fast transcription)
- [FFmpeg](https://ffmpeg.org/) installed and on PATH
- (Optional) [Google Gemini API key](https://aistudio.google.com/apikey) for AI transcript cleanup

### Installation

```bash
git clone https://github.com/pawan0305/pawiscribe.git
cd pawiscribe
pip install -r requirements.txt
```

For GPU acceleration, install PyTorch with CUDA:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

> **Note:** First run will download the Whisper model (~150MB for the `base` model).

### FFmpeg Setup

PawiScribe requires FFmpeg. Install via winget:

```bash
winget install Gyan.FFmpeg
```

Or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to your PATH.

### Gemini API Key (Optional)

For AI-powered transcript cleanup:

1. Get a free API key from [Google AI Studio](https://aistudio.google.com/apikey)
2. Add it to `config.json`:
   ```json
   {
     "gemini_api_key": "YOUR_API_KEY_HERE"
   }
   ```
3. Enable the "AI Cleanup" checkbox in the app

### Run

```bash
python main.py
```

Or double-click `Start PawiScribe.bat`.

## System Audio Setup

To capture meeting audio (not just your microphone), enable **Stereo Mix** in Windows:

1. Right-click the speaker icon in system tray → **Sounds**
2. Go to the **Recording** tab
3. Right-click in the empty area → **Show Disabled Devices**
4. Right-click **Stereo Mix** → **Enable**
5. Click **OK**

### Alternatives

- **[VB-Cable](https://vb-audio.com/Cable/)** — Free virtual audio cable (if Stereo Mix isn't available)
- **[VoiceMeeter](https://vb-audio.com/Voicemeeter/banana.htm)** — Advanced audio routing

## Usage

1. **Start** the app with `python main.py`
2. Check **"Real-time Transcription"** for live transcription
3. Check **"AI Cleanup"** to enable Gemini-powered correction (requires API key)
4. Click **"Start Recording"** and join your meeting
5. Watch the **Raw Transcript** pane fill with live text
6. Every ~10 minutes, the **AI Cleaned** pane updates with corrected text
7. Click **"Stop"** — a final AI pass generates the cleaned transcript + meeting summary
8. **Copy** or **Save** the notes

## How It Works

### Transcription Pipeline

1. **Audio Capture** — Dual streams: microphone + system loopback (Stereo Mix)
2. **Chunking** — Audio is processed in 5-second chunks with 1-second overlap
3. **Whisper** — OpenAI Whisper (base model) runs on GPU for speech-to-text
4. **Speaker Detection** — Each speech segment gets a speaker label via resemblyzer neural embeddings
5. **Display** — Raw transcript appears in real-time in the left pane

### AI Cleanup

- **During recording** — Every ~10 minutes, Gemini corrects speech recognition errors (misheard words, broken sentences, wrong technical terms)
- **After recording** — Final pass with full context produces a polished transcript + meeting summary with key decisions, action items, and topics discussed

### Speaker Diarization

Uses [resemblyzer](https://github.com/resemble-ai/Resemblyzer) neural d-vector embeddings to differentiate speakers:

- Automatically detects new speakers vs. returning speakers
- Labels as `[Speaker 1]`, `[Speaker 2]`, etc.
- Works per-segment using Whisper's word timestamps
- Configurable similarity threshold (default: 0.69)

## Configuration

Edit `config.json`:

```json
{
  "whisper_model": "base",
  "language": "en",
  "sample_rate": 16000,
  "gemini_api_key": "",
  "auto_save": false,
  "output_directory": "./notes",
  "include_timestamps": true,
  "summary_max_length": 500
}
```

| Setting | Description | Default |
|---------|-------------|---------|
| `whisper_model` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large` | `base` |
| `language` | Language code for transcription | `en` |
| `gemini_api_key` | Google Gemini API key (leave empty to disable) | `""` |
| `auto_save` | Auto-save notes on stop | `false` |
| `output_directory` | Where to save exported notes | `./notes` |

## Troubleshooting

### "No loopback device found"
Enable Stereo Mix in Windows Sound settings (see [System Audio Setup](#system-audio-setup)).

### Slow transcription
- Use GPU: install PyTorch with CUDA (`pip install torch --index-url https://download.pytorch.org/whl/cu128`)
- Use a smaller model (`tiny` instead of `base`)
- Close other GPU-heavy apps

### Gemini API errors (429)
You're hitting rate limits. The app automatically handles this with periodic calls every ~10 minutes. If it persists, check your [quota](https://aistudio.google.com/apikey).

### No system audio captured
- Verify Stereo Mix is enabled and not muted
- Try VB-Cable as an alternative
- Some laptops don't expose Stereo Mix — check your audio driver

### DLL loading errors with torch
The app includes an automatic DLL directory workaround for Windows. If you still get errors, ensure your CUDA toolkit matches your PyTorch version.

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Windows 10 | Windows 11 |
| RAM | 4 GB | 8 GB+ |
| GPU | — | NVIDIA with CUDA |
| VRAM | — | 4 GB+ |
| Storage | 500 MB | 2 GB |
| Microphone | Any | USB headset |
| Internet | For Gemini API only | — |

## Tech Stack

- **[OpenAI Whisper](https://github.com/openai/whisper)** — Speech recognition
- **[PyTorch](https://pytorch.org/)** — GPU acceleration
- **[resemblyzer](https://github.com/resemble-ai/Resemblyzer)** — Speaker diarization via neural embeddings
- **[Google Gemini](https://ai.google.dev/)** — AI transcript cleanup
- **[PyQt6](https://www.riverbankcomputing.com/software/pyqt/)** — GUI framework
- **[sounddevice](https://python-sounddevice.readthedocs.io/)** — Audio recording

## Contributing

Contributions welcome! Some ideas:

- Support for macOS / Linux
- Custom speaker names (assign names to detected voices)
- Real-time speaker labels in the UI
- Support for additional AI providers
- Audio file import (transcribe pre-recorded meetings)
- Multi-language support

## License

MIT License — see [LICENSE](LICENSE) for details.

---

**Built for private, productive meetings.**
