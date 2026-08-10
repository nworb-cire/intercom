#!/bin/sh
set -eu

if [ -z "${INTERCOM_ESL_PASSWORD:-}" ]; then
  echo "INTERCOM_ESL_PASSWORD is required" >&2
  exit 78
fi
if ! printf '%s' "$INTERCOM_ESL_PASSWORD" | grep -Eq '^[A-Za-z0-9._-]{16,128}$'; then
  echo "INTERCOM_ESL_PASSWORD must be 16-128 URL-safe characters" >&2
  exit 78
fi

escaped_password=$(printf '%s' "$INTERCOM_ESL_PASSWORD" | sed 's/[&|\\]/\\&/g')
sed "s|__INTERCOM_ESL_PASSWORD__|$escaped_password|g" \
  /opt/intercom/event_socket.conf.xml.template \
  >/etc/freeswitch/autoload_configs/event_socket.conf.xml
chmod 0600 /etc/freeswitch/autoload_configs/event_socket.conf.xml

exec /docker-entrypoint.sh "$@"
