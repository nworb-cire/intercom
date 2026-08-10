import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.adapter_runtime.runtime import AdapterRuntime, RuntimeConfig


class FakeSource:
    kind = "fake"
    baresip_source = "ausine,440"

    def prepare(self, _config_dir: Path) -> None:
        return

    def start(self, _connected) -> None:
        return

    def stop(self) -> None:
        return


class AdapterRuntimeTests(unittest.TestCase):
    def test_source_contract_controls_baresip_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            config = RuntimeConfig("test-device", "sip:9000@freeswitch:5070", 8080, False, Path(directory))
            runtime = AdapterRuntime(FakeSource(), config)
            with patch.object(runtime, "media_ip", return_value="172.30.0.3"):
                runtime.write_baresip_config()
            self.assertIn("audio_source ausine,440", (Path(directory) / "config").read_text())
            self.assertIn('"test-device" <sip:test-device@127.0.0.1', (Path(directory) / "accounts").read_text())

    def test_health_reports_source_and_stream_state(self):
        config = RuntimeConfig("test-device", "sip:9000@freeswitch:5070", 8080, False, Path("/tmp"))
        runtime = AdapterRuntime(FakeSource(), config)
        health = runtime.health()
        self.assertEqual(health["source_kind"], "fake")
        self.assertFalse(health["connected"])
        self.assertEqual(health["stream_clients"], 0)


if __name__ == "__main__":
    unittest.main()
