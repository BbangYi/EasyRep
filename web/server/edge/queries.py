"""Browser queries. Scope is always derived from the authenticated account."""

from datetime import datetime, timedelta, timezone as utc_timezone
from uuid import UUID
from django.http import JsonResponse
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET
from habitat.access import allowed_enclosures
from .models import CommandState, Event, Measurement
from .spatial import layout_for

HISTORY_LIMIT = 2000


def iso(value):
    return value.isoformat() if value else None


def scoped(user):
    latest = Measurement.objects.filter(
        enclosure_id=OuterRef("pk")
    ).order_by("-sampled_at", "-received_at", "-pk")
    return allowed_enclosures(user).annotate(
        history_sampled_at=Subquery(latest.values("sampled_at")[:1]),
        history_received_at=Subquery(latest.values("received_at")[:1]),
    ).select_related(
        "store", "current_state", "edge_binding__gateway", "photo"
    ).defer("photo__content", "photo__thumbnail")


def describe(item, now):
    photo = getattr(item, "photo", None)
    binding = getattr(item, "edge_binding", None)
    gateway = binding.gateway if binding else None
    state = getattr(item, "current_state", None)
    telemetry = state.telemetry if state else {}
    config = state.configuration if state else {}
    stale = (
        not state
        or not state.sampled_at
        or (now - state.sampled_at).total_seconds() > config.get("stale_after_s", 15)
        or state.sampled_at > now + timedelta(seconds=60)
    )
    gateway_status = (
        "unregistered"
        if not gateway
        else (
            "disabled"
            if not gateway.active
            else (
                "waiting"
                if not gateway.last_received_at
                else (
                    "offline"
                    if (now - gateway.last_received_at).total_seconds()
                    > gateway.offline_after_s
                    else "connected"
                )
            )
        )
    )
    configuration_changed = bool(telemetry) and any(
        telemetry.get(key) != config.get(key)
        for key in ("geometry_revision", "placement_revision")
    )
    if configuration_changed:
        stale = True
    readings = {} if configuration_changed else telemetry.get("readings", {})
    sensors = [
        {
            "id": sensor["id"],
            "unit": sensor["unit"],
            "value": readings.get(sensor["id"], {}).get("value"),
            "quality": readings.get(sensor["id"], {}).get("quality", "missing"),
        }
        for sensor in config.get("sensors", [])
    ]
    return {
        "id": item.pk,
        "name": item.name,
        "species": item.species,
        "location": item.location,
        "store": item.store.name,
        "photo": {
            "url": f"/api/enclosures/{item.pk}/photo/?v={photo.updated_at.timestamp()}",
            "thumbnailUrl": f"/api/enclosures/{item.pk}/photo/?size=thumbnail&v={photo.updated_at.timestamp()}",
            "updatedAt": iso(photo.updated_at),
        } if photo else None,
        "siteId": item.store.edge_site_id,
        "cageId": item.edge_cage_id,
        "gateway": {
            "id": gateway.edge_gateway_id if gateway else None,
            "status": gateway_status,
            "lastReceivedAt": iso(gateway.last_received_at) if gateway else None,
        },
        "historyReceipt": {
            "sampledAt": iso(item.history_sampled_at),
            "receivedAt": iso(item.history_received_at),
            "behindCurrent": bool(state and state.sampled_at and (
                not item.history_sampled_at or item.history_sampled_at < state.sampled_at
            )),
        },
        "sampledAt": iso(state.sampled_at) if state else None,
        "piReceivedAt": telemetry.get("received_at"),
        "stale": stale,
        "source": telemetry.get("data_source"),
        "sensors": sensors,
        "actuators": state.actuators if state else {},
        "mode": state.mode if state else "",
        "configurationChanged": configuration_changed,
        "staleAfterSeconds": config.get("stale_after_s", 15),
        "geometryRevision": config.get("geometry_revision"),
        "placementRevision": config.get("placement_revision"),
        "spatialLayout": layout_for(item, config, gateway),
    }


@require_GET
def enclosures(request):
    now = timezone.now()
    items = list(scoped(request.user).order_by("store__name", "name", "pk")[:201])
    return JsonResponse(
        {
            "asOf": iso(now),
            "items": [describe(item, now) for item in items[:200]],
            "truncated": len(items) > 200,
        }
    )


@require_GET
def current(request, enclosure_id):
    item = get_object_or_404(scoped(request.user), pk=enclosure_id)
    return JsonResponse(
        {"asOf": iso(timezone.now()), "item": describe(item, timezone.now())}
    )


def period(request):
    try:
        hours = int(request.GET.get("hours", "6"))
        if hours not in (1, 6, 24):
            raise ValueError
        end = (
            datetime.fromisoformat(request.GET["end"])
            if "end" in request.GET
            else timezone.now()
        )
        if end.utcoffset() is None:
            raise ValueError
        end = end.astimezone(utc_timezone.utc)
        return end - timedelta(hours=hours), end
    except (ValueError, TypeError, OverflowError):
        return None, None


