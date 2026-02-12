#!/bin/bash
# YouTube Downloader & Stem Isolation Server
# Start script for the web interface

cd "$(dirname "$0")"

echo "Starting YouTube Downloader & Stem Isolation Server..."
echo ""
echo "╔═══════════════════════════════════════════════════════╗"
echo "║     YouTube Downloader & Stem Isolation Server             ║"
echo "╠═══════════════════════════════════════════════════════╣"
echo "║                                                       ║"
echo "║  Server: http://localhost:8080                             ║"
echo "║                                                       ║"
echo "║  Opening in browser...                                 ║"
echo "║                                                       ║"
echo "║  Press Ctrl+C to stop the server                        ║"
echo "║                                                       ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# Check if Python 3 is available
if command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

# Start the server
exec $PYTHON server.py
