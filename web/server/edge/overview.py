"""Period summaries over persisted rows, without the raw-history display limit."""
from datetime import datetime, timedelta, timezone as utc_timezone
from zoneinfo import ZoneInfo
from django.db.models import Avg, Case, CharField, Count, FloatField, Func, Max, Min, Q, Value, When
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast, NullIf
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET
from habitat.models import CareRecord
from .models import Event, Measurement
from .queries import iso, scoped

KST = ZoneInfo("Asia/Seoul")


class KstBucket(Func):
    """Group SQLite timestamps in KST without Django's row-by-row Python UDF."""

    output_field = CharField()

    def __init__(self, expression, *, hourly):
        self.bucket_format = "%Y-%m-%dT%H:00:00+09:00" if hourly else "%Y-%m-%dT00:00:00+09:00"
        super().__init__(expression)

    def as_sql(self, compiler, connection, **extra_context):
        sql, params = compiler.compile(self.source_expressions[0])
        return f"strftime('{self.bucket_format}', datetime({sql}, '+9 hours'))", params


@require_GET
def overview(request, enclosure_id):
    item = get_object_or_404(scoped(request.user), pk=enclosure_id)
    try:
        days = int(request.GET.get("days", "7"))
        if days not in (1, 7, 30):
            raise ValueError
        end = datetime.fromisoformat(request.GET["end"]) if "end" in request.GET else timezone.now()
        if end.utcoffset() is None:
            raise ValueError
        end = end.astimezone(utc_timezone.utc)
        start = end - timedelta(days=days)
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({"error": "invalid_period"}, status=400)

    step = timedelta(hours=1) if days == 1 else timedelta(days=1)
    cursor = start.astimezone(KST).replace(minute=0, second=0, microsecond=0)
    if days != 1:
        cursor = cursor.replace(hour=0)
    buckets = {}
    while cursor <= end:
        bucket = iso(cursor)
        buckets[bucket] = {"at": bucket, "sensorCount": 0, "commandUpdates": 0, "careCount": 0, "readings": {}}
        cursor += step

    as_of = timezone.now()
    all_rows = Measurement.objects.filter(enclosure=item, sampled_at__lte=end, received_at__lte=as_of)
    sensor_source = Q(payload__data_source="sensor")
    lifetime = all_rows.aggregate(sensorCount=Count("pk", filter=sensor_source), firstAt=Min("sampled_at", filter=sensor_source), lastAt=Max("sampled_at", filter=sensor_source))
    rows = all_rows.filter(sampled_at__gte=start)
    counts = rows.aggregate(total=Count("pk"), sensorCount=Count("pk", filter=sensor_source))
    real = rows.filter(sensor_source)
    measurement_bucket = KstBucket("sampled_at", hourly=days == 1)
    for row in real.annotate(bucket=measurement_bucket).values("bucket").annotate(count=Count("pk")):
        buckets[row["bucket"]]["sensorCount"] = row["count"]

    state = getattr(item, "current_state", None)
    config = state.configuration if state else {}
    compatible = real.filter(payload__geometry_revision=config.get("geometry_revision"), payload__placement_revision=config.get("placement_revision")) if config else real.none()
    # Aggregate every configured sensor in one scan; derive period means by sample count.
    annotations = {}
    aggregates = {"samples": Count("pk")}
    sensors = []
    for index, sensor in enumerate(config.get("sensors", [])):
        reading = KeyTransform(sensor["id"], KeyTransform("readings", "payload"))
        quality_key, value_key = f"quality_{index}", f"value_{index}"
        annotations[quality_key] = Cast(KeyTextTransform("quality", reading), CharField())
        annotations[value_key] = Case(When(**{quality_key: "valid"}, then=Cast(NullIf(KeyTextTransform("value", reading), Value("null")), FloatField())), output_field=FloatField())
        for key, function in [("count", Count), ("avg", Avg), ("min", Min), ("max", Max)]:
            aggregates[f"{key}_{index}"] = function(value_key)
        sensors.append({"id": sensor["id"], "unit": sensor["unit"], "count": 0, "avg": None, "min": None, "max": None})
    compatible_count = 0
    for row in compatible.annotate(**annotations).annotate(bucket=measurement_bucket).values("bucket").annotate(**aggregates):
        compatible_count += row["samples"]
        for index, sensor in enumerate(sensors):
            stats = {key: row[f"{key}_{index}"] for key in ("count", "avg", "min", "max")}
            if not stats["count"]:
                continue
            buckets[row["bucket"]]["readings"][sensor["id"]] = stats
            previous_count = sensor["count"]
            sensor["count"] += stats["count"]
            sensor["avg"] = ((sensor["avg"] or 0) * previous_count + stats["avg"] * stats["count"]) / sensor["count"]
            sensor["min"] = min(sensor["min"], stats["min"]) if previous_count else stats["min"]
            sensor["max"] = max(sensor["max"], stats["max"]) if previous_count else stats["max"]
    for sensor in sensors:
        sensor["invalidCount"] = compatible_count - sensor["count"]

    commands = Event.objects.filter(enclosure=item, kind="command.updated", created_at__gte=start, created_at__lte=end)
    for row in commands.annotate(bucket=KstBucket("created_at", hourly=days == 1)).values("bucket").annotate(count=Count("pk")):
        buckets[row["bucket"]]["commandUpdates"] = row["count"]
    care = CareRecord.objects.filter(enclosure=item, voided_at__isnull=True, occurred_at__gte=start, occurred_at__lte=end)
    care_kinds = {row["kind"]: row["count"] for row in care.values("kind").annotate(count=Count("pk"))}
    for row in care.annotate(bucket=KstBucket("occurred_at", hourly=days == 1)).values("bucket").annotate(count=Count("pk")):
        buckets[row["bucket"]]["careCount"] = row["count"]
    return JsonResponse({
        "asOf": iso(as_of),
        "lifetime": {**lifetime, "firstAt": iso(lifetime["firstAt"]), "lastAt": iso(lifetime["lastAt"])},
        "period": {"start": iso(start), "end": iso(end), "days": days, "bucketHours": 1 if days == 1 else 24,
                   "sensorCount": counts["sensorCount"], "otherSourceCount": counts["total"] - counts["sensorCount"],
                   "otherConfigurationCount": counts["sensorCount"] - compatible_count},
        "sensors": sensors, "buckets": list(buckets.values()),
        # A command may report several status changes; neither number is physical activation count.
        "commands": {"count": commands.values("gateway_id", "body__payload__command_id").distinct().count(), "updates": commands.count()},
        "care": {"count": sum(care_kinds.values()), "kinds": care_kinds},
    })
