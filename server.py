#!/usr/bin/env python3
"""
YouTube Downloader & Stem Isolation Server
Folder Structure:
    downloads/
        @ChannelName/
            downloads/
                [Beat Name]/
                    [Beat Name].mp3
                    isolated_samples/
                        [Beat Name]_(Drums).mp3
                        [Beat Name]_(Bass).mp3
                        [Beat Name]_(Other).mp3
                        [Beat Name]_(Vocals).mp3
                    ai_covers/
                        [AI Generated Cover].mp3
"""

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import subprocess
import threading
import queue
import os
import sys
import re
import json
import shutil
import requests
import time
import tempfile
import github_storage

# Heavy imports - lazy load to speed up startup
librosa = None
np = None

def get_librosa():
    global librosa, np
    if librosa is None:
        import librosa
        import numpy as np
    return librosa, np

app = Flask(__name__)
CORS(app)

DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
PORT = int(os.environ.get('PORT', 8080))

# GitHub Storage Configuration
GITHUB_ENABLED = github_storage.USE_GITHUB
KIE_API_KEY = os.environ.get('KIE_API_KEY', '')
KIE_API_BASE = 'https://api.kie.ai/api/v1'
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Public URL for the deployed service
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', f'http://localhost:{PORT}')


def sanitize_filename(name):
    """Sanitize filename but preserve special unicode chars"""
    # Remove @ from channel names for display
    return name.replace('@', '').strip()


def get_channel_name(url):
    if '@' in url:
        match = re.search(r'@([^/?]+)', url)
        if match:
            return match.group(1)
    match = re.search(r'/(c/|channel/|user/)([^/?]+)', url)
    if match:
        return match.group(2).replace('/', '_')
    return 'unknown_channel'


def detect_bpm_and_key(audio_file):
    """Detect BPM and musical key from audio file"""
    # Try essentia first (more accurate), fallback to librosa
    try:
        import essentia.standard as es
        import essentia

        # Load audio for BPM/key detection
        loader = es.MonoLoader(filename=audio_file, sampleRate=22050)
        audio = loader()

        # BPM Detection
        rhythm_extractor = es.RhythmExtractor()
        bpm1, beats, bpm_values, rubato_start = rhythm_extractor(audio)

        try:
            percival = es.PercivalExtractor()
            bpm2 = percival(audio)
        except:
            bpm2 = bpm1

        bpm = float(bpm2 if bpm2 > 60 else bpm1)

        # Octave correction
        if bpm > 170:
            bpm = bpm / 2
        elif bpm < 55:
            bpm = bpm * 2

        bpm = round(bpm, 1)

        # Key Detection
        key_detector = es.KeyExtractor()
        key, scale, strength = key_detector(audio)
        scale_short = "maj" if scale == "major" else "min"
        key_str = f"{key}{scale_short}"

        return bpm, key_str

    except Exception as e:
        # Fallback to librosa
        try:
            librosa, np = get_librosa()
            y, sr = librosa.load(audio_file, sr=22050)

            # BPM detection
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr, tightness=100)
            bpm = float(tempo[0]) if hasattr(tempo, '__iter__') else float(tempo)

            if bpm > 170:
                bpm = bpm / 2
            elif bpm < 55:
                bpm = bpm * 2

            bpm = round(bpm, 1)

            # Key detection using chroma
            chroma_cq = librosa.feature.chroma_cqt(y=y, sr=sr)
            chroma_mean = np.mean(chroma_cq, axis=1)

            major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
            minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

            major_profile /= major_profile.sum()
            minor_profile /= minor_profile.sum()

            major_scores = []
            minor_scores = []

            key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

            for i in range(12):
                major_rotated = np.roll(major_profile, -i)
                minor_rotated = np.roll(minor_profile, -i)
                major_scores.append(np.dot(chroma_mean, major_rotated))
                minor_scores.append(np.dot(chroma_mean, minor_rotated))

            major_scores = np.array(major_scores)
            minor_scores = np.array(minor_scores)

            best_major = np.argmax(major_scores)
            best_minor = np.argmax(minor_scores)

            if major_scores[best_major] > minor_scores[best_minor]:
                key_str = f"{key_names[best_major]}maj"
            else:
                key_str = f"{key_names[best_minor]}min"

            return bpm, key_str

        except Exception as e2:
            print(f"BPM/Key detection failed: {e2}")
            return None, None


def run_ytdlp(url, channel_dir, to_mp3, progress_queue, mode='channel'):
    try:
        cmd = ['yt-dlp', '--no-warnings', '--ignore-errors', '--progress']

        if to_mp3:
            cmd.extend(['-x', '--audio-format', 'mp3', '--audio-quality', '0'])
        else:
            cmd.extend(['-f', 'bestvideo+bestaudio/best', '--merge-output-format', 'mp4'])

        # Handle different download modes
        mode_label = 'Channel'
        if mode == 'video':
            # Single video - add --no-playlist to only download one video
            cmd.insert(1, '--no-playlist')
            mode_label = 'Single Video'
        elif mode == 'playlist':
            # Playlist - download entire playlist but not channel
            mode_label = 'Playlist'
        else:  # channel
            mode_label = 'Entire Channel'

        # Download to temporary location first
        temp_dir = os.path.join(channel_dir, '.temp_download')
        os.makedirs(temp_dir, exist_ok=True)
        cmd.extend(['-o', os.path.join(temp_dir, '%(title)s.%(ext)s'), url])

        progress_queue.put({'status': f'Starting {mode_label.lower()} download...'})

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, bufsize=1)

        beat_names = []

        for line in process.stdout:
            line = line.strip()
            if '[download]' in line and '%' in line:
                match = re.search(r'(\d+\.?\d*)%', line)
                if match:
                    progress_queue.put({'progress': float(match.group(1))})
                if 'Destination:' in line:
                    filename = line.split('Destination:')[-1].strip()
                    beat_name = os.path.basename(filename).replace('.mp3', '').replace('.mp4', '')
                    progress_queue.put({'download': beat_name})
                    if beat_name not in beat_names:
                        beat_names.append(beat_name)
            if '[download] 100%' in line:
                progress_queue.put({'progress': 100})

        process.wait()

        # After download, organize files into proper beat folder structure
        # Expected: downloads/@ChannelName/BeatName/BeatName.mp3/isolated_samples/
        progress_queue.put({'status': 'Organizing downloaded files...'})

        organized_count = 0
        for filename in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, filename)
            if os.path.isfile(file_path) and (filename.endswith('.mp3') or filename.endswith('.mp4')):
                # Extract beat name (remove extension)
                beat_name = os.path.splitext(filename)[0]
                beat_folder = os.path.join(channel_dir, beat_name)

                # Create beat folder and move file into it
                os.makedirs(beat_folder, exist_ok=True)

                # Move file to beat folder with same name
                target_path = os.path.join(beat_folder, filename)
                if not os.path.exists(target_path):
                    shutil.move(file_path, target_path)

                # Create isolated_samples subfolder
                iso_dir = os.path.join(beat_folder, 'isolated_samples')
                os.makedirs(iso_dir, exist_ok=True)

                # Upload to GitHub if enabled
                if GITHUB_ENABLED:
                    repo_path = f'{channel_name}/{beat_name}/{filename}'
                    progress_queue.put({'status': f'Uploading to GitHub: {filename}...'})
                    public_url = github_storage.upload_to_github(target_path, repo_path)
                    if public_url:
                        progress_queue.put({'status': f'✓ Uploaded to GitHub: {filename}'})
                    else:
                        progress_queue.put({'error': f'Failed to upload {filename} to GitHub. Check environment variables.'})
                else:
                    progress_queue.put({'status': f'Note: GitHub storage not enabled. Files stored locally only.'})

                organized_count += 1

        # Remove the temp download folder
        try:
            shutil.rmtree(temp_dir)
        except:
            pass  # Folder might not exist or have other files

        if process.returncode == 0:
            count = organized_count if organized_count > 0 else len(beat_names)
            msg = f'{count} video{"s" if count != 1 else ""} downloaded!' if count > 0 else 'Download complete!'
            progress_queue.put({'complete': True, 'message': msg, 'count': count})
        else:
            progress_queue.put({'complete': True, 'message': 'Download finished with warnings.'})

    except Exception as e:
        progress_queue.put({'error': str(e), 'complete': True})


