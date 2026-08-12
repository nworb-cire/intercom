# Home Assistant application stub

This directory is reserved for the future Home Assistant application-layer
controller. It will own call policy (for example baby monitor, doorbell,
phone, and intercom calls), room/device membership, endpoint descriptors,
persisted gain settings, connection/disconnection operations, and directional
routes to the generic core API. It should use `/calls/{call_id}/...` (or the
equivalent `/rooms/{room_id}/...`) so each active call is isolated.

The core intentionally does not discover or register devices. Until the
application is implemented, use the scripts in `examples/` as temporary local
clients.
