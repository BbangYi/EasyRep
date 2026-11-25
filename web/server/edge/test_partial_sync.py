"""Regression coverage for retired cages remaining in a Pi's outbound snapshot."""

import copy
import uuid

from habitat.models import Enclosure

from edge.models import Binding, CurrentState, Event, Measurement
from edge.tests import EdgeTests


class PartialSyncTests(EdgeTests):
    def test_retired_snapshot_does_not_block_bound_cage_measurement(self):
        """Retired events clear the Pi queue without entering the site database."""
        Binding.objects.filter(enclosure=self.cage).delete()
        self.gateway.snapshot = {
            "cages": [copy.deepcopy(self.body["gateway"]["cages"][0])]
        }
        self.gateway.save(update_fields=["snapshot"])
        active = Enclosure.objects.create(
            id="active-cage",
            name="현재 사육장",
            store=self.store,
            edge_cage_id="CAGE-002",
        )
        Binding.objects.create(gateway=self.gateway, enclosure=active)

        active_snapshot = copy.deepcopy(self.body["gateway"]["cages"][0])
        active_snapshot["configuration"].update(id="CAGE-002", node_id="ESP32-002")
        active_snapshot["state"].update(cage_id="CAGE-002", node_id="ESP32-002")
        active_snapshot["state"]["telemetry"]["message_id"] = str(uuid.uuid4())
        self.body["gateway"]["cages"].append(active_snapshot)

        retired_event = copy.deepcopy(self.body["events"][0])
        active_event = copy.deepcopy(retired_event)
        active_event.update(event_id=str(uuid.uuid4()), event_sequence=2, cage_id="CAGE-002")
        active_event["payload"]["message_id"] = str(uuid.uuid4())
        self.body["events"] = [retired_event, active_event]

        response = self.send()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()["accepted_event_ids"],
            [retired_event["event_id"], active_event["event_id"]],
        )
        self.assertEqual(
            set(Event.objects.filter(enclosure=active).values_list("enclosure_id", flat=True)),
            {active.pk},
        )
        self.assertEqual(
            set(
                Measurement.objects.filter(enclosure=active).values_list(
                    "enclosure_id", flat=True
                )
            ),
            {active.pk},
        )
        self.assertEqual(
            CurrentState.objects.get(enclosure=active).enclosure_id,
            active.pk,
        )
        self.assertEqual(
            self.gateway.__class__.objects.get(pk=self.gateway.pk).snapshot["cages"][0]["configuration"]["id"],
            "CAGE-002",
        )

    def test_retired_only_batch_is_acknowledged_without_storage(self):
        """A retired queue head must not prevent newer registered telemetry."""
        Binding.objects.filter(enclosure=self.cage).delete()
        self.gateway.snapshot = {
            "cages": [copy.deepcopy(self.body["gateway"]["cages"][0])]
        }
        self.gateway.save(update_fields=["snapshot"])

        response = self.send()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()["accepted_event_ids"],
            [event["event_id"] for event in self.body["events"]],
        )
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(Measurement.objects.count(), 0)
        self.assertEqual(CurrentState.objects.count(), 0)
        gateway = self.gateway.__class__.objects.get(pk=self.gateway.pk)
        self.assertEqual(gateway.snapshot["cages"], [])
        self.assertEqual(gateway.snapshot["retired_cage_ids"], ["CAGE-001"])
        self.assertIsNotNone(gateway.last_received_at)
