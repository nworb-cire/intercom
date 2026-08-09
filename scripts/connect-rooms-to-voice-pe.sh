#!/bin/sh
# Example application-owned settings for the live room-camera -> Voice PE
# routes.  The Voice PE is driven by Home Assistant's native ESPHome media
# player; Music Assistant is not part of this path.
set -eu

env_file=${INTERCOM_ENV_FILE:-.env}
if [ -f "$env_file" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
fi

controller=${INTERCOM_CONTROLLER_URL:-http://127.0.0.1:8099}
home_assistant_url=${HOME_ASSISTANT_URL:-${HOMEASSISTANT_URL:-http://127.0.0.1:8123}}
home_assistant_token=${HOME_ASSISTANT_TOKEN:-${HOMEASSISTANT_TOKEN:-}}
media_player=${HOME_ASSISTANT_MEDIA_PLAYER:-media_player.home_assistant_voice_example_media_player}
stream_url=${INTERCOM_STREAM_URL:-http://192.0.2.10:8088/stream.wav}

case "$home_assistant_url" in
  http://*|https://*) ;;
  *) echo 'HOME_ASSISTANT_URL must use http:// or https://' >&2; exit 2 ;;
esac
if [ "${#home_assistant_token}" -lt 32 ]; then
  echo 'HOME_ASSISTANT_TOKEN (or HOMEASSISTANT_TOKEN) is required' >&2
  exit 2
fi

connect() {
  curl --fail --silent --show-error \
    -X POST -H 'Content-Type: application/json' \
    --data "$1" "$controller/connections"
  printf '\n'
}

# Gain is supplied by this caller, not stored by the controller or adapter.
connect '{"device_id":"room-b-camera","adapter_url":"http://room-b-camera:8080","can_transmit":true,"can_receive":false,"gain":{"input_level":4,"agc_target":1000}}'
connect '{"device_id":"room-a-camera","adapter_url":"http://room-a-camera:8080","can_transmit":true,"can_receive":false,"gain":{"input_level":4,"agc_target":1000}}'
connect '{"device_id":"voice-pe","adapter_url":"http://172.30.0.1:8088","can_transmit":false,"can_receive":true}'

curl --fail --silent --show-error \
  -X POST \
  -H "Authorization: Bearer $home_assistant_token" \
  -H 'Content-Type: application/json' \
  --data "$(jq -cn \
    --arg entity_id "$media_player" \
    --arg media_content_id "$stream_url" \
    '{entity_id:[$entity_id],media_content_id:$media_content_id,media_content_type:"audio/wav"}')" \
  "$home_assistant_url/api/services/media_player/play_media"
printf '\n'

for source in room-b-camera room-a-camera; do
  curl --fail --silent --show-error \
    -X PUT -H 'Content-Type: application/json' \
    --data '{"enabled":true}' "$controller/routes/$source/voice-pe"
  printf '\n'
done
