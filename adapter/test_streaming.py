import shutil
import struct
import subprocess
import unittest

from streaming import STREAM_CONTENT_TYPES, flac_encoder_command


class StreamingTest(unittest.TestCase):
    def test_voice_pe_stream_has_flac_content_type(self):
        self.assertEqual(STREAM_CONTENT_TYPES["/stream.flac"], "audio/flac")

    def test_flac_encoder_is_low_latency_48khz_stereo(self):
        command = flac_encoder_command()
        self.assertIn("-flush_packets", command)
        self.assertEqual(command[command.index("-compression_level") + 1], "0")
        self.assertEqual(command[-4:], ["1", "-f", "flac", "pipe:1"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
    def test_flac_encoder_accepts_streaming_pcm(self):
        samples = [12000 if index % 24 < 12 else -12000 for index in range(3200)]
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        encoded = subprocess.run(
            flac_encoder_command(), input=pcm, capture_output=True, check=True
        ).stdout
        self.assertTrue(encoded.startswith(b"fLaC"))


if __name__ == "__main__":
    unittest.main()
