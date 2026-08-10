#!/bin/sh
# Backward-compatible entry point; the live application script now enables both rooms.
set -eu

exec "$(dirname "$0")/connect-rooms-to-voice-pe.sh"
