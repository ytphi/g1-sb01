#!/usr/bin/env bash
# convention.sh — check that everything is ready, then start Yotie as it ran in the lab.
#
#   Terminal 1 (leave it running, wait for its "ready" line):
#       cd ~/sb01-conversation && ~/RoboGesture/.venv/bin/python -u scripts/gesture_server.py
#   Terminal 2, with the robot standing in walk mode:
#       cd ~/sb01-conversation && bash scripts/convention.sh
#
# The settings below: replies from the local model (Ollama: no internet, no API
# key), Chatterbox voice with English on the graphics card, arm gestures on,
# teaching gestures off. SB01_LLM=claude puts the replies back on Claude.
# Any of them can be set for one run in front of the command, for example
#       SB01_GESTURE_CUES=1 SB01_BOARD_SIDE=right bash scripts/convention.sh
# (a setting in the `env` file still wins over both).
#
#   bash scripts/convention.sh check     only the checks; Yotie is not started
set -u
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."

INTERFACE="${SB01_INTERFACE:-enp2s0}"
export SB01_LLM="${SB01_LLM:-local}"
export SB01_VOICE="${SB01_VOICE:-chatterbox}"
export SB01_CHATTERBOX_DEVICE="${SB01_CHATTERBOX_DEVICE:-cuda}"
export SB01_CHATTERBOX_GPU_ENGINES="${SB01_CHATTERBOX_GPU_ENGINES:-nano}"
export SB01_GESTURE_URL="${SB01_GESTURE_URL:-http://127.0.0.1:8765}"

if python3 scripts/preflight.py "$INTERFACE"; then
    [ "${1:-}" = check ] && exit 0
else
    [ "${1:-}" = check ] && exit 1
    read -r -p "Start Yotie anyway? [y/N] " answer
    case "$answer" in y|Y|yes) ;; *) exit 1 ;; esac
fi
echo
exec python3 -u scripts/sb01_conversation.py "$INTERFACE"