def scan_for_mp3s(folder_path):
    mp3_files = []
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith('.mp3'):
                mp3_files.append(os.path.join(root, file))
    return mp3_files


def run_stem_isolation(channel, progress_queue, beat=None):
    try:
        channel_dir = os.path.join(DOWNLOADS_DIR, channel)

        # For GitHub: Download file if not present locally
        if GITHUB_ENABLED:
            progress_queue.put({'status': 'Checking cloud storage...'})

        # Migrate any old files from downloads subfolder to proper structure
        old_downloads_dir = os.path.join(channel_dir, 'downloads')
        if os.path.exists(old_downloads_dir):
            progress_queue.put({'status': 'Migrating old files to new structure...'})
            for filename in os.listdir(old_downloads_dir):
                file_path = os.path.join(old_downloads_dir, filename)
                if os.path.isfile(file_path) and (filename.endswith('.mp3') or filename.endswith('.mp4')):
                    beat_name = os.path.splitext(filename)[0]
                    beat_folder = os.path.join(channel_dir, beat_name)
                    os.makedirs(beat_folder, exist_ok=True)
                    target_path = os.path.join(beat_folder, filename)
                    if not os.path.exists(target_path):
                        shutil.move(file_path, target_path)
                    iso_dir = os.path.join(beat_folder, 'isolated_samples')
                    os.makedirs(iso_dir, exist_ok=True)
            # Remove now-empty downloads folder
            try:
                os.rmdir(old_downloads_dir)
            except:
                pass

        # If GitHub is enabled and local directory doesn't exist or is empty, list files from GitHub first
        mp3_files = []
        if GITHUB_ENABLED:
            # Check if we need to download from GitHub
            local_has_files = os.path.exists(channel_dir) and any(
                os.path.isdir(os.path.join(channel_dir, item))
                for item in os.listdir(channel_dir) if item != 'downloads'
            )

            if not local_has_files:
                progress_queue.put({'status': 'No local files found, checking GitHub...'})
                # List all beat files from GitHub for this channel
                all_files = github_storage.list_github_files(channel)

                # Group by beat folder
                beats = {}
                for file_info in all_files:
                    parts = file_info['path'].split('/')
                    if len(parts) >= 3:
                        beat = parts[1]
                        filename = parts[2]
                        # Only get original MP3s (not isolated samples or covers)
                        if filename.endswith('.mp3') and 'isolated_samples' not in file_info['path'] and 'ai_covers' not in file_info['path']:
                            if beat not in beats:
                                beats[beat] = filename
                            # If specific beat requested, only include that one
                            if beat is None or beat == beat:
                                # Download the file
                                repo_path = f'{channel}/{beat}/{filename}'
                                local_path = os.path.join(channel_dir, beat, filename)
                                os.makedirs(os.path.dirname(local_path), exist_ok=True)

                                progress_queue.put({'status': f'Downloading {beat} from GitHub...'})
                                if github_storage.download_from_github(repo_path, local_path):
                                    progress_queue.put({'status': f'Downloaded: {beat}'})
                                    mp3_files.append((beat, local_path))

        # Also scan local filesystem for any additional files
        if os.path.exists(channel_dir):
            for item in os.listdir(channel_dir):
                # Skip 'downloads' subfolder - it's a temporary location
                if item == 'downloads':
                    continue
                beat_folder = os.path.join(channel_dir, item)
                if os.path.isdir(beat_folder):
                    # Look for MP3 with same name as folder
                    mp3_path = os.path.join(beat_folder, item + '.mp3')

                    # If GitHub enabled and file doesn't exist locally, try to download it
                    if GITHUB_ENABLED and not os.path.exists(mp3_path):
                        repo_path = f'{channel}/{item}/{item}.mp3'
                        if github_storage.file_exists_in_github(repo_path):
                            progress_queue.put({'status': f'Downloading {item} from GitHub...'})
                            if github_storage.download_from_github(repo_path, mp3_path):
                                progress_queue.put({'status': f'Downloaded: {item}'})

                    if os.path.exists(mp3_path):
                        # If specific beat requested, only include that one (avoid duplicates)
                        if beat is None or item == beat:
                            if not any(item == b for b, _ in mp3_files):
                                mp3_files.append((item, mp3_path))

        if not mp3_files:
            progress_queue.put({'error': 'No MP3 files found', 'complete': True})
            return

        model = 'htdemucs.yaml'
        total = len(mp3_files)
        
        for i, (beat_name, mp3_file) in enumerate(mp3_files, 1):
            progress_queue.put({'status': f'[{i}/{total}] Analyzing {beat_name}...'})

            # Detect BPM and key from original audio
            progress_queue.put({'status': f'Detecting BPM and key...'})
            bpm, key = detect_bpm_and_key(mp3_file)
            bpm_key_tag = f"{bpm}BPM_{key}" if bpm and key else ""

            # Create isolated_samples folder in beat folder
            beat_folder = os.path.join(channel_dir, beat_name)
            iso_dir = os.path.join(beat_folder, 'isolated_samples')
            os.makedirs(iso_dir, exist_ok=True)

            if bpm_key_tag:
                progress_queue.put({'status': f'Detected: {bpm} BPM, Key: {key}'})

            cmd = [
                'audio-separator',
                mp3_file,
                '-m', model,
                '--output_dir', iso_dir,
                '--output_format', 'mp3',
            ]

            progress_queue.put({'status': f'Starting AI stem isolation (~30-60s per beat)...'})

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            # Check for errors in stderr even if returncode is 0
            if result.stderr and ('ERROR' in result.stderr or 'Failed' in result.stderr):
                progress_queue.put({'error': f"audio-separator error: {result.stderr[-500:]}"})
                continue

            # Check if stem files were actually created
            stem_files = [f for f in os.listdir(iso_dir) if f.endswith('.mp3')] if os.path.exists(iso_dir) else []

            if not stem_files:
                error_msg = result.stderr[-500:] if result.stderr else "No output files created. Check audio-separator installation."
                progress_queue.put({'error': f"No stem files created for {beat_name}. Error: {error_msg}"})
                continue

            if result.returncode == 0 and stem_files:
                # Rename stems to desired format: StemType_[Beat Name]_XXXBPM_Xmaj_htdemucs.mp3
                stem_prefix_map = {
                    '(Vocals)': 'Vocals',
                    '(Instrumental)': 'Other',
                    '(Drums)': 'Drums',
                    '(Other)': 'Other',
                    '(Bass)': 'Bass'
                }
                for f in stem_files:
                    new_name = f
                    # Find stem type from audio-separator output
                    for old, prefix in stem_prefix_map.items():
                        if old in f:
                            # Construct new name with BPM and key if available
                            if bpm_key_tag:
                                new_name = f'{prefix}_{beat_name}_{bpm_key_tag}.mp3'
                            else:
                                new_name = f'{prefix}_{beat_name}.mp3'
                            break
                    if new_name != f:
                        src = os.path.join(iso_dir, f)
                        dst = os.path.join(iso_dir, new_name)
                        os.rename(src, dst)
                        progress_queue.put({'status': f'Created: {new_name}'})

                        # Upload stem to GitHub if enabled
                        if GITHUB_ENABLED:
                            repo_path = f'{channel}/{beat_name}/isolated_samples/{new_name}'
                            progress_queue.put({'status': f'Uploading {new_name} to GitHub...'})
                            upload_url = github_storage.upload_to_github(dst, repo_path)
                            if upload_url:
                                progress_queue.put({'status': f'✓ Uploaded: {new_name}'})
                            else:
                                progress_queue.put({'error': f'Failed to upload {new_name} to GitHub'})

                progress_queue.put({'status': f'Completed: {beat_name}'})
            else:
                progress_queue.put({'error': f"Failed: {beat_name} - {result.stderr[-200:] if result.stderr else 'Unknown error'}"})

        progress_queue.put({'complete': True, 'message': f'Stem isolation complete! ({total}/{total} beats processed)'})

    except Exception as e:
        progress_queue.put({'error': str(e), 'complete': True})


