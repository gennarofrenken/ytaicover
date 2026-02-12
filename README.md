# YouTube Downloader & Stem Isolation Server

A full-stack web application for downloading YouTube content, isolating instrumentals/stems using AI, and generating AI music covers using the YuE model.

## Project Overview

This application provides three main features through a web interface:
1. **YouTube Download** - Download single videos, playlists, or entire channels as MP3
2. **Stem Isolation** - Separate audio into 4 stems: Vocals, Drums, Bass, Sample
3. **AI Cover Generation** - Generate AI music covers using isolated stems as audio prompts

## Tech Stack

- **Backend**: Flask (Python)
- **Frontend**: Vanilla JavaScript + HTML/CSS
- **Audio Processing**: audio-separator with htdemucs model (4-stem separation)
- **AI Music**: YuE (note: has compatibility issues on Mac CPU, requires flash-attn)
- **Download**: yt-dlp with channel metadata extraction

## Installation & Setup

### Prerequisites

```bash
# Install Python dependencies
pip install flask flask-cors yt-dlp audio-separator torch torchvision torchaudio

# Clone YuE AI model (in project directory)
cd "/Users/macbook/Desktop/claudecode projects/yt-dlp"
git clone https://github.com/multimodal-art-projection/YuE.git
cd YuE/inference/
git clone https://huggingface.co/m-a-p/xcodec_mini_infer
```

### Running the Server

```bash
cd "/Users/macbook/Desktop/claudecode projects/yt-dlp"
python3 server.py
```

Then open http://localhost:8080 in your browser.

## Folder Structure

```
yt-dlp/
├── server.py                    # Flask server with all endpoints
├── youtube_downloader.html       # Single-page frontend with 3 tabs
├── downloads/                   # All downloaded content
│   └── @ChannelName/
│       └── Video Title/
│           ├── Video Title.mp3            # Original audio
│           ├── isolated_samples/           # Stems from htdemucs
│           │   ├── Video Title_(Vocals).mp3
│           │   ├── Video Title_(Drums).mp3
│           │   ├── Video Title_(Bass).mp3
│           │   └── Video Title_(Sample).mp3
│           └── ai_covers/               # YuE AI generated covers
│               └── yue_output_001.mp3
├── YuE/                         # AI music model (git clone)
│   └── inference/
│       ├── infer.py
│       └── xcodec_mini_infer/
└── README.md                    # This file
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve HTML interface |
| `/download` | POST | Start YouTube download (SSE stream) |
| `/isolate` | POST | Start stem isolation (SSE stream) |
| `/cover` | POST | Generate AI cover (SSE stream) |
| `/downloads` | GET | List all channels with beat counts |
| `/beats/<channel>` | GET | List beats for a channel |
| `/stems/<channel>/<beat>` | GET | List available stems for a beat |

## Features Detail

### 1. YouTube Download Tab
- **Modes**: Single Video, Playlist, Entire Channel
- **Output**: MP3 (best quality, 0 audio quality setting)
- **Organization**: Creates folder per video with channel name
- **Real-time progress**: SSE stream with download percentage

### 2. Stem Isolation Tab
- **Model**: htdemucs (4-stem model from audio-separator)
- **Stems**: Vocals, Drums, Bass, Sample (formerly "Other/Melody")
- **Process Time**: ~30-60 seconds per track
- **Output**: `isolated_samples/` folder with named stems
- **Modes**: Isolate all beats in channel or specific beat

### 3. AI Cover Tab
- **Model**: YuE with dual-track ICL mode
- **Input**: Select stems as audio prompts (Vocals, Drums, Bass, Sample)
- **Optional**: Genre/style prompt (e.g., "trap lo-fi jazz electronic")
- **Output**: `ai_covers/` folder with generated MP3s
- **Stem Selection**: Checkboxes that enable/disable based on available stems

## Important Technical Notes

### Stem Naming Convention
The system uses this naming for stems:
- `Video Title_(Vocals).mp3` - Vocal track
- `Video Title_(Drums).mp3` - Drum track
- `Video Title_(Bass).mp3` - Bass track
- `Video Title_(Sample).mp3` - Other/Melody (renamed to "Sample")

**Note**: The stem type is determined from the filename suffix by the `/stems/<channel>/<beat>` endpoint.

### Stem Type Mapping (server.py lines 199-205)
```python
stem_prefix_map = {
    '(Vocals)': 'Vocals',
    '(Instrumental)': 'Sample',
    '(Drums)': 'Drums',
    '(Other)': 'Sample',
    '(Bass)': 'Bass'
}
```

### AI Cover Checkbox Implementation
The AI Cover tab uses checkboxes with `data-stem` attributes that must match the stem types returned by the server:
- HTML: `<div class="stem-checkbox-item" data-stem="Sample">`
- Server returns: `{name: "...", type: "Sample", path: "..."}`
- JavaScript matches `data-stem` to `stem.type`

Key changes made:
1. Changed `data-stem="Other"` to `data-stem="Sample"`
2. Changed label from "Melody (Other)" to "Sample"
3. JavaScript sends full stem objects (with path) instead of just type strings
4. Added `availableStems` array to store stem data for later use

### Channel Name Extraction
Channel names are extracted using yt-dlp metadata:
1. First tries: `%(uploader)s` from video metadata
2. Fallback: `%(channel)s`
3. Special characters sanitized with regex
4. @ symbol preserved in folder names

### SSE (Server-Sent Events) Pattern
All long-running operations use SSE for real-time progress:
```python
progress_queue = queue.Queue()
thread = threading.Thread(target=worker_function, args=(..., progress_queue))
thread.daemon = True
thread.start()

