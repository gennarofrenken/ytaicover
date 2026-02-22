# YouTube Downloader & Stem Isolation Server

A web application for downloading YouTube content, isolating instrumentals/stems using AI, and generating AI music covers using the kie.ai Suno API.

## 🌐 Live Deployment

**Deployed on Render**: https://yt-dlp-server-pnge.onrender.com

## Features

1. **YouTube Download** - Download single videos as MP3
2. **Stem Isolation** - Separate audio into 4 stems: Vocals, Drums, Bass, Other
3. **AI Cover Generation** - Generate AI music covers using kie.ai Suno API
4. **GitHub Storage** - All files stored in GitHub repository
5. **Download & Delete** - Download files to your computer, delete from GitHub

## Tech Stack

- **Backend**: Flask (Python)
- **Frontend**: Vanilla JavaScript + HTML/CSS
- **Storage**: GitHub Repository (all files stored online)
- **Audio Processing**: audio-separator with htdemucs model
- **AI Music**: kie.ai Suno API
- **Download**: yt-dlp with channel metadata extraction

## 📁 File Storage

All files are stored in GitHub: https://github.com/gennarofrenken/ytaicover/tree/main/storage/

**Structure**:
```
storage/
  └── @ChannelName/
      └── Beat Name/
          ├── Beat Name.mp3              # Original audio
          ├── isolated_samples/         # Stems from htdemucs
          │   ├── Beat Name_(Vocals).mp3
          │   ├── Beat Name_(Drums).mp3
          │   ├── Beat Name_(Bass).mp3
          │   └── Beat Name_(Other).mp3
          └── ai_covers/               # AI generated covers
              └── AI_Cover_genre_timestamp.mp3
```

## 🔧 Environment Variables

For Render deployment, set these environment variables:

```
GITHUB_TOKEN=your_github_token_here
GITHUB_REPO=gennarofrenken/ytaicover
KIE_API_KEY=ebc48e66ade959b00669f2313753d89d
PORT=8080
PUBLIC_BASE_URL=https://yt-dlp-server-pnge.onrender.com
```

## 📋 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve HTML interface |
| `/health` | GET | Health check for uptime monitoring |
| `/debug` | GET | Debug info (credentials check) |
| `/download` | POST | Start YouTube download (SSE stream) |
| `/isolate` | POST | Start stem isolation (SSE stream) |
| `/cover` | POST | Generate AI cover (SSE stream) |
| `/downloads` | GET | List all channels with beat counts |
| `/beats/<channel>` | GET | List beats for a channel |
| `/stems/<channel>/<beat>` | GET | List available stems for a beat |
| `/storage-info` | GET | Get storage usage information |
| `/delete` | POST | Delete files from GitHub and local |

## 🚀 Quick Start

1. **Open** https://yt-dlp-server-pnge.onrender.com
2. **Download**: Paste YouTube URL → Click "Start Download"
3. **Isolate Stems**: Select channel → Click "Isolate Stems" (takes 30-60s per beat)
4. **AI Cover**: Select channel/beat → Select stems → Enter genre → Click "Generate AI Cover"

## ⚠️ Limitations

- **File size limit**: 100MB per file (GitHub limit)
- **Repository limit**: 100GB total storage
- **API rate limits**: 5000 requests/hour on GitHub API
- **Processing time**: Stem isolation takes ~30-60s per beat, AI covers take 1-2 minutes

## 🔐 Security Notes

- Files stored in public GitHub repository are accessible to anyone with the URL
- Use the `/delete` endpoint to manage your storage
- GitHub token has full repo access - keep it secret

---

**Last Updated**: 2026-02-22
**Live URL**: https://yt-dlp-server-pnge.onrender.com
**GitHub**: https://github.com/gennarofrenken/ytaicover
