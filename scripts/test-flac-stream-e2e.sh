#!/bin/sh
# Verify a conference tone survives the adapter's live FLAC encoder.
set -eu

controller=${INTERCOM_CONTROLLER_URL:-http://127.0.0.1:8099}
capture_dir=$(mktemp -d)
capture_file=$capture_dir/stream.pcm

disconnect() {
  curl --silent --show-error \
    -X DELETE -H 'Content-Type: application/json' \
    --data "$1" "$controller/connections" >/dev/null || true
}

cleanup() {
  disconnect '{"device_id":"lab-speaker","adapter_url":"http://lab-speaker:8080","can_transmit":false,"can_receive":true}'
  disconnect '{"device_id":"lab-a","adapter_url":"http://lab-a:8080","can_transmit":true,"can_receive":false}'
  rm -rf "$capture_dir"
}
trap cleanup EXIT INT TERM

curl --fail --silent --show-error \
  -X POST -H 'Content-Type: application/json' \
  --data '{"device_id":"lab-a","adapter_url":"http://lab-a:8080","can_transmit":true,"can_receive":false}' \
  "$controller/connections" >/dev/null
curl --fail --silent --show-error \
  -X POST -H 'Content-Type: application/json' \
  --data '{"device_id":"lab-speaker","adapter_url":"http://lab-speaker:8080","can_transmit":false,"can_receive":true}' \
  "$controller/connections" >/dev/null
curl --fail --silent --show-error \
  -X PUT -H 'Content-Type: application/json' \
  --data '{"enabled":true}' "$controller/routes/lab-a/lab-speaker" >/dev/null

decoder_container=$(docker ps \
  --filter label=com.docker.compose.project=intercom \
  --filter label=com.docker.compose.service=lab-a \
  --format '{{.ID}}')
if [ -z "$decoder_container" ] || [ "$(printf '%s\n' "$decoder_container" | wc -l)" -ne 1 ]; then
  echo 'could not identify exactly one intercom lab-a container' >&2
  exit 1
fi

docker exec "$decoder_container" \
  ffmpeg -nostdin -loglevel error \
    -i http://lab-speaker:8080/stream.flac \
    -t 2 -ac 1 -ar 16000 -f s16le pipe:1 >"$capture_file"

python3 - "$capture_file" <<'PY'
from pathlib import Path
import struct
import sys

payload = Path(sys.argv[1]).read_bytes()
samples = struct.unpack(f"<{len(payload) // 2}h", payload[: len(payload) // 2 * 2])
peak = max((abs(sample) for sample in samples), default=0)
if len(payload) < 32000 or peak < 100:
    raise SystemExit(f"invalid FLAC capture: bytes={len(payload)} peak={peak}")
print(f"FLAC stream verified: bytes={len(payload)} peak={peak}")
PY
