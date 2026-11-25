from django.db.models import Q
from .models import Enclosure, User


def client_ip(request):
    # Only the loopback proxy is trusted to supply the overwritten client IP.
    peer = request.META.get("REMOTE_ADDR", "")
    return (
        request.META.get("HTTP_X_REAL_IP", peer)
        if peer in ("127.0.0.1", "::1")
        else peer
    )


def visible_accounts(actor):
    if actor.role == User.Role.OWNER:
        return User.objects.all()
    if actor.role == User.Role.MANAGER:
        return User.objects.filter(
            Q(pk=actor.pk) | Q(role=User.Role.USER, store_id=actor.store_id)
        )
    return User.objects.filter(pk=actor.pk)


def manageable_accounts(actor):
    return (
        visible_accounts(actor).exclude(pk=actor.pk).exclude(role=User.Role.OWNER)
        if actor.role != User.Role.USER
        else User.objects.none()
    )


def allowed_enclosures(actor):
    if actor.role == User.Role.OWNER:
        return Enclosure.objects.all()
    result = Enclosure.objects.filter(store_id=actor.store_id)
    return result if actor.role == User.Role.MANAGER else result.filter(user=actor)
