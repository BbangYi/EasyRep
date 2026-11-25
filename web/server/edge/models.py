import uuid
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator


class Gateway(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey("habitat.Store", on_delete=models.PROTECT)
    edge_gateway_id = models.CharField("Pi ID", max_length=64)
    token_digest = models.CharField(max_length=64, unique=True)
    active = models.BooleanField("수신 허용", default=True)
    allow_simulation = models.BooleanField("가상 데이터 허용", default=False)
    offline_after_s = models.PositiveIntegerField(
        "통신 끊김 판단 (초)",
        default=60,
        validators=[MinValueValidator(10), MaxValueValidator(3600)],
    )
    last_received_at = models.DateTimeField(null=True)
    snapshot_sent_at = models.DateTimeField(null=True)
    snapshot = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["store", "edge_gateway_id"], name="unique_store_gateway"
            )
        ]

    def __str__(self):
        return f"{self.store} · {self.edge_gateway_id}"


class Binding(models.Model):
    enclosure = models.OneToOneField(
        "habitat.Enclosure", on_delete=models.PROTECT, related_name="edge_binding"
    )
    gateway = models.ForeignKey(
        Gateway, on_delete=models.PROTECT, related_name="bindings"
    )
    node_id = models.CharField(max_length=64, blank=True)


class CurrentState(models.Model):
    enclosure = models.OneToOneField(
        "habitat.Enclosure", on_delete=models.CASCADE, related_name="current_state"
    )
    configuration = models.JSONField(default=dict)
    snapshot_sent_at = models.DateTimeField(null=True)
    mode = models.CharField(max_length=16, blank=True)
    telemetry = models.JSONField(default=dict)
    sampled_at = models.DateTimeField(null=True)
    telemetry_sequence = models.BigIntegerField(null=True)
    actuators = models.JSONField(default=dict)


class Event(models.Model):
    gateway = models.ForeignKey(Gateway, on_delete=models.PROTECT)
    enclosure = models.ForeignKey("habitat.Enclosure", on_delete=models.PROTECT)
    event_id = models.UUIDField()
    event_sequence = models.BigIntegerField()
    kind = models.CharField(max_length=32)
    created_at = models.DateTimeField()
    sampled_at = models.DateTimeField(null=True)
    received_at = models.DateTimeField(auto_now_add=True)
    digest = models.CharField(max_length=64)
    body = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["gateway", "event_id"], name="unique_gateway_event"
            ),
            models.UniqueConstraint(
                fields=["gateway", "event_sequence"], name="unique_gateway_sequence"
            ),
        ]
        indexes = [
            models.Index(fields=["enclosure", "sampled_at"]),
            models.Index(fields=["enclosure", "-created_at", "-id"]),
        ]


class CommandState(models.Model):
    gateway = models.ForeignKey(Gateway, on_delete=models.PROTECT)
    enclosure = models.ForeignKey("habitat.Enclosure", on_delete=models.PROTECT)
    command_id = models.UUIDField()
    event_sequence = models.BigIntegerField()
    body = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["gateway", "command_id"], name="unique_gateway_command"
            )
        ]


class Measurement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gateway = models.ForeignKey(Gateway, on_delete=models.PROTECT)
    enclosure = models.ForeignKey("habitat.Enclosure", on_delete=models.PROTECT)
    message_id = models.UUIDField()
    sampled_at = models.DateTimeField()
    received_at = models.DateTimeField(default=timezone.now)
    payload = models.JSONField()
    event = models.ForeignKey(Event, null=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["gateway", "enclosure", "message_id"], name="unique_received_measurement"
        )]
        indexes = [models.Index(fields=["enclosure", "sampled_at"], name="measurement_cage_time")]