@app.route('/')
def index():
    return send_from_directory(os.path.dirname(__file__), 'youtube_downloader.html')


@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url', '')
    to_mp3 = data.get('toMp3', True)
    mode = data.get('mode', 'channel')  # 'video', 'playlist', or 'channel'

    if not url:
        return jsonify({'error': 'No URL'}), 400

    channel_name = sanitize_filename(get_channel_name(url))
    channel_dir = os.path.join(DOWNLOADS_DIR, channel_name)
    os.makedirs(channel_dir, exist_ok=True)

    progress_queue = queue.Queue()
    thread = threading.Thread(target=run_ytdlp, args=(url, channel_dir, to_mp3, progress_queue, mode))
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

    return Response(generate(), mimetype='text/event-stream')


@app.route('/isolate', methods=['POST'])
def isolate():
    data = request.json
    folder = data.get('folder', '')
    beat = data.get('beat', None)  # Optional: specific beat

    if not folder:
        return jsonify({'error': 'No folder'}), 400

    progress_queue = queue.Queue()
    thread = threading.Thread(target=run_stem_isolation, args=(folder, progress_queue, beat))
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

    return Response(generate(), mimetype='text/event-stream')


@app.route('/downloads')
def list_downloads():
    """List all channels with beat counts - reads from GitHub when enabled"""
    folders = {}

    try:
        if GITHUB_ENABLED:
            # Read from GitHub storage
            all_files = github_storage.list_github_files('')

            # Filter to only get actual beat MP3 files (not test files, isolated samples, etc.)
            beat_files = [f for f in all_files if f['name'].endswith('.mp3')
                         and 'isolated_samples' not in f['path']
                         and 'ai_covers' not in f['path']]

            for file_info in beat_files:
                # Path format: channel/beat/beat.mp3
                parts = file_info['path'].split('/')
                if len(parts) >= 3:
                    channel = parts[0]
                    beat = parts[1]  # beat folder name

                    if channel not in folders:
                        folders[channel] = {'name': channel, 'count': 0, 'hasIsolated': False, '_beats': set()}

                    # Count unique beats
                    folders[channel]['_beats'].add(beat)

                    # Check if has isolated samples
                    if 'isolated_samples' in f['path'] for f in all_files:
                        folders[channel]['hasIsolated'] = True

            # Build result
            result = []
            for channel, data in folders.items():
                result.append({
                    'name': data['name'],
                    'count': len(data['_beats']),
                    'hasIsolated': data['hasIsolated']
                })
            return jsonify(result)

        else:
            # Local filesystem fallback
            for item in os.listdir(DOWNLOADS_DIR):
                item_path = os.path.join(DOWNLOADS_DIR, item)
                if os.path.isdir(item_path):
                    beat_count = 0
                    has_isolated = False
                    for beat_folder in os.listdir(item_path):
                        if beat_folder == 'downloads':
                            continue
                        beat_path = os.path.join(item_path, beat_folder)
                        if os.path.isdir(beat_path):
                            mp3_file = os.path.join(beat_path, beat_folder + '.mp3')
                            if os.path.exists(mp3_file):
                                beat_count += 1
                                iso_dir = os.path.join(beat_path, 'isolated_samples')
                                if os.path.exists(iso_dir) and os.listdir(iso_dir):
                                    has_isolated = True
                    folders[item] = {'name': item, 'count': beat_count, 'hasIsolated': has_isolated}

            return jsonify(list(folders.values()))

    except Exception as e:
        print(f"Error listing downloads: {e}")
        return jsonify([])


