# Local intercom proof of concept

This directory contains a deliberately small FreeSWITCH intercom proof of
concept. FreeSWITCH and `mod_conference` remain the media engine. The Python
control service owns device identity and translates a directional routing
matrix into conference member controls.

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

Connect two duplex test adapters:

```sh
curl -fsS -X POST http://127.0.0.1:8099/devices/lab-a/connect
curl -fsS -X POST http://127.0.0.1:8099/devices/lab-b/connect
curl -fsS http://127.0.0.1:8099/session | jq
```

Enable both directions:

```sh
curl -fsS -X PUT -H 'Content-Type: application/json' \
  -d '{"enabled":true}' http://127.0.0.1:8099/routes/lab-a/lab-b
curl -fsS -X PUT -H 'Content-Type: application/json' \
  -d '{"enabled":true}' http://127.0.0.1:8099/routes/lab-b/lab-a
```

The first path below connects a real camera microphone to the speaker-only
capture adapter. Its received audio is kept in three rotating WAV segments in
the `intercom_sink_captures` volume.

```sh
curl -fsS -X POST http://127.0.0.1:8099/devices/room-a-camera/connect
curl -fsS -X POST http://127.0.0.1:8099/devices/lab-speaker/connect
curl -fsS -X PUT -H 'Content-Type: application/json' \
  -d '{"enabled":true}' \
  http://127.0.0.1:8099/routes/room-a-camera/lab-speaker
```

Disconnects are authoritative and require no action at the physical device:

```sh
curl -fsS -X DELETE http://127.0.0.1:8099/devices/room-a-camera/connect
```

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
- Device names, capabilities, and adapter URLs live in `devices.json`, above
  the media layer.
- The API starts from deny-by-default relationships when a participant joins;
  callers must explicitly enable desired directions.

Echo cancellation, authentication of the local HTTP API, encryption, and
provisioning remain intentionally out of scope. The API is therefore bound to
loopback and must not be exposed through Traefik.

## Telephone evolution

The internal FreeSWITCH SIP profile remains available for registered phones
and a later trunk. An inbound trunk call can be placed into `intercom@wideband`
and house devices can join the same room. Nothing in the controller assumes
that a session contains only adapter-originated calls.
