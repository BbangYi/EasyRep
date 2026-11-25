import os
from pathlib import Path
import secrets
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from edge.ingestion import token_digest
from edge.models import Gateway
from habitat.models import AuditEvent


class Command(BaseCommand):
    help = "Revoke the previous Pi token and write a new one to a NEW private file."

    def add_arguments(self, parser):
        parser.add_argument("gateway_uuid")
        parser.add_argument("--token-file", required=True)

    def handle(self, *args, **options):
        path = Path(options["token_file"])
        wrote_token = False
        try:
            with transaction.atomic():
                gateway = Gateway.objects.select_for_update().get(
                    pk=options["gateway_uuid"]
                )
                token = secrets.token_urlsafe(48)
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                wrote_token = True
                with os.fdopen(descriptor, "w") as stream:
                    stream.write(token + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                gateway.token_digest = token_digest(token)
                gateway.save(update_fields=["token_digest"])
                AuditEvent.objects.create(
                    action="Pi 인증키 교체", target=gateway.edge_gateway_id
                )
        except Exception as error:
            if wrote_token:
                path.unlink(missing_ok=True)
            raise CommandError(
                "Token rotation failed; previous database credential retained"
            ) from error
        self.stdout.write("Token rotated and saved privately. Previous token revoked.")