@app.route('/beats/<channel>')
def list_beats(channel):
    """List beats for a channel - reads from GitHub when enabled"""
    beats = {}

    try:
        if GITHUB_ENABLED:
            # Read from GitHub storage
            all_files = github_storage.list_github_files(channel)

            for file_info in all_files:
                # Path format: channel/beat/file.mp3 or channel/beat/isolated_samples/file.mp3
                parts = file_info['path'].split('/')
                if len(parts) >= 2:
                    beat = parts[1]

                    if beat and beat not in beats:
                        beats[beat] = {'name': beat, 'hasIsolated': False}

                    # Check if has isolated samples
                    if len(parts) > 2 and 'isolated_samples' in file_info['path']:
                        beats[beat]['hasIsolated'] = True

            return jsonify(list(beats.values()))

        else:
            # Local filesystem fallback
            channel_dir = os.path.join(DOWNLOADS_DIR, channel)
            if os.path.exists(channel_dir):
                for item in os.listdir(channel_dir):
                    if item == 'downloads':
                        continue
                    beat_folder = os.path.join(channel_dir, item)
                    if os.path.isdir(beat_folder):
                        mp3_path = os.path.join(beat_folder, item + '.mp3')
                        if os.path.exists(mp3_path):
                            iso_dir = os.path.join(beat_folder, 'isolated_samples')
                            has_isolated = os.path.exists(iso_dir) and os.listdir(iso_dir)
                            beats[item] = {'name': item, 'hasIsolated': has_isolated}

            return jsonify(list(beats.values()))

    except Exception as e:
        print(f"Error listing beats for {channel}: {e}")
        return jsonify([])


@app.route('/samples')
def list_samples():
    """List all samples grouped by channel - reads from GitHub when enabled"""
    samples_by_channel = {}

    try:
        if GITHUB_ENABLED:
            # Read from GitHub storage
            all_files = github_storage.list_github_files('')

            for file_info in all_files:
                path_parts = file_info['path'].split('/')

                # Only include files in isolated_samples folders
                if len(path_parts) >= 4 and path_parts[2] == 'isolated_samples' and file_info['name'].endswith('.mp3'):
                    channel = path_parts[0]
                    beat = path_parts[1]
                    filename = file_info['name']

                    if channel not in samples_by_channel:
                        samples_by_channel[channel] = {'name': channel, 'stems': [], 'count': 0}

                    samples_by_channel[channel]['stems'].append({
                        'name': filename,
                        'beat': beat,
                        'url': file_info['url']
                    })
                    samples_by_channel[channel]['count'] += 1

            return jsonify(list(samples_by_channel.values()))

        else:
            # Local filesystem fallback
            for item in os.listdir(DOWNLOADS_DIR):
                item_path = os.path.join(DOWNLOADS_DIR, item)
                if os.path.isdir(item_path):
                    stems = []
                    for beat_folder in os.listdir(item_path):
                        if beat_folder == 'downloads':
                            continue
                        beat_path = os.path.join(item_path, beat_folder)
                        if os.path.isdir(beat_path):
                            iso_dir = os.path.join(beat_path, 'isolated_samples')
                            if os.path.exists(iso_dir):
                                for f in os.listdir(iso_dir):
                                    if f.endswith('.mp3'):
                                        stems.append({'name': f, 'beat': beat_folder})
                    if stems:
                        samples_by_channel[item] = {'name': item, 'stems': stems, 'count': len(stems)}

            return jsonify(list(samples_by_channel.values()))

    except Exception as e:
        print(f"Error listing samples: {e}")
        return jsonify([])


@app.route('/stems/<channel>/<beat>')
def list_stems(channel, beat):
    """List stems for a beat - reads from GitHub when enabled"""
    stems = {}

    try:
        if GITHUB_ENABLED:
            # Read from GitHub storage
            all_files = github_storage.list_github_files(f'{channel}/{beat}/isolated_samples')

            for file_info in all_files:
                filename = file_info['name']
                if filename.endswith('.mp3'):
                    # Extract stem type from filename
                    stem_type = 'Unknown'
                    if filename.startswith('Vocals_'): stem_type = 'Vocals'
                    elif filename.startswith('Drums_'): stem_type = 'Drums'
                    elif filename.startswith('Bass_'): stem_type = 'Bass'
                    elif filename.startswith('Other_'): stem_type = 'Other'

                    stems[filename] = {
                        'name': filename,
                        'type': stem_type,
                        'url': file_info['url'],  # GitHub raw URL
                        'path': file_info['path']  # GitHub path for reference
                    }

            return jsonify(list(stems.values()))

        else:
            # Local filesystem fallback
            beat_path = os.path.join(DOWNLOADS_DIR, channel, beat)
            iso_dir = os.path.join(beat_path, 'isolated_samples')
            if os.path.exists(iso_dir):
                for f in os.listdir(iso_dir):
                    if f.endswith('.mp3'):
                        stem_type = 'Unknown'
                        if f.startswith('Vocals_'): stem_type = 'Vocals'
                        elif f.startswith('Drums_'): stem_type = 'Drums'
                        elif f.startswith('Bass_'): stem_type = 'Bass'
                        elif f.startswith('Other_'): stem_type = 'Other'
                        stems[f] = {
                            'name': f,
                            'type': stem_type,
                            'path': os.path.join(iso_dir, f)
                        }

            return jsonify(list(stems.values()))

    except Exception as e:
        print(f"Error listing stems for {channel}/{beat}: {e}")
        return jsonify([])


# Note: PUBLIC_BASE_URL is already defined above (line 49)
# Keeping this comment for reference - no redeclaration needed


