#!/bin/bash
while true; do
    python3 main.py
    echo "Script crashed with exit code $?. Restarting in 5 seconds..."
    sleep 1
done