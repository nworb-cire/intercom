#!/bin/sh
# Example application-owned endpoint settings for the live Room B -> Voice PE route.
set -eu

controller=http://127.0.0.1:8099

connect() {
  curl --fail --silent --show-error \
    -X POST -H 'Content-Type: application/json' \
    --data "$1" "$controller/connections"
  printf '\n'
}

# Gain is intentionally supplied by this caller, not stored by the controller.
connect '{"device_id":"room-b-camera","adapter_url":"http://room-b-camera:8080","can_transmit":true,"can_receive":false,"gain":{"input_level":4,"agc_target":1000}}'
connect '{"device_id":"voice-pe","adapter_url":"http://172.30.0.1:8088","can_transmit":false,"can_receive":true}'

curl --fail --silent --show-error \
  -X PUT -H 'Content-Type: application/json' \
  --data '{"enabled":true}' "$controller/routes/room-b-camera/voice-pe"
printf '\n'