def upload_file_to_temp_host(file_path, progress_queue):
    """Get public URL for a file - uses GitHub raw URL if GitHub is enabled"""
    try:
        # If GitHub storage is enabled, the file should already be uploaded
        # Get the GitHub raw URL directly
        if GITHUB_ENABLED:
            downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
            rel_path = os.path.relpath(file_path, downloads_dir)

            # Check if file exists in GitHub
            if github_storage.file_exists_in_github(rel_path):
                github_url = f'https://raw.githubusercontent.com/{github_storage.GITHUB_REPO}/{github_storage.GITHUB_BRANCH}/storage/{rel_path}'
                progress_queue.put({'status': f'Using GitHub URL for file'})
                return github_url
            else:
                # Try to upload to GitHub first
                progress_queue.put({'status': f'Uploading to GitHub for kie.ai...'})
                public_url = github_storage.upload_to_github(file_path, rel_path)
                if public_url:
                    return public_url
                else:
                    progress_queue.put({'error': 'Failed to upload to GitHub. File may be too large (>100MB).'})
                    return None

        # Fallback to local file serving (for non-GitHub setups)
        downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
        rel_path = os.path.relpath(file_path, downloads_dir)

        safe_path = rel_path.replace(' ', '%20')
        upload_url = f'{PUBLIC_BASE_URL}/serve-audio/{safe_path}'

        progress_queue.put({'status': f'Using local file (server must be publicly accessible)'})

        # Check if this is a localhost URL - warn the user
        if 'localhost' in PUBLIC_BASE_URL or '127.0.0.1' in PUBLIC_BASE_URL:
            progress_queue.put({'error': 'WARNING: Your server is running locally. kie.ai needs a public URL to access your files.'})
            progress_queue.put({'error': 'Please install ngrok (brew install ngrok) and run: ngrok http 8080'})
            progress_queue.put({'error': 'Then set PUBLIC_BASE_URL environment variable to the ngrok URL'})
            progress_queue.put({'error': 'Example: export PUBLIC_BASE_URL=https://abc123.ngrok.io'})
            return None

        return upload_url

    except Exception as e:
        progress_queue.put({'error': f"File path error: {str(e)}"})
        return None


def run_kie_cover(channel, beat, selected_stems, genre, progress_queue):
    """Generate AI cover using kie.ai Suno API with the selected stems"""
    try:
        # Get stem file paths
        beat_folder = os.path.join(DOWNLOADS_DIR, channel, beat)
        iso_dir = os.path.join(beat_folder, 'isolated_samples')
        os.makedirs(iso_dir, exist_ok=True)

        # Create output directory for AI covers
        output_dir = os.path.join(beat_folder, 'ai_covers')
        os.makedirs(output_dir, exist_ok=True)

        # If GitHub enabled and no stems locally, download from GitHub
        if GITHUB_ENABLED:
            local_stems = [f for f in os.listdir(iso_dir) if f.endswith('.mp3')] if os.path.exists(iso_dir) else []
            if not local_stems:
                progress_queue.put({'status': 'Downloading stems from GitHub...'})
                all_files = github_storage.list_github_files(f'{channel}/{beat}/isolated_samples')
                for file_info in all_files:
                    if file_info['name'].endswith('.mp3'):
                        local_path = os.path.join(iso_dir, file_info['name'])
                        if not os.path.exists(local_path):
                            progress_queue.put({'status': f'Downloading {file_info["name"]}...'})
                            github_storage.download_from_github(file_info['path'], local_path)
                progress_queue.put({'status': 'Stems downloaded from GitHub'})

        # Map stem types to filename prefixes
        stem_type_to_prefix = {
            'Vocals': 'Vocals',
            'Sample': 'Other',
            'Drums': 'Drums',
            'Bass': 'Bass',
            'Other': 'Other'
        }

        # Get all available stems
        available_stems = []
        if os.path.exists(iso_dir):
            for f in os.listdir(iso_dir):
                if f.endswith('.mp3'):
                    for prefix_name, prefix in [('Vocals', 'Vocals_'), ('Drums', 'Drums_'),
                                               ('Bass', 'Bass_'), ('Other', 'Other_')]:
                        if f.startswith(prefix):
                            available_stems.append({
                                'type': prefix_name,
                                'path': os.path.join(iso_dir, f),
                                'name': f
                            })
                            break

        if not available_stems:
            progress_queue.put({'error': 'No stem files found. Please isolate stems first.'})
            progress_queue.put({'complete': True})
            return

        # Select the first available stem for upload
        # Prioritize Vocals, then Drums, then Bass, then Other
        stem_priority = ['Vocals', 'Drums', 'Bass', 'Other']
        selected_stem = None
        for priority_type in stem_priority:
            for stem in available_stems:
                if stem['type'] == priority_type:
                    selected_stem = stem
                    break
            if selected_stem:
                break

        if not selected_stem:
            selected_stem = available_stems[0]

        progress_queue.put({'status': f'Using stem: {selected_stem["name"]}'})

        # Upload the stem file to temporary host
        upload_url = upload_file_to_temp_host(selected_stem['path'], progress_queue)
        if not upload_url:
            progress_queue.put({'error': 'Failed to upload audio file. Please try again.'})
            progress_queue.put({'complete': True})
            return

        progress_queue.put({'status': f'File uploaded: {upload_url}'})

        # Prepare the API request
        headers = {
            'Authorization': f'Bearer {KIE_API_KEY}',
            'Content-Type': 'application/json'
        }

        # Determine if instrumental based on selected stems
        has_vocals = any(
            (s.get('type') == 'Vocals' if isinstance(s, dict) else s == 'Vocals')
            for s in selected_stems
        )
        instrumental = not has_vocals

        # Build the prompt from genre or use default
        prompt = genre if genre else 'A creative cover in a new style'

        # Prepare request data for Non-custom Mode (simplest)
        data = {
            'uploadUrl': upload_url,
            'prompt': prompt,
            'customMode': False,  # Simple mode - only prompt required
            'instrumental': instrumental,
            'model': 'V4_5',  # Use V4.5 for better quality
            'callBackUrl': f'{PUBLIC_BASE_URL}/kie-callback'  # Use public URL
        }

        progress_queue.put({'status': 'Sending request to kie.ai Suno API...'})

        # Make the API request
        response = requests.post(
            f'{KIE_API_BASE}/generate/upload-cover',
            headers=headers,
            json=data,
            timeout=30
        )

        result = response.json()

        if response.status_code != 200 or result.get('code') != 200:
            error_msg = result.get('msg', 'Unknown error')
            progress_queue.put({'error': f'API Error: {error_msg}'})
            progress_queue.put({'complete': True})
            return

        task_id = result['data']['taskId']
        progress_queue.put({'status': f'Task created! ID: {task_id}. Waiting for generation...'})

        # Poll for task completion
        max_wait = 600  # 10 minutes max
        start_time = time.time()
        check_interval = 10  # Check every 10 seconds

        while time.time() - start_time < max_wait:
            # Check task status
            status_response = requests.get(
                f'{KIE_API_BASE}/generate/record-info?taskId={task_id}',
                headers={'Authorization': f'Bearer {KIE_API_KEY}'},
                timeout=10
            )

            status_result = status_response.json()

            if status_result.get('code') == 200:
                task_data = status_result.get('data', {})
                status = task_data.get('status')

                if status == 'SUCCESS':
                    # Get the generated audio URL
                    suno_data = task_data.get('response', {}).get('sunoData', [])
                    if suno_data:
                        audio_url = suno_data[0].get('audioUrl')
                        if audio_url:
                            progress_queue.put({'status': 'Downloading generated audio...'})

                            # Download the generated audio
                            download_response = requests.get(audio_url, timeout=60)
                            if download_response.status_code == 200:
                                # Save the file
                                genre_tag = genre.replace(' ', '_')[:30] if genre else 'cover'
                                timestamp = int(time.time())
                                output_filename = f'AI_Cover_{genre_tag}_{timestamp}.mp3'
                                output_path = os.path.join(output_dir, output_filename)

                                with open(output_path, 'wb') as f:
                                    f.write(download_response.content)

                                progress_queue.put({'status': f'Created: {output_filename}'})

                                # Upload to GitHub if enabled
                                if GITHUB_ENABLED:
                                    repo_path = f'{channel}/{beat}/ai_covers/{output_filename}'
                                    github_url = github_storage.upload_to_github(output_path, repo_path)
                                    if github_url:
                                        progress_queue.put({'status': f'Uploaded to GitHub: {output_filename}'})

                                progress_queue.put({'complete': True,
                                                  'message': f'AI Cover generated successfully!'})
                                return
                            else:
                                progress_queue.put({'error': 'Failed to download generated audio'})
                                progress_queue.put({'complete': True})
                                return

                elif status == 'PENDING':
                    progress_queue.put({'status': 'Generating... (this may take 1-2 minutes)'})
                elif status == 'FIRST_SUCCESS':
                    progress_queue.put({'status': 'First track complete...'})
                elif status in ['CREATE_TASK_FAILED', 'GENERATE_AUDIO_FAILED']:
                    error_msg = task_data.get('errorMessage', 'Generation failed')
                    progress_queue.put({'error': f'Generation failed: {error_msg}'})
                    progress_queue.put({'complete': True})
                    return
                elif status == 'SENSITIVE_WORD_ERROR':
                    progress_queue.put({'error': 'Content filtered due to sensitive words'})
                    progress_queue.put({'complete': True})
                    return

            time.sleep(check_interval)

        # Timeout
        progress_queue.put({'error': 'Generation timeout. The task may still be processing.'})
        progress_queue.put({'complete': True})

    except Exception as e:
        progress_queue.put({'error': f'AI Cover generation failed: {str(e)}'})
        progress_queue.put({'complete': True})


