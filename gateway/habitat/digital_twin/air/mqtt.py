"""Receive-only adapter from the gateway's MQTT contract to the air display."""
from collections import OrderedDict
import json
import logging
import os
from uuid import uuid4

import paho.mqtt.client as mqtt

from habitat_gateway.models import utcnow
from habitat_gateway.transport import node_topic
from .telemetry import validate_telemetry

logger = logging.getLogger(__name__)


class AirSubscriber:
    def __init__(self, settings, cage, state, client=None, *, now=utcnow):
        self.settings, self.cage, self.state, self.now = settings, cage, state, now
        self.connected = False
        self.seen = OrderedDict()
        self.topics = {node_topic(settings, cage, kind): kind for kind in ('telemetry', 'status')}
        self.sensors = {sensor.id: sensor for sensor in cage.sensors}
        if any(key not in self.sensors or self.sensors[key].unit != 'degC' for key in ('T1', 'T2', 'T3')):
            raise ValueError('air_view_requires_three_temperature_sensors')
        password = os.environ.get(settings.mqtt.password_env)
        if not password:
            raise ValueError('air_view_mqtt_credential_missing')
        self.client = client if client is not None else mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f'air-{uuid4().hex}', protocol=mqtt.MQTTv311)
        self.client.username_pw_set(settings.mqtt.username, password)
        if settings.mqtt.tls_ca:
            self.client.tls_set(ca_certs=settings.mqtt.tls_ca)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._connect
        self.client.on_disconnect = self._disconnect
        self.client.on_message = self._message

    def start(self):
        self.client.connect_async(self.settings.mqtt.host, self.settings.mqtt.port, keepalive=30)
        self.client.loop_start()

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()

    def _connect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = not reason_code.is_failure
        if self.connected:
            client.subscribe([(topic, 1) for topic in self.topics])
            self.state.mark('held' if self.seen else 'waiting', 'mqtt_connected_waiting_for_telemetry')
            logger.info('Air viewer MQTT connected cage=%s', self.cage.id)
        else:
            self.state.mark('offline', 'mqtt_connection_rejected')
            logger.warning('Air viewer MQTT connection rejected')

    def _disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = False
        self.state.mark('offline', 'mqtt_disconnected')

    def _message(self, client, userdata, message):
        kind = self.topics.get(message.topic)
        if kind is None:
            return
        if message.retain:
            if kind == 'telemetry':
                self.state.mark('held', 'retained_telemetry_ignored')
            return
        try:
            if len(message.payload) > 65536:
                raise ValueError('oversized_payload')
            raw = json.loads(message.payload)
            if not isinstance(raw, dict):
                raise ValueError('invalid_payload')
            if kind == 'status':
                if type(raw.get('online')) is not bool:
                    raise ValueError('invalid_status')
                self.state.ingest(dict(event='status', retained=False, online=raw['online']), now=self.now())
                return
            now = self.now()
            sample = validate_telemetry(raw, self.cage, now, self.state.max_future_skew)
            key = str(sample.message_id)
            if key in self.seen:
                # A QoS redelivery must not grey a fresh, already accepted field.
                return
            payload = sample.model_dump(mode='json')
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            # Validation exceptions may contain full input; never log their contents.
            self.state.mark('held', 'invalid_sensor_message')
            return
        try:
            accepted = self.state.ingest(dict(event='telemetry', retained=False, fresh_unique=True,
                message_id=key, sampled_at=payload['sampled_at'], readings=payload['readings'], payload=payload), now=now)
        except Exception:
            self.state.mark('held', 'air_model_update_failed')
            logger.error('Air model update failed; receiver remains active')
            return
        if accepted:
            if not self.seen:
                logger.info('Air viewer first measurement cage=%s message_id=%s', self.cage.id, key)
            self.seen[key] = None
            if len(self.seen) > 4096:
                self.seen.popitem(last=False)
