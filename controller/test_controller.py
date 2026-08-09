import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("INTERCOM_ESL_PASSWORD", "test-only")
os.environ.setdefault("DEVICES_FILE", str(Path(__file__).with_name("devices.json")))
spec = importlib.util.spec_from_file_location("controller", Path(__file__).with_name("controller.py"))
controller = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(controller)


class FakeESL:
    commands = []

    def api(self, command):
        self.commands.append(command)
        return "+OK"


class RoutingTests(unittest.TestCase):
    def setUp(self):
        FakeESL.commands = []

    @patch.object(controller, "member_map", return_value={"lab-a": 1, "lab-b": 2})
    @patch.object(controller, "ESL", FakeESL)
    def test_directional_route_uses_source_to_sink_relationship(self, _members):
        controller.set_route("lab-a", "lab-b", False)
        self.assertEqual(FakeESL.commands, ["conference intercom relate 1 2 nospeak"])

    @patch.object(controller, "member_map", return_value={"lab-a": 1, "lab-b": 2})
    @patch.object(controller, "ESL", FakeESL)
    def test_enabled_route_clears_only_that_relationship(self, _members):
        controller.set_route("lab-a", "lab-b", True)
        self.assertEqual(FakeESL.commands, ["conference intercom relate 1 2 clear"])

    @patch.object(controller, "member_map", return_value={"lab-speaker": 3, "lab-a": 1})
    def test_speaker_cannot_be_route_source(self, _members):
        with self.assertRaisesRegex(controller.Error, "no transmit"):
            controller.set_route("lab-speaker", "lab-a", True)

    @patch.object(controller, "member_map", return_value={"room-a-camera": 4, "lab-a": 1})
    def test_camera_cannot_be_route_sink(self, _members):
        with self.assertRaisesRegex(controller.Error, "no receive"):
            controller.set_route("lab-a", "room-a-camera", True)


class ESLParsingTests(unittest.TestCase):
    def test_frame_reads_content_length(self):
        import io

        headers, body = controller.ESL._frame(io.BytesIO(b"Content-Type: api/response\nContent-Length: 5\n\nhello"))
        self.assertEqual(headers["content-type"], "api/response")
        self.assertEqual(body, b"hello")


if __name__ == "__main__":
    unittest.main()