def generate():
    while True:
        try:
            msg = progress_queue.get(timeout=1)
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get('complete'):
                break
        except queue.Empty:
            yield ": keepalive\n\n"
```

## Recent Changes & Fixes (2026-02-11)

### 1. Folder Structure Fixes (Multiple iterations)
**Problem**: Files going into `downloads/unknown_channel/downloads/`
**Solution**:
- Fixed channel name extraction from video metadata
- Changed yt-dlp output template to proper structure
- Now correctly creates: `downloads/@ChannelName/Video Title/Video Title.mp3`

### 2. Stem Renaming: "Other" → "Sample"
**Problem**: User wanted "Sample" instead of "Other/Melody"
**Solution**:
- Renamed `(Other)` stem to `(Sample)` in server.py
- Updated HTML checkbox from `data-stem="Other"` to `data-stem="Sample"`
- Changed label from "Melody (Other)" to "Sample"

### 3. AI Cover Stem Selection Bug
**Problem**: Checkboxes grayed out, "'str' object has no attribute 'get'" error
**Root Causes**:
1. HTML had `data-stem="Other"` but server returned `type: "Sample"`
2. JavaScript sent type strings (e.g., `['Drums']`) but server expected objects with `.get()` method
3. Checkboxes not matching available stem types

**Solutions Applied**:
- Fixed `data-stem` attributes to match server types (Vocals, Drums, Bass, Sample)
- Added `availableStems` array to store full stem objects
- Modified `loadCoverStems()` to store stems and match by type
- Changed `coverBtn` handler to send objects with `name`, `type`, `path` properties

### 4. loadSamples() Function
**Problem**: "loadSamples is not defined" JavaScript error
**Solution**: Added `loadSamples()` function that calls `loadCoverStems()` after stem isolation completes

### 5. Audio-Separator Output Directory
**Problem**: Stems going to beat folder root instead of isolated_samples
**Solution**: Changed `--output_dir` parameter to explicitly point to `iso_dir`

## File Locations & Key Code Sections

### server.py
| Lines | Description |
|-------|-------------|
| 40-76 | `get_channel_name()` - Extracts channel from URL or metadata |
| 79-141 | `run_ytdlp()` - Downloads YouTube content with progress |
| 153-228 | `run_stem_isolation()` - Isolates stems using audio-separator |
| 199-205 | Stem prefix mapping for renaming |
| 380-402 | `/stems/<channel>/<beat>` - Lists available stems with paths |
| 405-555 | `run_yue_cover()` - YuE AI cover generation |
| 558-587 | `/cover` POST endpoint - Starts AI cover generation |

### youtube_downloader.html
| Lines | Description |
|-------|-------------|
| 198-202 | Tab buttons (Download, Stem Isolation, AI Cover) |
| 321-336 | AI Cover stem checkboxes (with data-stem attributes) |
| 376-377 | Tab switching - loads channels/cover channels |
| 676-704 | `loadCoverStems()` - Loads and enables/disables checkboxes |
| 734-822 | `coverBtn` handler - Sends stems to backend |

## Quick Start Workflow

1. **Open** http://localhost:8080
2. **Download**: Paste YouTube URL → Select mode (Video/Playlist/Channel) → Click "Start Download"
3. **Isolate**: Switch to "Stem Isolation" tab → Select channel → Choose "All Beats" or "Specific Beat" → Click "Isolate Stems"
4. **AI Cover**: Switch to "AI Cover" tab → Select channel → Select beat → Check stems (Vocals/Drums/Bass/Sample) → (Optional) Enter genre → Click "Generate AI Cover"

## Known Issues & Limitations

1. **YuE Processing Time**: AI cover generation takes several minutes on CPU (1-5 minutes)
2. **Memory Usage**: audio-separator and YuE are resource-intensive
3. **GPU Support**: YuE defaults to CUDA idx 0, falls back to CPU if unavailable
4. **Stem Quality**: MP3 format used for compatibility (WAV was tested but reverted for stability)
5. **Download Mode**: Single video mode uses 'downloads' as placeholder initially, channel extracted after download

## Dependencies

```
flask
flask-cors
yt-dlp
audio-separator
torch
torchvision
torchaudio
```

Install all with: `pip install flask flask-cors yt-dlp audio-separator torch torchvision torchaudio`

## Coming Back to This Project

When returning to work on this project:
1. Run `python3 server.py` from project directory
2. Open http://localhost:8080
3. Check downloads folder for existing content
4. Stem isolation and AI Cover features are fully functional
5. YuE model must be cloned in `YuE/inference/` directory

## Architecture Notes

### Threading Pattern
All long-running operations use this pattern:
```python
progress_queue = queue.Queue()
thread = threading.Thread(target=worker_function, args=(..., progress_queue))
thread.daemon = True
thread.start()
```

### Error Handling
- Server: `try/except` blocks with `progress_queue.put({'error': ...})`
- Client: `try/catch` for fetch requests with user alerts

### Response Format
SSE messages use this format:
```json
{"status": "Processing...", "progress": 50}
{"complete": true, "message": "Done!"}
{"error": "Something went wrong", "complete": true}
```

---

**Last Updated**: 2026-02-11
**Server Port**: 8080
**Project Path**: `/Users/macbook/Desktop/claudecode projects/yt-dlp/`
**Python Version**: 3.x

Made with ❤️
