# Local intercom proof of concept

This directory contains a deliberately small FreeSWITCH intercom proof of
concept. FreeSWITCH and `mod_conference` remain the media engine. The Python
control service is stateless: the application supplies a call/room name, an
adapter descriptor, and capabilities for each connection operation, while
FreeSWITCH is the source of truth for live conference membership.

Physical devices are **not** assumed to support SIP. Each adapter has a
device-native side and a nominally duplex media side. The RTSP-camera
integration uses GStreamer for camera audio and Baresip for its internal RTP/SIP leg;
SIP is only an adapter implementation detail here. Future SIP phones can use
FreeSWITCH directly.

## Repository layout

- [`core`](core) contains the FreeSWITCH controller, media configuration, and
  the generic Python adapter runtime plus its `AudioSource` interface.
- [`integrations`](integrations) contains device-specific adapter
  entry points and documentation; importable Python implementations live in
  `intercom_integrations/`. The Voice PE firmware is under
  [`integrations/voice-pe/firmware`](integrations/voice-pe/firmware).
- [`homeassistant`](homeassistant) is reserved for the future application-layer
  controller. It will own device descriptors, gain persistence, and route
  selection; the core retains no device registry.
- [`examples`](examples) contains application-like shell clients, while
  [`tests/e2e`](tests/e2e) contains deployment smoke tests.

## Example deployment targets

| Device | Address/interface | PoC role |
| --- | --- | --- |
| Room A camera | `192.0.2.21`, RTSP, ONVIF on 2020 | microphone-only source through Frigate's local go2rtc restream |
| Room B camera | `192.0.2.22`, RTSP, ONVIF on 2020 | second microphone-only source |
| Reolink doorbell | `192.0.2.23`, RTSP | candidate two-way adapter; talk protocol is vendor-specific and not part of this first adapter |
| Home Assistant Voice PE | `192.0.2.20`, ESPHome/Home Assistant | future duplex adapter target; stock firmware is not a general SIP endpoint |
| Amazon Echo | `192.0.2.24`, Alexa integration | future speaker sink only; excluded from the offline core because normal control depends on Amazon services |

The addresses above are documentation-only examples from the RFC 5737 range.
Supply the real device addresses and stream URLs through deployment-specific
environment values; do not commit them.

The deterministic PoC participants are two synthetic duplex adapters, one
speaker-only capture adapter, and the real RTSP camera microphone. This proves
the conference and adapter boundary without claiming unsupported native
interfaces on the Voice PE or Echo.

## Run

The Compose stack is [`compose.yaml`](compose.yaml).
It publishes only the controller on loopback (`127.0.0.1:8099`). FreeSWITCH,
SIP, and RTP stay on the internal Docker network for this unauthenticated PoC.

```sh
export INTERCOM_ESL_PASSWORD="$(openssl rand -hex 24)"
docker compose config
docker compose up -d --build
curl -fsS http://127.0.0.1:8099/health | jq
```

Portainer must receive `INTERCOM_ESL_PASSWORD` as a stack environment value.
It is substituted into FreeSWITCH's event-socket configuration at container
startup and is never stored in Git.

## Exercise the routing model

The local scripts contain the two synthetic adapter descriptors. They are
deliberately application data rather than a controller registry; neither script
contains a secret.

```sh
./examples/connect-lab-clients.sh
curl -fsS http://127.0.0.1:8099/session | jq
```

The following commands connect a real camera microphone to the speaker-only
capture adapter. Its received audio is kept in three rotating WAV segments in
the `intercom_sink_captures` volume.

```sh
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"device_id":"room-a-camera","adapter_url":"http://room-a-camera:8080","can_transmit":true,"can_receive":false,"gain":{"input_level":4,"agc_target":1000}}' \
  http://127.0.0.1:8099/connections
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"device_id":"lab-speaker","adapter_url":"http://lab-speaker:8080","can_transmit":false,"can_receive":true}' \
  http://127.0.0.1:8099/connections
curl -fsS -X PUT -H 'Content-Type: application/json' \
  -d '{"enabled":true}' http://127.0.0.1:8099/routes/room-a-camera/lab-speaker
```

Disconnect the synthetic test clients:

```sh
./examples/disconnect-lab-clients.sh
```

