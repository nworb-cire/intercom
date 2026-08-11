import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("INTERCOM_ESL_PASSWORD", "test-only")
spec = importlib.util.spec_from_file_location("controller", Path(__file__).with_name("controller.py"))
controller = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = controller
spec.loader.exec_module(controller)


class FakeESL:
    commands = []

    def api(self, command):
        self.commands.append(command)
        return "+OK"


LAB_A = controller.Endpoint("lab-a", "http://lab-a:8080", True, True)
LAB_B = controller.Endpoint("lab-b", "http://lab-b:8080", True, True)


class EndpointTests(unittest.TestCase):
    def test_accepts_stateless_endpoint_descriptor(self):
        endpoint = controller.endpoint_from_body({
            "device_id": "lab-a",
            "adapter_url": "http://lab-a:8080/",
            "can_transmit": True,
            "can_receive": False,
        })
        self.assertEqual(endpoint, controller.Endpoint("lab-a", "http://lab-a:8080", True, False))

    def test_accepts_optional_application_owned_gain_settings(self):
        endpoint = controller.endpoint_from_body({
            "device_id": "lab-a",
            "adapter_url": "http://lab-a:8080",
            "can_transmit": True,
            "can_receive": False,
            "gain": {"input_level": 4, "output_level": -2, "agc_target": 1000},
        })
        self.assertEqual(endpoint.gain, controller.GainSettings(4, -2, 1000))

    def test_rejects_invalid_gain_settings(self):
        body = {
            "device_id": "lab-a",
            "adapter_url": "http://lab-a:8080",
            "can_transmit": True,
            "can_receive": True,
            "gain": {"input_level": 5},
        }
        with self.assertRaisesRegex(controller.ValidationError, "input_level"):
            controller.endpoint_from_body(body)
        body["gain"] = {"agc_target": 0}
        with self.assertRaisesRegex(controller.ValidationError, "agc_target"):
            controller.endpoint_from_body(body)
        body["gain"] = {"output_level": True}
        with self.assertRaisesRegex(controller.ValidationError, "output_level"):
            controller.endpoint_from_body(body)

    def test_rejects_adapter_url_with_credentials_or_path(self):
        body = {
            "device_id": "lab-a",
            "adapter_url": "http://user:password@lab-a:8080/private",
            "can_transmit": True,
            "can_receive": True,
        }
        with self.assertRaisesRegex(controller.ValidationError, "adapter_url"):
            controller.endpoint_from_body(body)

    def test_accepts_null_adapter_for_an_already_joined_device(self):
        endpoint = controller.endpoint_from_body({
            "device_id": "sip-phone",
            "adapter_url": None,
            "can_transmit": True,
            "can_receive": True,
        })
        self.assertEqual(endpoint, controller.Endpoint("sip-phone", None, True, True))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        FakeESL.commands = []

    @patch.object(controller, "session", return_value={"members": [
        {"device_id": "lab-a", "member_id": 1}, {"device_id": "lab-b", "member_id": 2}
    ]})
    @patch.object(controller, "ESL", FakeESL)
    def test_directional_route_uses_source_to_sink_relationship(self, _session):
        controller.set_route("lab-a", "lab-b", False)
        self.assertEqual(FakeESL.commands, ["conference intercom relate 1 2 nospeak"])

    @patch.object(controller, "session", return_value={"members": [
        {"device_id": "lab-a", "member_id": 1}, {"device_id": "lab-b", "member_id": 2}
    ]})
    @patch.object(controller, "ESL", FakeESL)
    def test_enabled_route_clears_only_that_relationship(self, _session):
        controller.set_route("lab-a", "lab-b", True)
        self.assertEqual(FakeESL.commands, ["conference intercom relate 1 2 clear"])

    @patch.object(controller, "session", return_value={"members": [
        {"device_id": "lab-a", "member_id": 1}, {"device_id": "lab-a", "member_id": 2}
    ]})
    def test_duplicate_device_identity_is_rejected(self, _session):
        with self.assertRaisesRegex(controller.Error, "multiple conference members"):
            controller.member_for_device("lab-a")


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        FakeESL.commands = []

    @patch.object(controller, "session", return_value={"members": [
        {"device_id": "lab-a", "member_id": 1}, {"device_id": "lab-b", "member_id": 2}
    ]})
    @patch.object(controller, "ESL", FakeESL)
    def test_reauthorizes_existing_member_and_reasserts_adapter_state(self, _session):
        with patch.object(controller, "adapter_request") as adapter_request:
            controller.connect(LAB_A)
        adapter_request.assert_called_once_with("http://lab-a:8080", "POST")
        self.assertEqual(FakeESL.commands, [
            "conference intercom relate 1 2 nospeak",
            "conference intercom relate 2 1 nospeak",
            "conference intercom unmute 1 quiet",
            "conference intercom undeaf 1",
        ])

    @patch.object(controller, "session", return_value={"members": [
        {"device_id": "lab-a", "member_id": 1}, {"device_id": "lab-b", "member_id": 2}
    ]})
    @patch.object(controller, "ESL", FakeESL)
    @patch.object(controller, "adapter_request")
    def test_applies_requested_gain_on_each_connection(self, adapter_request, _session):
        endpoint = controller.Endpoint(
            "lab-a", "http://lab-a:8080", True, True, controller.GainSettings(4, -1, 1000)
        )
        controller.connect(endpoint)
        adapter_request.assert_called_once_with("http://lab-a:8080", "POST")
        self.assertEqual(FakeESL.commands[-3:], [
            "conference intercom volume_in 1 4",
            "conference intercom volume_out 1 -1",
            "conference intercom agc 1 1000",
        ])

    @patch.object(controller, "member_for_device", return_value=None)
    def test_requires_an_adapter_to_connect_a_missing_member(self, _member):
        with self.assertRaisesRegex(controller.Error, "adapter_url is required"):
            controller.connect(controller.Endpoint("sip-phone", None, True, True))


class ESLParsingTests(unittest.TestCase):
    def test_frame_reads_content_length(self):
        import io

        headers, body = controller.ESL._frame(io.BytesIO(b"Content-Type: api/response\nContent-Length: 5\n\nhello"))
        self.assertEqual(headers["content-type"], "api/response")
        self.assertEqual(body, b"hello")


if __name__ == "__main__":
    unittest.main()
