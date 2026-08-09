#!/bin/sh
# Local proof-of-concept clients. These descriptors are intentionally hardcoded
# here, not retained by the intercom controller.
set -eu

controller=http://127.0.0.1:8099

connect() {
  curl --fail --silent --show-error \
    -X POST -H 'Content-Type: application/json' \
    --data "$1" "$controller/connections"
  printf '\n'
}

connect '{"device_id":"lab-a","adapter_url":"http://lab-a:8080","can_transmit":true,"can_receive":true}'
connect '{"device_id":"lab-b","adapter_url":"http://lab-b:8080","can_transmit":true,"can_receive":true}'

curl --fail --silent --show-error \
  -X PUT -H 'Content-Type: application/json' \
  --data '{"enabled":true}' "$controller/routes/lab-a/lab-b"
printf '\n'
curl --fail --silent --show-error \
  -X PUT -H 'Content-Type: application/json' \
  --data '{"enabled":true}' "$controller/routes/lab-b/lab-a"
printf '\n'
