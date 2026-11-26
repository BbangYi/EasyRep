from datetime import datetime, timedelta, timezone

import pytest

from habitat_gateway.config import load_settings
from habitat_gateway.gateway import Gateway
from habitat_gateway.transport import SimulatedTransport


def confirm_empty_cloud(store):
    """Test setup only: each fixture owns an empty isolated receiver, never a real registration."""
    store.confirm_cloud_continuity({"site_id": store.event_identity[0], "gateway_id": store.event_identity[1],
        "server_high_watermark": 0, "verified_at": store.now().isoformat(),
        "method": "isolated_test_receiver", "evidence_ref": "new empty test receiver", "exclusive_writer": True})


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 18, 0, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def settings():
    return load_settings("config/simulation.toml").model_copy(update={"database": ":memory:"})


@pytest.fixture
def rig(settings):
    clock = Clock()
    transport = SimulatedTransport(settings, now=clock)
    gateway = Gateway(settings, transport, now=clock)
    transport.start(gateway)
    yield gateway, transport, clock
    gateway.store.close()
