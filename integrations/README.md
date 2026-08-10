# Integrations

Each integration implements the generic `AudioSource` and `Integration`
interfaces from [`core/interfaces.py`](../core/interfaces.py). Importable
implementations live in `intercom_integrations/`; the directories here contain
container entry points and device-specific assets. Integrations may provide a
source, a sink-facing stream, or both; the core does not retain their device
configuration.

- `synthetic/` provides sine and silence sources for tests and demos.
- `rtsp-camera/` provides a GStreamer-backed RTSP camera source.
- `voice-pe/` provides the Voice PE adapter and its optional microphone
  firmware. The adapter is speaker-only unless microphone mode is explicitly
  enabled with deployment configuration.
