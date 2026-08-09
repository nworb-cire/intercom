# Voice PE microphone bridge

The stock Home Assistant Voice Preview Edition firmware has no microphone
entity, RTSP endpoint, or general-purpose audio output. It sends microphone
audio only to the one native-API client that owns its Assist pipeline. Trying
to become a second voice-assistant API client would disconnect or compete with
Home Assistant.

This package instead adds a passive `MicrophoneSource` consumer to the official
firmware. The wake-word and Assist components continue to own microphone
start/stop behavior. The bridge sees the same post-XMOS, 16 kHz microphone
channel and emits headerless signed 16-bit little-endian PCM over UDP only while
an authenticated subscriber renews a five-second lease.

## Install

1. Take control of the Voice PE in ESPHome Device Builder if it is still using
   factory-managed firmware. Run the builder on the Docker host (an ephemeral
   `ghcr.io/esphome/esphome` container is sufficient); do not build or host this
   service on a workstation.
2. Copy `components/udp_microphone` and `voice-pe-intercom.yaml` beside the
   device YAML. If the package is placed in a subdirectory, adjust the local
   `external_components` path accordingly.
3. Generate a dedicated token and put it in the builder's untracked
   `secrets.yaml`:

   ```yaml
   intercom_microphone_token: "use-a-random-value-of-at-least-24-characters"
   ```

4. Include the package from the device configuration:

   ```yaml
   packages:
     intercom: !include voice-pe-intercom.yaml
   ```

5. Compile and install the firmware. Put the exact same canonical token in the
   Portainer intercom stack as `VOICE_PE_INTERCOM_TOKEN`; do not commit it.
6. Redeploy only after capturing the existing Portainer stack configuration and
   confirming its Git update operation preserves all environment values.

After the firmware is verified, change the Docker host's `voice-pe` service to
`SOURCE_KIND: udp-pcm` and supply `UDP_REMOTE_HOST=192.0.2.20`,
`UDP_REMOTE_PORT=18555`, and `UDP_TOKEN` from the Portainer environment. Only
then mark the device `can_transmit: true` in `controller/devices.json`.

The component binds UDP port `18555` on the Voice PE. A valid `START <token>`
datagram leases the stream to that sender's address and source port. Renewals
extend the lease; `STOP <token>` or five seconds without a renewal stops network
audio. The physical mute switch still acts below this bridge.

## Verification

- Confirm the Voice PE reconnects to ESPHome and normal wake-word/Assist use
  still works before enabling an intercom route.
- Connect `voice-pe` through the intercom controller and confirm its adapter
  health reports `source_kind: udp-pcm`.
- Route `voice-pe` to `lab-speaker` and inspect a rotating capture for intelligible
  speech.
- Disconnect `voice-pe`, wait more than five seconds, and confirm UDP audio from
  the Voice PE stops.
- Check recent Voice PE, adapter, FreeSWITCH, and controller logs for errors.

This is a LAN protocol with a bearer token, not encrypted transport. It should
remain confined to the trusted network.
