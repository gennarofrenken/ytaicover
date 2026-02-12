#!/usr/bin/env python3
"""
Melody Extraction Script
Extracts melody/instrumental stem and saves to flipped_samples/
Perfect for sampling without drums.
"""

import os
import subprocess
import argparse

# Configuration
SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
OUTPUT_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')  # Parent of beat folders
MODEL = 'htdemucs'  # 4-stem model for extracting instrumental/melody

def extract_melody(input_file, beat_folder):
    """Extract melody/instrumental from an MP3 file."""
    try:
        base_name = os.path.basename(input_file).replace('.mp3', '')
        print(f"  Processing: {base_name}")

        # Create isolated_samples folder in beat folder
        iso_dir = os.path.join(beat_folder, 'isolated_samples')
        os.makedirs(iso_dir, exist_ok=True)

        cmd = [
            'audio-separator',
            input_file,
            '-m', MODEL,
            '--output_dir', iso_dir,
            '--output_format', 'mp3',
            '--single_stem', 'Other',  # Extract only the melody/instrumental stem
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            # Find the "Other" stem output (melody/instrumental)
            for f in os.listdir(iso_dir):
                if f.endswith('.mp3') and ('(Other)' in f or '(Instrumental)' in f):
                    # Rename to clearer format
                    if '(Other)' in f:
                        new_name = f"{base_name}_Melody.mp3"
                    else:
                        new_name = f"{base_name}_Instrumental.mp3"
                    src = os.path.join(iso_dir, f)
                    dst = os.path.join(iso_dir, new_name)
                    os.rename(src, dst)
                    print(f"  ✓ Created: {new_name}")
                    return True
        return False
    except subprocess.TimeoutExpired:
        print(f"  ✗ Timeout")
        return False
    except Exception as e:
        print(f"  ✗ Error: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Extract melody/instrumental from MP3s')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation')
    parser.add_argument('--limit', '-l', type=int, help='Limit files')
    parser.add_argument('--folder', '-f', help='Specific channel folder')
    args = parser.parse_args()

    print("""
╔═════════════════════════════════════════════════════╗
║          MELODY EXTRACTION FOR SAMPLING               ║
╠═════════════════════════════════════════════════╣
║  Extracts melody/instrumental from your beats                 ║
║  Perfect for sampling without drums                       ║
╚═════════════════════════════════════════════════════╝
    """)

    # Determine source folder
    mp3_files = []

    if args.folder:
        channel_dir = os.path.join(SOURCE_DIR, args.folder)
        if os.path.exists(channel_dir):
            for item in os.listdir(channel_dir):
                beat_folder = os.path.join(channel_dir, item)
                if os.path.isdir(beat_folder):
                    mp3_path = os.path.join(beat_folder, item + '.mp3')
                    if os.path.exists(mp3_path):
                        mp3_files.append(mp3_path)
        if not mp3_files:
            print(f"Error: Channel '{args.folder}' not found or has no MP3s")
            return
    else:
        # Scan all channels for MP3s
        for item in os.listdir(SOURCE_DIR):
            item_path = os.path.join(SOURCE_DIR, item)
            if os.path.isdir(item_path):
                # Look for beat folders (structure: @Channel/Beat Name/Beat.mp3)
                for beat_folder in os.listdir(item_path):
                    beat_path = os.path.join(item_path, beat_folder)
                    if os.path.isdir(beat_path):
                        mp3_path = os.path.join(beat_path, beat_folder + '.mp3')
                        if os.path.exists(mp3_path):
                            mp3_files.append(mp3_path)

    if not mp3_files:
        print("No MP3 files found.")
        return

    if args.limit and args.limit > 0:
        mp3_files = mp3_files[:args.limit]
        print(f"Processing first {len(mp3_files)} files (limited).")
    else:
        print(f"Found {len(mp3_files)} MP3 file(s) to process.\\n")

    # Confirmation for large batches
    if len(mp3_files) > 5 and not args.yes:
        try:
            response = input(f"Process all {len(mp3_files)} files? (y/n): ").strip().lower()
            if response != 'y':
                print("Cancelled.")
                return
        except EOFError:
            pass

    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Process each file
    success_count = 0
    for i, mp3_file in enumerate(mp3_files, 1):
        base_name = os.path.basename(mp3_file).replace('.mp3', '')

        print(f"[{i}/{len(mp3_files)}] {base_name}")

        if extract_melody(mp3_file, OUTPUT_DIR):
            success_count += 1

    print(f"\\n{'='*60}")
    print(f"COMPLETE! {success_count}/{len(mp3_files)} files processed")
    print(f"Output saved to: {OUTPUT_DIR}/")
    print(f"{'='*60}\\n")

if __name__ == '__main__':
    main()
