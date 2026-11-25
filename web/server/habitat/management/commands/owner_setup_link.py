import uuid
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from habitat.models import User, AuditEvent
from habitat.views import activation_link


class Command(BaseCommand):
    help = "Reissue a setup link only while the initial owner has no usable password."

    def handle(self, *args, **options):
        with transaction.atomic():
            user = User.objects.filter(role=User.Role.OWNER, is_active=True).first()
            if not user or user.has_usable_password():
                raise CommandError(
                    "Owner missing or already activated; use the normal password-change flow."
                )
            user.set_unusable_password()
            user.session_generation = uuid.uuid4()
            user.save(update_fields=["password", "session_generation"])
            AuditEvent.objects.create(
                actor=user, action="최초 설정 링크 재발급", target=user.username
            )
            self.stdout.write(activation_link(user))
