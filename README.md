# YouTube Downloader & Stem Isolation

Complete audio processing suite with yt-dlp, audio-separator, and optional YuE AI cover generation.

## Features

- **YouTube Download**: Download single videos, playlists, or entire channels
- **Stem Isolation**: Separate beats into Drums, Bass, Other, and Vocals using audio-separator
- **AI Cover**: Generate AI music covers using isolated stems (YuE integration)
- **Melody Extraction**: Extract instrumental/melody for sampling

## Quick Start

### Local (Python 3.13+ required)

```bash
# Install dependencies
pip3 install -r requirements.txt

# Start server
python3 server.py
```

### Docker (Recommended - Zero Setup)

```bash
# Build and run with Docker Compose
docker-compose up --build
```

**Why Docker?**
- ✅ No Python installation needed
- ✅ All packages pre-installed (yt-dlp, ffmpeg, audio-separator)
- ✅ Works the same everywhere (Mac, Linux, Windows)
- ✅ Faster startup and deployment
- ✅ Isolated from system issues

## Folder Structure

```
downloads/
├── @ChannelName/
│   ├── Beat Name 1/
│   │   ├── Beat Name 1.mp3
│   │   └── isolated_samples/
│   │       ├── Beat Name 1_Vocals_htdemucs.mp3
│   │       ├── Beat Name 1_Drums_htdemucs.mp3
│   │       ├── Beat Name 1_Bass_htdemucs.mp3
│   │       └── Beat Name 1_Other_htdemucs.mp3
│   └── Beat Name 2/
│       └── ...
```

## Web Interface

- **Download Tab**: Choose Single Video, Playlist, or Entire Channel mode
- **Stem Isolation Tab**: Select channel, choose All Beats or Specific Beat
- **AI Cover Tab**: Select channel/beat/stems to generate covers

## CLI Tools

### Melody Extraction
Extract melody/instrumental from your beats for drumless sampling:

```bash
python3 extract_melody.py --help
```

## Requirements

- Python 3.13+
- yt-dlp
- audio-separator
- Flask & Flask-CORS
- ffmpeg (installed via audio-separator)

## Development

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run server
python3 server.py
```

---

Made with ❤️ by @geenaro
