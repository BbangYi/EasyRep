import copy
import json
from pathlib import Path
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MeasurementMigrationTests(TransactionTestCase):
    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_events_keep_original_receipt_and_merge_same_measurement(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("edge", "0001_initial")])
        apps = executor.loader.project_state([("edge", "0001_initial")]).apps
        org = apps.get_model("habitat", "Organization").objects.create(name="Migration fixture")
        store = apps.get_model("habitat", "Store").objects.create(name="Fixture", organization=org)
        cage = apps.get_model("habitat", "Enclosure").objects.create(id="fixture", name="Fixture", store=store)
        gateway = apps.get_model("edge", "Gateway").objects.create(store=store, edge_gateway_id="PI", token_digest="fixture")
        Event = apps.get_model("edge", "Event")
        fixture = json.loads((Path(__file__).parent / "fixtures/sync-request.json").read_text())
        body = next(e for e in fixture["events"] if e["kind"] == "telemetry.recorded")
        first = Event.objects.create(gateway=gateway, enclosure=cage, event_id=body["event_id"],
            event_sequence=1, kind=body["kind"], created_at=body["created_at"],
            sampled_at=body["payload"]["sampled_at"], digest="fixture", body=body)
        payload = copy.deepcopy(body["payload"])
        payload["readings"]["T1"]["value"] = 25.0
        later = Event.objects.create(gateway=gateway, enclosure=cage,
            event_id="00000000-0000-4000-8000-000000000002", event_sequence=2,
            kind=body["kind"], created_at=body["created_at"], sampled_at=body["payload"]["sampled_at"],
            digest="fixture", body={**body, "payload": payload})
        executor = MigrationExecutor(connection)
        executor.migrate([("edge", "0002_measurement")])
        apps = executor.loader.project_state([("edge", "0002_measurement")]).apps
        Measurement = apps.get_model("edge", "Measurement")
        self.assertEqual(Measurement.objects.count(), 1)
        row = Measurement.objects.get()
        self.assertEqual(row.received_at, first.received_at)
        self.assertEqual(row.event_id, later.pk)
        self.assertEqual(row.payload["readings"]["T1"]["value"], 25.0)
        self.assertEqual(apps.get_model("edge", "Event").objects.count(), 2)