def run_yue_cover(channel, beat, selected_stems, genre, progress_queue):
    """Generate AI cover using YuE with the selected stems as prompts"""
    try:
        import importlib
        import torch

        # Check if YuE inference module is available
        yue_inference_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'YuEGP', 'inference')
        infer_module_path = os.path.join(yue_inference_path, 'infer.py')

        if not os.path.exists(infer_module_path):
            progress_queue.put({'error': 'YuE inference module not found. Please ensure YuEGP is properly installed.'})
            progress_queue.put({'complete': True})
            return

        # Check for required models
        xcodec_path = os.path.join(yue_inference_path, 'xcodec_mini_infer')
        if not os.path.exists(xcodec_path):
            progress_queue.put({'error': 'xcodec_mini_infer models not found. Download from: https://huggingface.co/m-a-p/xcodec_mini_infer'})
            progress_queue.put({'error': 'Run: cd YuEGP/inference && git clone https://huggingface.co/m-a-p/xcodec_mini_infer'})
            progress_queue.put({'complete': True})
            return

        # Get stem file paths
        beat_folder = os.path.join(DOWNLOADS_DIR, channel, beat)
        iso_dir = os.path.join(beat_folder, 'isolated_samples')

        # Create output directory for AI covers
        output_dir = os.path.join(beat_folder, 'ai_covers')
        os.makedirs(output_dir, exist_ok=True)

        # Map stem types to filename prefixes
        stem_type_to_prefix = {
            'Vocals': 'Vocals',
            'Sample': 'Other',  # Sample maps to Other stem
            'Drums': 'Drums',
            'Bass': 'Bass',
            'Other': 'Other'
        }

        # Find selected stem files
        vocal_path = None
        instrumental_path = None

        # Get all available stems in isolated_samples
        available_stems = []
        if os.path.exists(iso_dir):
            for f in os.listdir(iso_dir):
                if f.endswith('.mp3'):
                    # Determine stem type from filename
                    for prefix_name, prefix in [('Vocals', 'Vocals_'), ('Drums', 'Drums_'), ('Bass', 'Bass_'), ('Other', 'Other_')]:
                        if f.startswith(prefix):
                            available_stems.append({
                                'type': prefix_name,
                                'path': os.path.join(iso_dir, f),
                                'name': f
                            })
                            break

        # Process selected stems (can be strings or dict objects)
        for stem in selected_stems:
            # Handle both string and dict formats
            if isinstance(stem, str):
                stem_type = stem
            elif isinstance(stem, dict):
                stem_type = stem.get('type', stem.get('name', ''))
            else:
                continue

            # Map Sample to Other for file lookup
            lookup_type = stem_type_to_prefix.get(stem_type, stem_type)

            # Find matching stem file
            for avail in available_stems:
                if avail['type'] == lookup_type:
                    if stem_type in ['Vocals', 'Sample']:
                        vocal_path = vocal_path or avail['path']
                    elif stem_type in ['Drums', 'Bass', 'Other']:
                        instrumental_path = instrumental_path or avail['path']
                    break

        # Create temporary genre file
        genre_file = os.path.join(output_dir, 'genre.txt')
        with open(genre_file, 'w') as f:
            if genre:
                f.write(genre)
            else:
                f.write('pop, electronic, upbeat')

        # Create dummy lyrics file (required by YuE even in ICL mode)
        # Need at least 2 segments for generation to work (i=0 is skipped, i=1 generates)
        # Each segment must end with \n for split_lyrics regex to match
        lyrics_file = os.path.join(output_dir, 'lyrics.txt')
        with open(lyrics_file, 'w') as f:
            f.write('[Verse]\nGenerated from stem prompts\n\n[Chorus]\nAI music generation\n')

        progress_queue.put({'status': 'Initializing YuE AI model...'})

        # Prepare YuE command
        import subprocess

        cmd = [
            sys.executable,  # Use same Python interpreter
            infer_module_path,
            '--icl',  # Use ICL mode for audio prompts (doesn't require lyrics)
            '--use_dual_tracks_prompt',
            '--vocal_track_prompt_path', vocal_path or '',
            '--instrumental_track_prompt_path', instrumental_path or '',
            '--genre_txt', genre_file,
            '--lyrics_txt', lyrics_file,  # Add lyrics file
            '--output_dir', output_dir,
            '--run_n_segments', '2',
            '--max_new_tokens', '1000',
        ]

        # Check if CUDA is available, otherwise CPU
        if not torch.cuda.is_available():
            cmd.extend(['--cuda_idx', '-1'])  # Use CPU
            progress_queue.put({'status': 'Using CPU for inference (slower)...'})

        progress_queue.put({'status': 'Generating AI cover (this may take several minutes)...'})

        # Run YuE inference
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            cwd=yue_inference_path
        )

        # Monitor output for progress
        for line in process.stdout:
            line = line.strip()
            if line:
                progress_queue.put({'status': line[:200]})  # Truncate long lines

        process.wait()

        # Find generated output file
        output_files = []
        for f in os.listdir(output_dir):
            if f.endswith('.mp3') and f != 'genre.txt':
                output_files.append(f)

        if output_files and process.returncode == 0:
            # Rename output to include genre info
            genre_tag = genre.replace(' ', '_')[:30] if genre else 'cover'
            timestamp = int(time.time())
            for output_file in output_files:
                old_path = os.path.join(output_dir, output_file)
                new_name = f'AI_Cover_{genre_tag}_{timestamp}.mp3'
                new_path = os.path.join(output_dir, new_name)
                os.rename(old_path, new_path)
                progress_queue.put({'status': f'Created: {new_name}'})

            progress_queue.put({'complete': True, 'message': f'AI Cover generated! ({len(output_files)} file(s))'})
        else:
            progress_queue.put({'error': 'YuE generation failed. Check console for details.'})
            progress_queue.put({'complete': True})

    except ImportError as e:
        progress_queue.put({'error': f'Missing dependency: {str(e)}'})
        progress_queue.put({'error': 'Install required packages: pip install torch torchaudio transformers'})
        progress_queue.put({'complete': True})
    except Exception as e:
        progress_queue.put({'error': f'AI Cover generation failed: {str(e)}'})
        progress_queue.put({'complete': True})


