#!/bin/sh
# Verify that a conference source reaches the Voice PE through HA's native
# ESPHome media_player.play_media path, without Music Assistant.
set -eu

env_file=${INTERCOM_ENV_FILE:-.env}
if [ -f "$env_file" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
fi

controller=${INTERCOM_CONTROLLER_URL:-http://127.0.0.1:8099}
voice_adapter=${VOICE_ADAPTER_URL:-http://127.0.0.1:8088}
home_assistant_url=${HOME_ASSISTANT_URL:-${HOMEASSISTANT_URL:-http://127.0.0.1:8123}}
home_assistant_token=${HOME_ASSISTANT_TOKEN:-${HOMEASSISTANT_TOKEN:-}}
media_player=${HOME_ASSISTANT_MEDIA_PLAYER:-media_player.home_assistant_voice_example_media_player}
stream_url=${INTERCOM_STREAM_URL:-http://192.0.2.10:8088/stream.wav}

if [ "${#home_assistant_token}" -lt 32 ]; then
  echo 'HOME_ASSISTANT_TOKEN (or HOMEASSISTANT_TOKEN) is required' >&2
  exit 2
fi

voice_added=0
played=0
cleanup() {
  set +e
  curl --silent --show-error -X PUT -H 'Content-Type: application/json' \
    --data '{"enabled":false}' "$controller/routes/lab-a/voice-pe" >/dev/null
  if [ "$played" -eq 1 ]; then
    curl --silent --show-error -X POST \
      -H "Authorization: Bearer $home_assistant_token" \
      -H 'Content-Type: application/json' \
      --data "$(jq -cn --arg entity_id "$media_player" '{entity_id:[$entity_id]}')" \
      "$home_assistant_url/api/services/media_player/stop" >/dev/null
  fi
  curl --silent --show-error -X DELETE -H 'Content-Type: application/json' \
    --data '{"device_id":"lab-a","adapter_url":"http://lab-a:8080","can_transmit":true,"can_receive":false}' \
    "$controller/connections" >/dev/null
  if [ "$voice_added" -eq 1 ]; then
    curl --silent --show-error -X DELETE -H 'Content-Type: application/json' \
      --data '{"device_id":"voice-pe","adapter_url":"http://172.30.0.1:8088","can_transmit":false,"can_receive":true}' \
      "$controller/connections" >/dev/null
  fi
}
trap cleanup EXIT INT TERM

if ! curl --fail --silent "$controller/session" | jq -e '.members[] | select(.device_id == "voice-pe")' >/dev/null; then
  curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' \
    --data '{"device_id":"voice-pe","adapter_url":"http://172.30.0.1:8088","can_transmit":false,"can_receive":true}' \
    "$controller/connections" >/dev/null
  voice_added=1
fi

curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' \
  --data '{"device_id":"lab-a","adapter_url":"http://lab-a:8080","can_transmit":true,"can_receive":false}' \
  "$controller/connections" >/dev/null

before=$(curl --fail --silent "$voice_adapter/health" | jq -r '.stream_pcm_bytes')
curl --fail --silent --show-error -X POST \
  -H "Authorization: Bearer $home_assistant_token" \
  -H 'Content-Type: application/json' \
  --data "$(jq -cn \
    --arg entity_id "$media_player" \
    --arg media_content_id "$stream_url" \
    '{entity_id:[$entity_id],media_content_id:$media_content_id,media_content_type:"audio/wav"}')" \
  "$home_assistant_url/api/services/media_player/play_media" >/dev/null
played=1

curl --fail --silent --show-error -X PUT -H 'Content-Type: application/json' \
  --data '{"enabled":true}' "$controller/routes/lab-a/voice-pe" >/dev/null

for _ in $(seq 1 30); do
  health=$(curl --fail --silent --show-error "$voice_adapter/health")
  if printf '%s' "$health" | jq -e \
    --argjson before "$before" \
    '.connected and (.music_assistant == false) and .stream_clients > 0 and .stream_pcm_bytes > $before and .stream_peak > 100' \
    >/dev/null; then
    printf '%s\n' "$health" | jq -c \
      '{connected,music_assistant,stream_clients,stream_pcm_bytes,stream_peak}'
    exit 0
  fi
  sleep 1
done

echo 'Voice PE did not consume non-silent conference PCM through ESPHome' >&2
printf '%s\n' "$health" >&2
exit 1