The `voice-pe` adapter runs on the host network and exposes `/stream.flac`, a
live 48 kHz stereo FLAC stream for applications that drive the Voice PE's
native ESPHome media player directly. It forwards each available encoder chunk
immediately; it does not wait for compressed silence to fill a fixed HTTP write
block. Device selection and play/stop remain application responsibilities.

The current local application script connects both room cameras with their
owned gain settings and enables each route:

```sh
./examples/connect-rooms-to-voice-pe.sh
./examples/disconnect-rooms-from-voice-pe.sh
```

The native FLAC endpoint has an end-to-end test. It routes the synthetic source
to the capture adapter, decodes `/stream.flac`, and rejects silent or truncated
PCM:

```sh
./tests/e2e/test-flac-stream.sh
```

The reproducible custom Voice PE firmware and authenticated microphone bridge
are under [`integrations/voice-pe/firmware`](integrations/voice-pe/firmware/README.md).
The application must still explicitly connect it with `can_transmit: true`
before microphone audio can enter a session.

An ordinary SIP softphone can eventually use extension `9000` and join the same
on-demand `intercom` conference once a secured SIP profile is intentionally
published on the LAN. The fail-closed profile initially mutes and deafens every
new member, so the application layer must identify and enable an unmanaged
phone before it carries audio. The conference disappears when its final member
leaves.

## Semantics

### Calls and rooms

Each named call is an isolated, on-demand FreeSWITCH conference. The API also
accepts `rooms` as the application-facing spelling of the same resource, so an
application can use names such as `baby-monitor`, `doorbell`,
`incoming-phone-42`, and `upstairs-intercom` concurrently. The controller
does not classify, create, retain, or clean up calls: joining the first member
creates a conference and FreeSWITCH removes it after its last member leaves.
The application owns which devices belong to each call, when a call is active,
and which directional routes are allowed.

Use the call-scoped API for new integrations:

```text
GET    /calls                         # active calls
GET    /calls/{call_id}               # one call's live membership
POST   /calls/{call_id}/connections
DELETE /calls/{call_id}/connections
PUT    /calls/{call_id}/routes/{source}/{sink}
```

`/rooms` and `/rooms/{room_id}/...` provide identical operations for clients
that prefer room terminology. Call and device IDs must use lowercase letters,
digits, and hyphens. The original `/session`, `/connections`, and `/routes`
endpoints remain available for the default `intercom` call (override it with
`INTERCOM_DEFAULT_CALL` for a deployment). An adapter can participate in only
one call at a time; a second connection request for a different call is
rejected instead of silently interrupting the first call.

For example, connect and route the doorbell independently of the default
intercom room:

```sh
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"device_id":"room-a-camera","adapter_url":"http://room-a-camera:8080","can_transmit":true,"can_receive":false}' \
  http://127.0.0.1:8099/calls/doorbell/connections
curl -fsS -X PUT -H 'Content-Type: application/json' \
  -d '{"enabled":true}' \
  http://127.0.0.1:8099/calls/doorbell/routes/room-a-camera/voice-pe
```

- `can_transmit: false` causes the controller to apply conference `mute`.
- `can_receive: false` causes it to apply conference `deaf`.
- A disabled route from A to B applies `relate A B nospeak`.
- An enabled route clears that A-to-B relationship.
- Device names, capabilities, and adapter URLs are supplied by the application
  with each connect or disconnect request; the controller does not retain a
  device registry. `adapter_url` may be `null` when the participant has already
  joined FreeSWITCH directly.
- A connection descriptor may include optional `gain` settings. `input_level`
  and `output_level` are FreeSWITCH member levels from `-4` through `4`;
  `agc_target` is from `1` through `1800`. The controller applies only supplied
  settings on every connect or reauthorization, so the application owns their
  persistence. Omit a setting to leave FreeSWITCH's current/default value
  unchanged.
- The API starts from deny-by-default relationships when a participant joins;
  callers must explicitly enable desired directions.

Echo cancellation, authentication of the local HTTP API, encryption, and
provisioning remain intentionally out of scope. The API is therefore bound to
loopback and must not be exposed through Traefik.

## Telephone evolution

The PoC's internal SIP profile can be cloned and secured for registered phones
and a later trunk. An inbound trunk call can be placed into a validated named
conference such as `incoming-phone-42@wideband`, while house devices join that
same call through the scoped API. Nothing in the controller assumes that a
session contains only adapter-originated calls.
