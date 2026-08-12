# Core

The core contains the stateless control plane and the shared media runtime. It
is intentionally unaware of concrete devices.

- `controller/` exposes the application-facing HTTP API and translates
  call-scoped connection, capability, gain, and route operations into
  FreeSWITCH commands. Calls (also exposed as rooms) are application-named,
  isolated conferences; the controller intentionally retains no registry.
- `freeswitch/` contains the conference, SIP, event-socket, and dialplan
  configuration.
- `adapter_runtime/` contains the reusable Python adapter process and the
  `AudioSource`, `StreamEncoder`, `AudioSink`, and `Integration` contracts from
  [`interfaces.py`](interfaces.py).

An integration supplies an `AudioSource` implementation. The runtime provides
the common Baresip leg, PulseAudio sink, `/connect`, `/health`, and
`/stream.flac` behavior.
