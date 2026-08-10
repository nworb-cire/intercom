#!/bin/sh
# Local proof-of-concept clients. The controller stores no endpoint registry.
set -eu

controller=http://127.0.0.1:8099

disconnect() {
  curl --fail --silent --show-error \
    -X DELETE -H 'Content-Type: application/json' \
    --data "$1" "$controller/connections"
  printf '\n'
}

disconnect '{"device_id":"lab-b","adapter_url":"http://lab-b:8080","can_transmit":true,"can_receive":true}'
disconnect '{"device_id":"lab-a","adapter_url":"http://lab-a:8080","can_transmit":true,"can_receive":true}'