@app.route('/serve-audio/<path:filepath>')
def serve_audio(filepath):
    """Serve audio files for external access (needed for kie.ai API)"""
    # Decode URL-encoded path
    from urllib.parse import unquote
    filepath = unquote(filepath)

    # Security: ensure the path is within downloads directory
    safe_path = os.path.basename(filepath)
    for part in filepath.split('/'):
        if part and part != safe_path:
            safe_path = os.path.join(part, safe_path)

    full_path = os.path.join(DOWNLOADS_DIR, safe_path)

    if not os.path.exists(full_path):
        return jsonify({'error': 'File not found'}), 404

    return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))


@app.route('/storage-info', methods=['GET'])
def storage_info():
    """Get storage information including GitHub repo size"""
    info = {
        'github_enabled': GITHUB_ENABLED,
        'local_path': DOWNLOADS_DIR,
        'github_repo': github_storage.GITHUB_REPO if GITHUB_ENABLED else None,
        'github_branch': github_storage.GITHUB_BRANCH if GITHUB_ENABLED else None
    }

    if GITHUB_ENABLED:
        repo_size_kb = github_storage.get_repo_size()
        info['repo_size_mb'] = round(repo_size_kb / 1024, 2) if repo_size_kb else None

    # Calculate local storage size
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(DOWNLOADS_DIR):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total_size += os.path.getsize(fp)
    info['local_size_mb'] = round(total_size / (1024 * 1024), 2)

    return jsonify(info)


