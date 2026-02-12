#!/bin/bash
# YouTube Downloader - Stop Server
# Double-click this file to stop the server

echo "Stopping server..."

# Find and kill the server process
PID=$(lsof -t -i :8080)

if [ -n "$PID" ]; then
    kill $PID
    echo "Server stopped!"
    sleep 2
else
    echo "Server was not running"
fi

sleep 1
