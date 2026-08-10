# Home Assistant Voice PE integration

The Python adapter uses the shared core runtime and exposes the live
`/stream.flac` sink for direct native Voice PE playback. Set
`VOICE_PE_MICROPHONE=true` with the UDP settings to enable the optional custom
firmware microphone source.

The firmware build and upload instructions are in
[firmware/README.md](firmware/README.md).