@require_GET
def history(request, enclosure_id):
    item = get_object_or_404(scoped(request.user), pk=enclosure_id)
    start, end = period(request)
    if start is None:
        return JsonResponse({"error": "invalid_period"}, status=400)
    query = Measurement.objects.filter(
        enclosure=item,
        sampled_at__gte=start,
        sampled_at__lte=end,
    )
    before = request.GET.get("before")
    if before is not None:
        try:
            sampled, received, key = before.split("|")
            sampled, received = datetime.fromisoformat(sampled), datetime.fromisoformat(received)
            if sampled.utcoffset() is None or received.utcoffset() is None:
                raise ValueError
            sampled = sampled.astimezone(utc_timezone.utc)
            received = received.astimezone(utc_timezone.utc)
            key = UUID(key)
        except (ValueError, TypeError, OverflowError):
            return JsonResponse({"error": "invalid_cursor"}, status=400)
        query = query.filter(
            Q(sampled_at__lt=sampled)
            | Q(sampled_at=sampled, received_at__lt=received)
            | Q(sampled_at=sampled, received_at=received, pk__lt=key)
        )
    rows = list(
        query.select_related("event").order_by("-sampled_at", "-received_at", "-pk")[: HISTORY_LIMIT + 1]
    )
    truncated = len(rows) > HISTORY_LIMIT
    rows = list(reversed(rows[:HISTORY_LIMIT]))
    points = [
        {
            "id": str(e.pk),
            "eventId": str(e.pk),  # Legacy chart key; piEventId is the actual Pi event ID.
            "piEventId": str(e.event.event_id) if e.event_id else None,
            "receiptSource": "event" if e.event_id else "snapshot",
            "at": iso(e.sampled_at),
            "serverReceivedAt": iso(e.received_at),
            **e.payload,
        }
        for e in rows
    ]
    commands = list(
        Event.objects.filter(
            enclosure=item,
            kind="command.updated",
            created_at__gte=start,
            created_at__lte=end,
        ).order_by("created_at", "pk")[:501]
    )
    return JsonResponse(
        {
            "start": iso(start),
            "end": iso(end),
            "points": points,
            "commands": [
                {
                    "id": str(e.event_id),
                    "at": iso(e.created_at),
                    "actuator": e.body["payload"]["actuator_id"],
                    "action": e.body["payload"]["action"],
                    "status": e.body["payload"]["status"],
                }
                for e in commands[:500]
            ],
            "truncated": truncated,
            "commandsTruncated": len(commands) > 500,
            "limit": HISTORY_LIMIT,
            "olderThan": iso(rows[0].sampled_at) if rows and truncated else None,
            "next": (
                f"{rows[0].sampled_at.isoformat()}|{rows[0].received_at.isoformat()}|{rows[0].pk}"
                if rows and truncated else None
            ),
        }
    )


@require_GET
def records(request, enclosure_id):
    item = get_object_or_404(scoped(request.user), pk=enclosure_id)
    kind = request.GET.get("kind", "all")
    if kind not in ("all", "telemetry.recorded", "command.updated"):
        return JsonResponse({"error": "invalid_kind"}, status=400)
    query = Event.objects.filter(enclosure=item)
    if kind != "all":
        query = query.filter(kind=kind)
    search = request.GET.get("q", "").strip()[:80]
    if search:
        # Match visible Korean labels against their fields, not unrelated JSON keys.
        devices = {"분무": "mister", "환기": "fan", "조명": "light", "히터": "heater"}
        statuses = {
            "발행 대기": "publishing", "전송됨 결과 대기": "published",
            "장치 적용 확인": "applied", "거절": "rejected",
            "기한 만료": "expired", "실행 중단": "interrupted",
        }
        for term in search.replace("·", " ").split():
            match = Q(body__icontains=term)
            for label, value in devices.items():
                if term in label or term in label.replace(" ", ""):
                    match |= Q(kind="command.updated", body__payload__actuator_id=value)
            for label, value in statuses.items():
                if term in label or term in label.replace(" ", ""):
                    match |= Q(kind="command.updated", body__payload__status=value)
            if term in "환경 측정":
                match |= Q(kind="telemetry.recorded")
            if term in "명령 처리":
                match |= Q(kind="command.updated")
            if term in "센서 데이터":
                match |= Q(kind="telemetry.recorded", body__payload__data_source="sensor")
            if term in "가상 데이터":
                match |= Q(kind="telemetry.recorded", body__payload__data_source="simulation")
            query = query.filter(match)
    before = request.GET.get("before")
    if before:
        try:
            stamp, key = before.rsplit("|", 1)
            stamp = datetime.fromisoformat(stamp)
            if stamp.utcoffset() is None:
                raise ValueError
            query = query.filter(
                Q(created_at__lt=stamp) | Q(created_at=stamp, pk__lt=int(key))
            )
        except (ValueError, TypeError):
            return JsonResponse({"error": "invalid_cursor"}, status=400)
    rows = list(query.order_by("-created_at", "-pk")[:51])
    page = rows[:50]
    return JsonResponse(
        {
            "items": [
                {
                    "id": str(e.event_id),
                    "kind": e.kind,
                    "at": iso(e.created_at),
                    "serverReceivedAt": iso(e.received_at),
                    "sequence": e.event_sequence,
                    "payload": e.body["payload"],
                }
                for e in page
            ],
            "next": (
                f"{page[-1].created_at.isoformat()}|{page[-1].pk}"
                if len(rows) > 50
                else None
            ),
        }
    )


@require_GET
def commands(request, enclosure_id):
    item = get_object_or_404(scoped(request.user), pk=enclosure_id)
    return JsonResponse(
        {
            "items": list(
                CommandState.objects.filter(enclosure=item)
                .order_by("-event_sequence")
                .values_list("body", flat=True)[:30]
            )
        }
    )
