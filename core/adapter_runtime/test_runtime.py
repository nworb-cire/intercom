import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.adapter_runtime.runtime import AdapterRuntime, RuntimeConfig


class FakeSource:
    kind = "fake"
    baresip_source = "ausine,440"
    baresip_modules = ("stdio.so",)

    def prepare(self, _config_dir: Path) -> None:
        return

    def start(self, _connected) -> None:
        return

    def stop(self) -> None:
        return


class FakeIntegration:
    name = "fake"
    source = FakeSource()
    sink = None

    def __init__(self):
        self.stop_count = 0

    def health(self):
        return {"fake_ready": True}

    def prepare(self, config_dir):
        self.source.prepare(config_dir)

    def start(self, connected):
        self.source.start(connected)

    def stop(self):
        self.stop_count += 1
        self.source.stop()


class AdapterRuntimeTests(unittest.TestCase):
    def test_source_contract_controls_baresip_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            config = RuntimeConfig("test-device", "sip:9000@freeswitch:5070", 8080, False, Path(directory))
            runtime = AdapterRuntime(FakeIntegration(), config)
            with patch.object(runtime, "media_ip", return_value="172.30.0.3"):
                runtime.write_baresip_config()
            self.assertIn("audio_source ausine,440", (Path(directory) / "config").read_text())
            self.assertIn('"test-device" <sip:test-device@127.0.0.1', (Path(directory) / "accounts").read_text())

    def test_health_reports_source_and_stream_state(self):
        config = RuntimeConfig("test-device", "sip:9000@freeswitch:5070", 8080, False, Path("/tmp"))
        runtime = AdapterRuntime(FakeIntegration(), config)
        health = runtime.health()
        self.assertEqual(health["source_kind"], "fake")
        self.assertFalse(health["connected"])
        self.assertEqual(health["stream_clients"], 0)
        self.assertTrue(health["fake_ready"])

    def test_shutdown_stops_integration_once(self):
        integration = FakeIntegration()
        runtime = AdapterRuntime(integration, RuntimeConfig("test-device", "sip:9000@freeswitch:5070", 8080, False, Path("/tmp")))
        runtime.shutdown()
        runtime.shutdown()
        self.assertEqual(integration.stop_count, 1)

    def test_baresip_is_supervised_as_a_fatal_child(self):
        runtime = AdapterRuntime(
            FakeIntegration(),
            RuntimeConfig("test-device", "sip:9000@freeswitch:5070", 8080, False, Path("/tmp")),
        )
        baresip = MagicMock()
        with (
            patch.object(runtime, "write_baresip_config"),
            patch.object(runtime, "start_pulse"),
            patch("core.adapter_runtime.runtime.subprocess.Popen", return_value=baresip),
            patch("core.adapter_runtime.runtime.threading.Thread") as thread,
        ):
            runtime.start_processes()
        self.assertTrue(any(
            call.kwargs.get("target") == runtime.watch_child
            and call.kwargs.get("args") == ("baresip", baresip)
            for call in thread.call_args_list
        ))

    def test_child_exit_is_ignored_during_shutdown(self):
        runtime = AdapterRuntime(
            FakeIntegration(),
            RuntimeConfig("test-device", "sip:9000@freeswitch:5070", 8080, False, Path("/tmp")),
        )
        child = MagicMock()
        child.wait.return_value = 0
        runtime.shutdown_event.set()
        with patch("core.adapter_runtime.runtime.os._exit") as exit_process:
            runtime.watch_child("baresip", child)
        exit_process.assert_not_called()

    def test_unexpected_child_exit_terminates_adapter_process(self):
        runtime = AdapterRuntime(
            FakeIntegration(),
            RuntimeConfig("test-device", "sip:9000@freeswitch:5070", 8080, False, Path("/tmp")),
        )
        child = MagicMock()
        child.wait.return_value = 3
        with patch("core.adapter_runtime.runtime.os._exit") as exit_process:
            runtime.watch_child("baresip", child)
        exit_process.assert_called_once_with(3)


if __name__ == "__main__":
    unittest.main()
