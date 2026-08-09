#!/bin/sh
set -eu

controller=http://127.0.0.1:8099

disconnect() {
  curl --fail --silent --show-error \
    -X DELETE -H 'Content-Type: application/json' \
    --data "$1" "$controller/connections"
  printf '\n'
}

disconnect '{"device_id":"voice-pe","adapter_url":"http://172.30.0.1:8088","can_transmit":false,"can_receive":true}'
disconnect '{"device_id":"room-b-camera","adapter_url":"http://room-b-camera:8080","can_transmit":true,"can_receive":false}'
disconnect '{"device_id":"room-a-camera","adapter_url":"http://room-a-camera:8080","can_transmit":true,"can_receive":false}'
