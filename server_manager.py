#!/usr/bin/env python3
"""
Simple server manager for YouTube Downloader
Start/stop the Flask server cleanly with double-click
"""

import os
import sys
import signal
import subprocess
from pathlib import Path

DOWNLOADS_DIR = Path(__file__).parent.absolute()
SERVER_PID_FILE = DOWNLOADS_DIR / '.server_pid'

def find_server_pid():
    """Find any Python server.py process on port 8080"""
    try:
        result = subprocess.run(['lsof', '-i', ':8080', '-t', '-P', 'PYTHON'],
                                    capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Parse PID from output
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    try:
                        # Format: "PID   12345"
                        parts = line.split()
                        if len(parts) >= 2:
                            pid_part = parts[-1]  # Last part should be the PID
                            if pid_part.strip().isdigit():
                                return int(pid_part)
                    except:
                        pass
        return None
    except:
        return None

def start_server():
    """Start the Flask server"""
    print("Starting YouTube Downloader server...")

    # Change to project directory
    os.chdir(DOWNLOADS_DIR)

    # Start server
    process = subprocess.Popen([sys.executable, 'server.py'],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,
                              universal_newlines=True)

    # Save PID
    with open(SERVER_PID_FILE, 'w') as f:
        f.write(str(process.pid))

    print(f"Server started! (PID: {process.pid})")
    print(f"Open http://localhost:8080 in your browser")
    print("Press Ctrl+C to stop")

def stop_server():
    """Stop the Flask server"""
    # Try to read PID from file
    try:
        with open(SERVER_PID_FILE, 'r') as f:
            saved_pid = f.read().strip()
            if saved_pid:
                pid = int(saved_pid)
                # Try to kill the process
                os.kill(pid)
                print(f"Stopped server (PID: {pid})")

                # Clear PID file
                open(SERVER_PID_FILE, 'w').truncate(0)
                return
    except FileNotFoundError:
            pass

    # Fallback: find and kill any server on port 8080
    print("Looking for server processes...")
    pid = find_server_pid()
    if pid:
        try:
            os.kill(pid)
            print(f"Stopped server (PID: {pid})")
        except ProcessLookupError:
            print("Server not found or already stopped")

    # Clear PID file
    open(SERVER_PID_FILE, 'w').truncate(0)

def show_status():
    """Show if server is running"""
    pid = find_server_pid()
    if pid:
        status = f"● Running (PID: {pid})"
        color = "\033[92m"  # Green
    else:
        status = "○ Stopped"
        color = "\033[91m"  # Red

    print(f"Status: {status}")
    return color

def main():
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        if command == 'start':
            start_server()
        elif command == 'stop':
            stop_server()
        elif command == 'status':
            show_status()
        else:
            print("Usage: python3 server_manager.py [start|stop|status]")
            sys.exit(1)
    else:
        # Show status by default
        show_status()

if __name__ == '__main__':
    main()
