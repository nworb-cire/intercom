import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from music_assistant import MusicAssistantError, MusicAssistantSink, pcm_peak, wav_header


class FakeApiHandler(BaseHTTPRequestHandler):
    requests = []
    status = 200

    def log_message(self, _format, *_args):
        return

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.requests.append((self.path, self.headers["Authorization"], json.loads(body)))
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"null")


class MusicAssistantSinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApiHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeApiHandler.requests = []
        FakeApiHandler.status = 200
        self.tempdir = tempfile.TemporaryDirectory()
        self.token_file = Path(self.tempdir.name) / "token"
        self.token_file.write_text("test-token-that-is-deliberately-long-enough")
        self.sink = MusicAssistantSink(
            f"http://127.0.0.1:{self.server.server_port}",
            self.token_file,
            "voice-player",
            "http://intercom:8088/stream.wav",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_play_uses_bearer_token_and_live_url(self):
        self.sink.play()
        self.assertEqual(FakeApiHandler.requests, [(
            "/api",
            "Bearer test-token-that-is-deliberately-long-enough",
            {
                "command": "player_queues/play_media",
                "args": {
                    "queue_id": "voice-player",
                    "media": "http://intercom:8088/stream.wav",
                },
            },
        )])

    def test_stop_targets_the_same_player(self):
        self.sink.stop()
        self.assertEqual(FakeApiHandler.requests[0][2], {
            "command": "player_queues/stop",
            "args": {"queue_id": "voice-player"},
        })

    def test_http_errors_do_not_include_response_or_token(self):
        FakeApiHandler.status = 401
        with self.assertRaisesRegex(MusicAssistantError, "HTTP 401") as error:
            self.sink.play()
        self.assertNotIn("test-token", str(error.exception))

    def test_streaming_wav_header_describes_16khz_mono_pcm(self):
        header = wav_header()
        self.assertEqual(len(header), 44)
        self.assertEqual(header[:4], b"RIFF")
        self.assertEqual(header[8:16], b"WAVEfmt ")
        self.assertEqual(header[36:40], b"data")

    def test_pcm_peak_handles_signed_samples_and_partial_tail(self):
        self.assertEqual(pcm_peak(b"\x00\x00\x00\x80\xff"), 32768)


if __name__ == "__main__":
    unittest.main()
