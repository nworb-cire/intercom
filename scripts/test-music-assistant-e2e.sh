#!/bin/sh
# Plays a short 440 Hz conference source and verifies PCM reaches Music Assistant.
set -eu

controller=http://127.0.0.1:8099
voice_adapter=http://127.0.0.1:8088

disconnect() {
  curl --silent --show-error \
    -X DELETE -H 'Content-Type: application/json' \
    --data "$1" "$controller/connections" >/dev/null || true
}

cleanup() {
  disconnect '{"device_id":"voice-pe","adapter_url":"http://172.30.0.1:8088","can_transmit":false,"can_receive":true}'
  disconnect '{"device_id":"lab-a","adapter_url":"http://lab-a:8080","can_transmit":true,"can_receive":false}'
}
trap cleanup EXIT INT TERM

curl --fail --silent --show-error \
  -X POST -H 'Content-Type: application/json' \
  --data '{"device_id":"lab-a","adapter_url":"http://lab-a:8080","can_transmit":true,"can_receive":false}' \
  "$controller/connections" >/dev/null
curl --fail --silent --show-error \
  -X POST -H 'Content-Type: application/json' \
  --data '{"device_id":"voice-pe","adapter_url":"http://172.30.0.1:8088","can_transmit":false,"can_receive":true}' \
  "$controller/connections" >/dev/null
curl --fail --silent --show-error \
  -X PUT -H 'Content-Type: application/json' \
  --data '{"enabled":true}' "$controller/routes/lab-a/voice-pe" >/dev/null

for attempt in $(seq 1 30); do
  health=$(curl --fail --silent --show-error "$voice_adapter/health")
  if printf '%s' "$health" | jq -e \
    '.connected and .music_assistant and .stream_clients > 0 and .stream_pcm_bytes > 32000 and .stream_peak > 100' \
    >/dev/null; then
    printf '%s\n' "$health" | jq -c \
      '{connected,music_assistant,stream_clients,stream_pcm_bytes,stream_peak}'
    exit 0
  fi
  sleep 1
done

printf 'Music Assistant did not consume non-silent conference PCM\n' >&2
exit 1
