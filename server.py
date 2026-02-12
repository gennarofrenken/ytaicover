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
"""

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import subprocess
import threading
import queue
import os
import re
import json

app = Flask(__name__)
CORS(app)

DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
PORT = 8080
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


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


def run_ytdlp(url, downloads_dir, to_mp3, progress_queue, mode='channel'):
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

        cmd.extend(['-o', os.path.join(downloads_dir, '%(title)s.%(ext)s'), url])

        progress_queue.put({'status': f'Starting {mode_label.lower()} download...'})

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, bufsize=1)

        beat_folders = []

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
                    if beat_name not in beat_folders:
                        beat_folders.append(beat_name)
            if '[download] 100%' in line:
                progress_queue.put({'progress': 100})

        process.wait()

        # Create isolated_samples folder for each beat
        for beat_name in beat_folders:
            beat_folder = os.path.join(downloads_dir, beat_name)
            if os.path.exists(beat_folder):
                iso_dir = os.path.join(beat_folder, 'isolated_samples')
                os.makedirs(iso_dir, exist_ok=True)

        if process.returncode == 0:
            count = len(beat_folders)
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

        # Scan for MP3s in beat folders (structure: @Channel/Beat Name/Beat Name.mp3)
        mp3_files = []
        for item in os.listdir(channel_dir):
            beat_folder = os.path.join(channel_dir, item)
            if os.path.isdir(beat_folder):
                # Look for MP3 with same name as folder
                mp3_path = os.path.join(beat_folder, item + '.mp3')
                if os.path.exists(mp3_path):
                    # If specific beat requested, only include that one
                    if beat is None or item == beat:
                        mp3_files.append((item, mp3_path))

        if not mp3_files:
            progress_queue.put({'error': 'No MP3 files found', 'complete': True})
            return

        model = 'htdemucs.yaml'
        total = len(mp3_files)
        
        for i, (beat_name, mp3_file) in enumerate(mp3_files, 1):
            progress_queue.put({'status': f'[{i}/{total}] {beat_name}'})

            # Create isolated_samples folder in beat folder
            beat_folder = os.path.join(channel_dir, beat_name)
            iso_dir = os.path.join(beat_folder, 'isolated_samples')
            os.makedirs(iso_dir, exist_ok=True)

            cmd = [
                'audio-separator',
                mp3_file,
                '-m', model,
                '--output_dir', iso_dir,
                '--output_format', 'mp3',
            ]

            progress_queue.put({'status': f'Starting AI stem isolation (~30-60s per beat)...'})

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode == 0:
                # Rename stems to desired format: StemType_[Beat Name]_htdemucs.mp3
                stem_prefix_map = {
                    '(Vocals)': 'Vocals',
                    '(Instrumental)': 'Other',
                    '(Drums)': 'Drums',
                    '(Other)': 'Other',
                    '(Bass)': 'Bass'
                }
                for f in os.listdir(iso_dir):
                    if f.endswith('.mp3'):
                        new_name = f
                        # Find stem type from audio-separator output
                        for old, prefix in stem_prefix_map.items():
                            if old in f:
                                # Construct new name: StemType_[Beat Name]_htdemucs.mp3
                                new_name = f'{prefix}_{beat_name}_htdemucs.mp3'
                                break
                        if new_name != f:
                            src = os.path.join(iso_dir, f)
                            dst = os.path.join(iso_dir, new_name)
                            os.rename(src, dst)
                            progress_queue.put({'status': f'Created: {new_name}'})
                progress_queue.put({'status': f'Completed: {beat_name}'})
            else:
                progress_queue.put({'error': f"Failed: {beat_name}"})

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
    downloads_dir = os.path.join(channel_dir, 'downloads')
    os.makedirs(downloads_dir, exist_ok=True)

    progress_queue = queue.Queue()
    thread = threading.Thread(target=run_ytdlp, args=(url, downloads_dir, to_mp3, progress_queue, mode))
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
    folders = []
    try:
        for item in os.listdir(DOWNLOADS_DIR):
            item_path = os.path.join(DOWNLOADS_DIR, item)
            if os.path.isdir(item_path):
                # Count beat folders (each contains an MP3 with same name)
                beat_count = 0
                has_isolated = False
                for beat_folder in os.listdir(item_path):
                    beat_path = os.path.join(item_path, beat_folder)
                    if os.path.isdir(beat_path):
                        mp3_file = os.path.join(beat_path, beat_folder + '.mp3')
                        if os.path.exists(mp3_file):
                            beat_count += 1
                            # Check if isolated_samples exists
                            iso_dir = os.path.join(beat_path, 'isolated_samples')
                            if os.path.exists(iso_dir) and os.listdir(iso_dir):
                                has_isolated = True
                folders.append({'name': item, 'count': beat_count, 'hasIsolated': has_isolated})
    except Exception:
        pass

    return jsonify(folders)


@app.route('/beats/<channel>')
def list_beats(channel):
    beats = []
    try:
        channel_dir = os.path.join(DOWNLOADS_DIR, channel)
        if os.path.exists(channel_dir):
            for item in os.listdir(channel_dir):
                beat_folder = os.path.join(channel_dir, item)
                if os.path.isdir(beat_folder):
                    # Check for MP3 file with same name as folder
                    mp3_path = os.path.join(beat_folder, item + '.mp3')
                    if os.path.exists(mp3_path):
                        # Check if isolated_samples exists for this beat
                        iso_dir = os.path.join(beat_folder, 'isolated_samples')
                        has_isolated = os.path.exists(iso_dir) and os.listdir(iso_dir)
                        beats.append({'name': item, 'hasIsolated': has_isolated})
    except Exception:
        pass

    return jsonify(beats)


@app.route('/samples')
def list_samples():
    samples = []
    try:
        for item in os.listdir(DOWNLOADS_DIR):
            item_path = os.path.join(DOWNLOADS_DIR, item)
            if os.path.isdir(item_path):
                # Look for isolated_samples in each beat folder
                stems = []
                for beat_folder in os.listdir(item_path):
                    beat_path = os.path.join(item_path, beat_folder)
                    if os.path.isdir(beat_path):
                        iso_dir = os.path.join(beat_path, 'isolated_samples')
                        if os.path.exists(iso_dir):
                            for f in os.listdir(iso_dir):
                                if f.endswith('.mp3'):
                                    stems.append({'name': f, 'beat': beat_folder})
                if stems:
                    samples.append({'name': item, 'stems': stems, 'count': len(stems)})
    except Exception:
        pass

    return jsonify(samples)


@app.route('/stems/<channel>/<beat>')
def list_stems(channel, beat):
    stems = []
    try:
        beat_path = os.path.join(DOWNLOADS_DIR, channel, beat)
        iso_dir = os.path.join(beat_path, 'isolated_samples')
        if os.path.exists(iso_dir):
            for f in os.listdir(iso_dir):
                if f.endswith('.mp3'):
                    # Extract stem type from filename (e.g., Vocals_..., Drums_..., etc.)
                    stem_type = 'Unknown'
                    if f.startswith('Vocals_'): stem_type = 'Vocals'
                    elif f.startswith('Drums_'): stem_type = 'Drums'
                    elif f.startswith('Bass_'): stem_type = 'Bass'
                    elif f.startswith('Other_'): stem_type = 'Melody'
                    stems.append({
                        'name': f,
                        'type': stem_type,
                        'path': os.path.join(iso_dir, f)
                    })
    except Exception:
        pass
    return jsonify(stems)


@app.route('/cover', methods=['POST'])
def generate_cover():
    data = request.json
    channel = data.get('channel', '')
    beat = data.get('beat', '')
    selected_stems = data.get('stems', [])

    if not channel or not beat:
        return jsonify({'error': 'Channel and beat required'}), 400

    if not selected_stems:
        return jsonify({'error': 'Please select at least one stem'}), 400

    # For now, return a message that YuE needs to be installed separately
    progress_queue = queue.Queue()
    progress_queue.put({'status': 'AI Cover generation requires YuE installation.'})
    progress_queue.put({'status': 'Please install YuE from https://github.com/multimodal-art-projection/YuE'})
    progress_queue.put({'complete': True, 'message': 'YuE not installed. Install it to enable AI Cover generation.'})

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
    try:
        subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
    except:
        print("yt-dlp not found. Install: pip install yt-dlp")
        exit(1)

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
║  Press Ctrl+C to stop                                   ║
╚═══════════════════════════════════════════════╝
    """)

    app.run(host='localhost', port=PORT, debug=False)
