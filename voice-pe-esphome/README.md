# Voice PE intercom firmware

The stock Home Assistant Voice Preview Edition firmware has no microphone
entity, RTSP endpoint, or general-purpose audio output. It sends microphone
audio only to the one native-API client that owns its Assist pipeline. Trying
to become a second voice-assistant API client would disconnect or compete with
Home Assistant.

The custom image in `home-assistant-voice-intercom.yaml` pins the official Voice
PE firmware source, retains its native speaker/media-player pipeline, reduces
the interactive HTTP media buffer, and adds a passive `MicrophoneSource`
consumer. The wake-word and Assist components continue to own microphone
start/stop behavior. The bridge sees the same post-XMOS, 16 kHz microphone
channel and emits headerless signed 16-bit little-endian PCM over UDP only while
an authenticated subscriber renews a five-second lease.

## Install

1. Run ESPHome on the Docker host; an ephemeral
   `ghcr.io/esphome/esphome:2026.6.0` container is sufficient.
2. Copy this directory to the builder host without its ignored `secrets.yaml`.
3. Recover the current native-API encryption key from Home Assistant's ESPHome
   config entry, generate a dedicated microphone token, and put both in the
   builder's untracked `secrets.yaml`:
   `secrets.yaml`:

   ```yaml
   intercom_microphone_token: "use-a-random-value-of-at-least-24-characters"
   api_encryption_key: "reuse-the-existing-voice-pe-native-api-key"
   ```

4. Validate, compile, and upload `home-assistant-voice-intercom.yaml`. Preserve
   a hash-verified official factory image and a stock OTA image before upload.
5. Put the exact same canonical microphone token in the
   Portainer intercom stack as `VOICE_PE_INTERCOM_TOKEN`; do not commit it.
6. Redeploy only after capturing the existing Portainer stack configuration and
   confirming its Git update operation preserves all environment values.

After the firmware is verified, change the Docker host's `voice-pe` service to
`SOURCE_KIND: udp-pcm` and supply `UDP_REMOTE_HOST=192.0.2.20`,
`UDP_REMOTE_PORT=18555`, and `UDP_TOKEN` from the Portainer environment. Then
have the application include `"can_transmit": true` in its Voice PE connection
request to the stateless intercom controller.

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

For direct speaker playback, have the application play the adapter's
`http://192.0.2.10:8088/stream.flac` URL through the Voice PE's native ESPHome
media-player entity. The adapter converts conference PCM to the 48 kHz stereo
FLAC format accepted by the stock speaker pipeline.
