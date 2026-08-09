# Local intercom proof of concept

This directory contains a deliberately small FreeSWITCH intercom proof of
concept. FreeSWITCH and `mod_conference` remain the media engine. The Python
control service is stateless: the application supplies an adapter descriptor
and capabilities for each connection operation, while FreeSWITCH is the source
of truth for live conference membership.

Physical devices are **not** assumed to support SIP. Each adapter has a
device-native side and a nominally duplex media side. The included adapter
uses GStreamer for RTSP camera audio and Baresip for its internal RTP/SIP leg;
SIP is only an adapter implementation detail here. Future SIP phones can use
FreeSWITCH directly.

## Discovered targets (2026-08-08)

| Device | Address/interface | PoC role |
| --- | --- | --- |
| Room A camera | `192.0.2.21`, RTSP, ONVIF on 2020 | microphone-only source through Frigate's local go2rtc restream |
| Room B camera | `192.0.2.22`, RTSP, ONVIF on 2020 | second microphone-only source |
| Reolink doorbell | `192.0.2.23`, RTSP | candidate two-way adapter; talk protocol is vendor-specific and not part of this first adapter |
| Home Assistant Voice PE | `192.0.2.20`, ESPHome/Home Assistant | future duplex adapter target; stock firmware is not a general SIP endpoint |
| Amazon Echo | `192.0.2.24`, Alexa integration | future speaker sink only; excluded from the offline core because normal control depends on Amazon services |

The deterministic PoC participants are two synthetic duplex adapters, one
speaker-only capture adapter, and the real RTSP camera microphone. This proves
the conference and adapter boundary without claiming unsupported native
interfaces on the Voice PE or Echo.

## Run

The Portainer stack is [`../stacks/intercom.yaml`](../stacks/intercom.yaml).
It publishes only the controller on loopback (`127.0.0.1:8099`). FreeSWITCH,
SIP, and RTP stay on the internal Docker network for this unauthenticated PoC.

```sh
export INTERCOM_ESL_PASSWORD="$(openssl rand -hex 24)"
docker compose -f stacks/intercom.yaml config
docker compose -f stacks/intercom.yaml up -d --build
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
./intercom/scripts/connect-lab-clients.sh
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
./intercom/scripts/disconnect-lab-clients.sh
```

The `voice-pe` adapter runs on the host network. Received conference audio stays
lossless: Pulse PCM is resampled into a local WAV FIFO and Sendspin negotiates
PCM or FLAC with the physical player. An opt-in microphone bridge is prepared
under [`voice-pe-esphome`](voice-pe-esphome/README.md), but the live participant
remains receive-only until that firmware and its dedicated token are installed
and verified on the Docker host. Music Assistant and Home Assistant media playback
are not in the intercom audio path.

An ordinary SIP softphone can eventually use extension `9000` and join the same
on-demand `intercom` conference once a secured SIP profile is intentionally
published on the LAN. The fail-closed profile initially mutes and deafens every
new member, so the application layer must identify and enable an unmanaged
phone before it carries audio. The conference disappears when its final member
leaves.

## Semantics

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
and a later trunk. An inbound trunk call can be placed into `intercom@wideband`
and house devices can join the same room. Nothing in the controller assumes
that a session contains only adapter-originated calls.
