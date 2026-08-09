#!/bin/sh
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

if [ "${#home_assistant_token}" -ge 32 ]; then
  curl --fail --silent --show-error \
    -X POST \
    -H "Authorization: Bearer $home_assistant_token" \
    -H 'Content-Type: application/json' \
    --data "$(jq -cn --arg entity_id "$media_player" '{entity_id:[$entity_id]}')" \
    "$home_assistant_url/api/services/media_player/stop" >/dev/null
fi

disconnect() {
  curl --fail --silent --show-error \
    -X DELETE -H 'Content-Type: application/json' \
    --data "$1" "$controller/connections"
  printf '\n'
}

disconnect '{"device_id":"voice-pe","adapter_url":"http://172.30.0.1:8088","can_transmit":false,"can_receive":true}'
disconnect '{"device_id":"room-b-camera","adapter_url":"http://room-b-camera:8080","can_transmit":true,"can_receive":false}'
disconnect '{"device_id":"room-a-camera","adapter_url":"http://room-a-camera:8080","can_transmit":true,"can_receive":false}'
