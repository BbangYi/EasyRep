"""Explicit server-side registration. Never trust tenant/scope from an inbound batch."""

import json
import os
from pathlib import Path
import secrets
import uuid
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from pydantic import TypeAdapter, ValidationError
from edge.contracts import Identifier
from edge.ingestion import token_digest
from edge.models import Binding, Gateway
from habitat.models import AuditEvent, Enclosure, Organization, Store


class Command(BaseCommand):
    help = "Register a Pi from JSON and write its bearer token to a NEW private file (never stdout)."

    def add_arguments(self, parser):
        parser.add_argument("registration")
        parser.add_argument("--token-file", required=True)

    def handle(self, *args, **options):
        target = Path(options["token_file"])
        try:
            data = json.loads(Path(options["registration"]).read_text())
            identifier = TypeAdapter(Identifier)
            for key in ("site_id", "gateway_id"):
                identifier.validate_python(data[key])
            cages = data["cages"]
            if (
                not cages
                or len(cages) > 100
                or len({c["id"] for c in cages}) != len(cages)
            ):
                raise ValueError("One to 100 distinct cages required")
            for cage in cages:
                identifier.validate_python(cage["id"])
                if cage.get("node_id"):
                    identifier.validate_python(cage["node_id"])
                if (
                    not isinstance(cage["name"], str)
                    or not 1 <= len(cage["name"]) <= 100
                ):
                    raise ValueError("Cage name required")
            if type(data.get("allow_simulation", False)) is not bool:
                raise ValueError("allow_simulation must be boolean")
            if (
                not isinstance(data["store_name"], str)
                or not 1 <= len(data["store_name"]) <= 80
            ):
                raise ValueError("Store name required")
            organization = Organization.objects.get(pk=data.get("organization_id", 1))
            if target.exists():
                raise ValueError("Token file already exists; refusing to overwrite")
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            ValidationError,
            Organization.DoesNotExist,
        ) as error:
            raise CommandError(str(error)) from error
        token = secrets.token_urlsafe(48)
        wrote_token = False
        try:
            with transaction.atomic():
                store, _ = Store.objects.get_or_create(
                    organization=organization,
                    edge_site_id=data["site_id"],
                    defaults={"name": data["store_name"]},
                )
                if Gateway.objects.filter(
                    store=store, edge_gateway_id=data["gateway_id"]
                ).exists():
                    raise CommandError(
                        "Gateway already registered; use rotate_gateway_token for rotation"
                    )
                gateway = Gateway.objects.create(
                    store=store,
                    edge_gateway_id=data["gateway_id"],
                    token_digest=token_digest(token),
                    allow_simulation=data.get("allow_simulation", False),
                )
                for cage in cages:
                    enclosure, _ = Enclosure.objects.get_or_create(
                        store=store,
                        edge_cage_id=cage["id"],
                        defaults={"id": str(uuid.uuid4()), "name": cage["name"]},
                    )
                    if Binding.objects.filter(enclosure=enclosure).exists():
                        raise CommandError("A cage already belongs to a registered Pi")
                    Binding.objects.create(
                        gateway=gateway,
                        enclosure=enclosure,
                        node_id=cage.get("node_id", ""),
                    )
                descriptor = os.open(
                    target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                wrote_token = True
                with os.fdopen(descriptor, "w") as stream:
                    stream.write(token + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                AuditEvent.objects.create(
                    action="Pi 등록", target=f"{store.name} / {gateway.edge_gateway_id}"
                )
        except Exception:
            if wrote_token:
                target.unlink(missing_ok=True)
            raise
        self.stdout.write(
            f"Registered {gateway.edge_gateway_id}: {len(cages)} cages; token saved privately."
        )
