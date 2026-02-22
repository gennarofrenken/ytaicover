# Deploy to Render + GitHub Storage

## Setup Instructions

### 1. Prepare GitHub Repository

1. Create a new GitHub repository (or use existing one)
2. The repository will store all MP3 files in a `storage/` directory
3. **Note**: GitHub has a 100MB file size limit and 100GB repository limit

### 2. Create GitHub Personal Access Token

1. Go to https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Give it a name like "Render yt-dlp"
4. Select scopes: `repo` (full control)
5. Generate and copy the token

### 3. Deploy on Render

1. Go to https://dashboard.render.com/
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Configure:
   - **Name**: yt-dlp-server
   - **Region**: Oregon (or closest to you)
   - **Branch**: main
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python server.py`

5. **Environment Variables** (add these in Render):
   ```
   GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxx
   GITHUB_REPO=yourusername/your-repo-name
   GITHUB_BRANCH=main
   KIE_API_KEY=ebc48e66ade959b00669f2313753d89d
   PORT=8080
   ```

6. Click "Create Web Service"

### 4. Wait for Deployment

- First deployment takes 5-10 minutes
- Render will install all dependencies
- After deployment, your app will be at: `https://yt-dlp-server.onrender.com`

### 5. Managing Storage

The app includes a delete endpoint to free up space:

```javascript
// Delete specific beat
POST /delete
{
  "channel": "channel_name",
  "beat": "beat_name",
  "type": "all",
  "deleteFromGithub": true
}

// Delete only stems
POST /delete
{
  "channel": "channel_name",
  "beat": "beat_name",
  "type": "stems",
  "deleteFromGithub": true
}

// Delete entire channel
POST /delete
{
  "channel": "channel_name",
  "type": "all",
  "deleteFromGithub": true
}
```

### Important Notes

1. **File Size Limit**: GitHub rejects files > 100MB
2. **Repository Limit**: 100GB total per repository
3. **Rate Limits**: GitHub API has rate limits (5000/hour authenticated)
4. **Git History**: Every file is stored in history - deleting doesn't immediately free space

### Storage Management Tips

- Check storage usage: `GET /storage-info`
- Delete old stems after downloading
- Consider creating a new repo when approaching limits
- Large beat packs may exceed 100MB per file

### Troubleshooting

**Files not uploading to GitHub:**
- Check GITHUB_TOKEN is valid
- Verify GITHUB_REPO format (username/repo)
- Check file size is under 100MB

** kie.ai API failing:**
- Ensure files are uploaded to GitHub first
- Check KIE_API_KEY is valid
- Files must be publicly accessible via raw.githubusercontent.com

**App crashing on Render:**
- Check Render logs
- Ensure all dependencies in requirements.txt
- PORT must be set to 8080
