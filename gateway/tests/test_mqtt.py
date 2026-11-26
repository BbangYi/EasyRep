import json
from types import SimpleNamespace
from unittest.mock import Mock

import paho.mqtt.client as mqtt
import pytest

from habitat_gateway.transport import MQTTTransport, node_topic


def test_mqtt_qos_expiry_nonretained_and_routing(settings, monkeypatch):
    monkeypatch.setenv("HABITAT_MQTT_PASSWORD", "test-only")
    transport = MQTTTransport(settings)
    transport.client = Mock()
    transport.client.publish.return_value = SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)
    transport.gateway = Mock()
    transport._connect(transport.client, None, None, SimpleNamespace(is_failure=False), None)
    assert transport.connected
    topics = transport.client.subscribe.call_args.args[0]
    assert all(topic.startswith("habitat/v1/STORE-001/cages/CAGE-001/nodes/ESP32-001/") and qos == 1 for topic, qos in topics)
    transport.publish("CAGE-001", {"command_id": "test"})
    call = transport.client.publish.call_args
    assert call.args[0] == node_topic(settings, settings.cages[0], "command")
    assert json.loads(call.args[1]) == {"command_id": "test"}
    assert call.kwargs["qos"] == 1
    assert call.kwargs["retain"] is False
    assert call.kwargs["properties"].MessageExpiryInterval == settings.command_ttl_s
    transport._message(None, None, SimpleNamespace(topic="other/site/topic", payload=b"{}"))
    transport.gateway.ingest.assert_not_called()
    transport._disconnect(None, None, None, None, None)
    with pytest.raises(ConnectionError):
        transport.publish("CAGE-001", {})


def test_malformed_mqtt_packet_does_not_terminate_callback(settings, monkeypatch):
    monkeypatch.setenv("HABITAT_MQTT_PASSWORD", "test-only")
    transport = MQTTTransport(settings)
    transport.gateway = Mock()
    topic = node_topic(settings, settings.cages[0], "telemetry")
    for payload in (b"not-json", b"[]", b"{}", b"x" * 65537):
        transport._message(None, None, SimpleNamespace(topic=topic, payload=payload, retain=False))
    transport.gateway.ingest.assert_not_called()
