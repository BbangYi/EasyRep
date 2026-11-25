import uuid
from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from django.dispatch import receiver
from .models import AuditEvent, User


@receiver(user_logged_in)
def register_session(sender, request, user, **kwargs):
    # Owner devices share a generation; password/permission changes revoke all devices.
    with transaction.atomic():
        account = User.objects.select_for_update().get(pk=user.pk)
        if account.role != User.Role.OWNER:
            account.session_generation = uuid.uuid4()
            account.save(update_fields=["session_generation"])
        generation = account.session_generation
        AuditEvent.objects.create(actor=user, action="로그인", target=user.username)
    request.session["generation"] = str(generation)
    request.session.pop("ended_elsewhere", None)
