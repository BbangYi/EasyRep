from uuid import uuid4

import pytest
from habitat_gateway.config import load_settings
from habitat_gateway.gateway import Gateway, Conflict
from habitat_gateway.models import CommandRequest
from habitat_gateway.transport import SimulatedTransport
from habitat_gateway.cloud import CloudSync
from habitat_gateway.sync_contract import SyncRequest


def test_planned_mist_slots_preserve_v1_contract_but_cannot_turn_on():
    settings = load_settings("configs/examples/reptile-city.toml").model_copy(update={
        "database": ":memory:", "transport": "simulated"})
    transport = SimulatedTransport(settings)
    gateway = Gateway(settings, transport)
    try:
        transport.start(gateway)
        for cage in settings.cages:
            result = gateway.send_command(cage.id, CommandRequest(request_id=uuid4(), actuator_id="mister",
                                                                 action="on", duration_s=2))
            assert result["status"] == "rejected" and result["reason"] == "hardware_not_commissioned"
            with pytest.raises(Conflict, match="hardware_not_commissioned"):
                gateway.set_mode(cage.id, "auto")
        assert transport.sent == []
        wire = CloudSync(gateway, None)._prepare()
        assert len(SyncRequest.model_validate(wire).gateway.cages) == 3
        assert all(len(c["configuration"]["actuators"]) >= 1 for c in wire["gateway"]["cages"])
    finally:
        gateway.store.close()