@app.route('/delete', methods=['POST'])
def delete_files():
    """Delete files from local storage and optionally from GitHub"""
    data = request.json
    channel = data.get('channel', '')
    beat = data.get('beat', None)        # Optional: specific beat
    file_type = data.get('type', 'all')  # 'all', 'original', 'stems', 'covers'
    delete_from_github = data.get('deleteFromGithub', True)

    if not channel:
        return jsonify({'error': 'Channel required'}), 400

    try:
        channel_dir = os.path.join(DOWNLOADS_DIR, channel)
        deleted_count = 0
        deleted_github_count = 0

        # Determine what to delete
        if beat:
            # Delete specific beat folder
            beat_dir = os.path.join(channel_dir, beat)
            if os.path.exists(beat_dir):
                # Delete from GitHub first if enabled
                if GITHUB_ENABLED and delete_from_github:
                    # Delete original file
                    github_storage.delete_from_github(f'{channel}/{beat}/{beat}.mp3')
                    deleted_github_count += 1

                    # Delete stems
                    stem_files = os.listdir(os.path.join(beat_dir, 'isolated_samples')) if os.path.exists(os.path.join(beat_dir, 'isolated_samples')) else []
                    for stem in stem_files:
                        if github_storage.delete_from_github(f'{channel}/{beat}/isolated_samples/{stem}'):
                            deleted_github_count += 1

                    # Delete AI covers
                    covers_dir = os.path.join(beat_dir, 'ai_covers')
                    if os.path.exists(covers_dir):
                        for cover in os.listdir(covers_dir):
                            if github_storage.delete_from_github(f'{channel}/{beat}/ai_covers/{cover}'):
                                deleted_github_count += 1

                # Delete local folder
                shutil.rmtree(beat_dir)
                deleted_count += 1
        else:
            # Delete entire channel or specific file types
            for item in os.listdir(channel_dir) if os.path.exists(channel_dir) else []:
                if item == 'downloads':
                    continue

                item_path = os.path.join(channel_dir, item)

                if file_type == 'all':
                    # Delete entire item
                    if os.path.isdir(item_path):
                        # Delete from GitHub first
                        if GITHUB_ENABLED and delete_from_github:
                            github_storage.delete_from_github(f'{channel}/{item}/{item}.mp3')
                            deleted_github_count += 1

                        shutil.rmtree(item_path)
                        deleted_count += 1
                else:
                    # Delete specific file types within beat folders
                    if os.path.isdir(item_path):
                        if file_type == 'stems':
                            iso_dir = os.path.join(item_path, 'isolated_samples')
                            if os.path.exists(iso_dir):
                                for stem in os.listdir(iso_dir):
                                    if GITHUB_ENABLED and delete_from_github:
                                        if github_storage.delete_from_github(f'{channel}/{item}/isolated_samples/{stem}'):
                                            deleted_github_count += 1
                                    os.remove(os.path.join(iso_dir, stem))
                                    deleted_count += 1
                        elif file_type == 'covers':
                            covers_dir = os.path.join(item_path, 'ai_covers')
                            if os.path.exists(covers_dir):
                                for cover in os.listdir(covers_dir):
                                    if GITHUB_ENABLED and delete_from_github:
                                        if github_storage.delete_from_github(f'{channel}/{item}/ai_covers/{cover}'):
                                            deleted_github_count += 1
                                    os.remove(os.path.join(covers_dir, cover))
                                    deleted_count += 1
                        elif file_type == 'original':
                            original_file = os.path.join(item_path, f'{item}.mp3')
                            if os.path.exists(original_file):
                                if GITHUB_ENABLED and delete_from_github:
                                    if github_storage.delete_from_github(f'{channel}/{item}/{item}.mp3'):
                                        deleted_github_count += 1
                                os.remove(original_file)
                                deleted_count += 1

        return jsonify({
            'success': True,
            'deleted_local': deleted_count,
            'deleted_github': deleted_github_count,
            'message': f'Deleted {deleted_count} local file(s) and {deleted_github_count} GitHub file(s)'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/cover', methods=['POST'])
def generate_cover():
    data = request.json
    channel = data.get('channel', '')
    beat = data.get('beat', '')
    selected_stems = data.get('stems', [])
    genre = data.get('genre', '')

    if not channel or not beat:
        return jsonify({'error': 'Channel and beat required'}), 400

    if not selected_stems:
        return jsonify({'error': 'Please select at least one stem'}), 400

    progress_queue = queue.Queue()
    thread = threading.Thread(target=run_kie_cover, args=(channel, beat, selected_stems, genre, progress_queue))
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

    return Response(generate(), mimetype='text/event-stream')


if __name__ == '__main__':
    # Validate required environment variables for production
    errors = []
    warnings = []

    # Check GitHub configuration
    if not github_storage.GITHUB_TOKEN:
        errors.append("GITHUB_TOKEN environment variable not set - files cannot be stored!")
    if not github_storage.GITHUB_REPO:
        errors.append("GITHUB_REPO environment variable not set - files cannot be stored!")

    # Check KIE.AI API key
    if not KIE_API_KEY:
        warnings.append("KIE_API_KEY not set - AI cover generation will not work!")

    # Check for production environment
    if os.environ.get('RENDER'):  # Render.com sets this
        if not os.environ.get('PUBLIC_BASE_URL'):
            errors.append("PUBLIC_BASE_URL not set - kie.ai callbacks will fail!")

    # Print errors and exit if critical
    if errors:
        print("╔═════════════════════════════════════════════════════════╗")
        print("║  CRITICAL ERRORS - Cannot start server:                  ║")
        print("╠═════════════════════════════════════════════════════════╣")
        for error in errors:
            print(f"║  ❌ {error:<55} ║")
        print("╚═════════════════════════════════════════════════════════╝")
        exit(1)

    # Check yt-dlp installation
    try:
        subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
    except:
        errors.append("yt-dlp not found. Install: pip install yt-dlp")
        print("╔═════════════════════════════════════════════════════════╗")
        print("║  CRITICAL ERRORS - Cannot start server:                  ║")
        print("╠═════════════════════════════════════════════════════════╣")
        for error in errors:
            print(f"║  ❌ {error:<55} ║")
        print("╚═════════════════════════════════════════════════════════╝")
        exit(1)

    # Print warnings
    if warnings:
        print("╔═════════════════════════════════════════════════════════╗")
        print("║  WARNINGS:                                               ║")
        print("╠═════════════════════════════════════════════════════════╣")
        for warning in warnings:
            print(f"║  ⚠️  {warning:<53} ║")
        print("╚═════════════════════════════════════════════════════════╝")

    print(f"""
╔═════════════════════════════════════════════════════════╗
║     YouTube Downloader & Stem Isolation Server             ║
╠═════════════════════════════════════════════════════╣
║                                                        ║
║  Server: http://localhost:{PORT}                             ║
║                                                        ║
║  Folder Structure:                                       ║
║    downloads/                                            ║
║       @ChannelName/                                       ║
║          downloads/                                        ║
║             [Beat Name].mp3                                  ║
║             isolated_samples/                                 ║
║                [Beat Name]/                                    ║
║                   [Beat Name]_(Drums).mp3                      ║
║                   [Beat Name]_(Bass).mp3                       ║
║                   [Beat Name]_(Other).mp3                      ║
║                   [Beat Name]_(Vocals).mp3                     ║
║                                                        ║
""")

    # Storage status
    if GITHUB_ENABLED:
        print(f"║  Storage: GitHub ({github_storage.GITHUB_REPO})            ║")
        print(f"║  Files stored in repository: /storage/              ║")
        print(f"║  Files over 100MB will fail!                          ║")
        # Test GitHub connection
        try:
            test_url = github_storage.upload_to_github(__file__, f'__test__.txt')
            if test_url:
                github_storage.delete_from_github(f'__test__.txt')
            else:
                print(f"║  ⚠️  GitHub upload test failed!                           ║")
        except Exception as e:
            print(f"║  ⚠️  GitHub connection error: {str(e)[:50]}             ║")
    else:
        print(f"║  Storage: Local only (files lost on redeploy)        ║")
        print(f"║  Set GITHUB_TOKEN and GITHUB_REPO for cloud storage  ║")

    print(f"║                                                        ║")
    print(f"║  Press Ctrl+C to stop                                   ║")
    print(f"╚═══════════════════════════════════════════════╝")
    print()

    # Add debug endpoint
    @app.route('/debug')
    def debug_info():
        """Debug endpoint to check configuration"""
        info = {
            'github_enabled': GITHUB_ENABLED,
            'github_repo': github_storage.GITHUB_REPO if GITHUB_ENABLED else None,
            'github_token_set': bool(github_storage.GITHUB_TOKEN) if GITHUB_ENABLED else False,
            'env_vars': {
                'GITHUB_TOKEN': os.environ.get('GITHUB_TOKEN', 'NOT_SET')[:10] + '...' if os.environ.get('GITHUB_TOKEN') else 'NOT_SET',
                'GITHUB_REPO': os.environ.get('GITHUB_REPO', 'NOT_SET'),
            },
            'working_dir': os.getcwd(),
            'python_version': f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
        }
        return jsonify(info)

    @app.route('/health')
    def health_check():
        """Health check endpoint for Render uptime monitoring"""
        return jsonify({
            'status': 'ok',
            'timestamp': time.time(),
            'github_enabled': GITHUB_ENABLED
        })

    app.run(host='0.0.0.0', port=PORT, debug=False)
