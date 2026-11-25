import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class Organization(models.Model):
    name = models.CharField(max_length=80, default="EasyRep")


class Store(models.Model):
    organization = models.ForeignKey(Organization, default=1, on_delete=models.PROTECT)
    edge_site_id = models.CharField("Pi 매장 ID", max_length=64, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "edge_site_id"], name="unique_org_site"
            )
        ]

    name = models.CharField("매장 이름", max_length=80)
    region = models.CharField("지역", max_length=100, blank=True)

    def __str__(self):
        return self.name


class Enclosure(models.Model):
    edge_cage_id = models.CharField(
        "Pi 사육장 ID", max_length=64, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["store", "edge_cage_id"], name="unique_store_cage"
            )
        ]

    id = models.SlugField(primary_key=True)
    name = models.CharField("사육장 이름", max_length=100)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, verbose_name="소속 매장")
    species = models.CharField("사육 개체·종", max_length=100, blank=True, default="", db_default="")
    location = models.CharField("설치 위치", max_length=100, blank=True, default="", db_default="")

    def __str__(self):
        return f"{self.store} · {self.name}"


class EnclosurePhoto(models.Model):
    # One bounded, normalized photo per enclosure. Atomic replacement, no public files.
    enclosure = models.OneToOneField(
        Enclosure, primary_key=True, on_delete=models.CASCADE, related_name="photo"
    )
    content = models.BinaryField()
    thumbnail = models.BinaryField()
    width = models.PositiveSmallIntegerField()
    height = models.PositiveSmallIntegerField()
    updated_at = models.DateTimeField(auto_now=True)


class CareRecord(models.Model):
    """Human-entered husbandry log, separate from immutable Pi telemetry."""

    class Kind(models.TextChoices):
        FEEDING = "feeding", "급여"
        CLEANING = "cleaning", "청소"
        SHEDDING = "shedding", "탈피"
        WEIGHT = "weight", "체중"
        NOTE = "note", "특이사항"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enclosure = models.ForeignKey(Enclosure, on_delete=models.PROTECT, related_name="care_records")
    kind = models.CharField("종류", max_length=12, choices=Kind.choices)
    occurred_at = models.DateTimeField("발생 시각")
    note = models.CharField("내용", max_length=2000, blank=True)
    weight_g = models.DecimalField("체중 (g)", max_digits=9, decimal_places=2, null=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.PROTECT, related_name="care_records")
    created_at = models.DateTimeField(auto_now_add=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey("User", on_delete=models.PROTECT, null=True, blank=True, related_name="voided_care_records")
    void_reason = models.CharField(max_length=240, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["enclosure", "-occurred_at", "-id"], name="care_enclosure_time"),
            models.Index(fields=["enclosure", "kind", "-occurred_at", "-id"], name="care_kind_time"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["feeding", "cleaning", "shedding", "weight", "note"]), name="care_known_kind"),
            models.CheckConstraint(condition=(Q(kind="weight", weight_g__isnull=False, weight_g__gt=0, weight_g__lte=1000000) | (~Q(kind="weight") & Q(weight_g__isnull=True))), name="care_weight_matches_kind"),
            models.CheckConstraint(condition=(Q(voided_at__isnull=True, voided_by__isnull=True, void_reason="") | (Q(voided_at__isnull=False, voided_by__isnull=False) & ~Q(void_reason=""))), name="care_void_complete"),
        ]


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "owner", "총괄 관리자"
        MANAGER = "manager", "매장 관리자"
        USER = "user", "사용자"

    username = models.CharField("로그인 ID", max_length=254, unique=True)
    display_name = models.CharField("이름", max_length=40)
    role = models.CharField(
        "역할", max_length=10, choices=Role.choices, default=Role.USER
    )
    store = models.ForeignKey(
        Store, null=True, blank=True, on_delete=models.PROTECT, verbose_name="소속 매장"
    )
    enclosures = models.ManyToManyField(
        Enclosure, blank=True, verbose_name="담당 사육장"
    )
    session_generation = models.UUIDField(default=uuid.uuid4, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("username"), name="unique_login_casefold"),
            models.UniqueConstraint(
                fields=["role"], condition=Q(role="owner"), name="single_owner"
            ),
            models.CheckConstraint(
                condition=Q(role="owner", store__isnull=True)
                | Q(role__in=["manager", "user"], store__isnull=False),
                name="role_store_scope",
            ),
        ]

    def __str__(self):
        return self.display_name or self.username


class SiteSettings(models.Model):
    # One record. No public registration or implicit owner creation.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    title = models.CharField("사이트 이름", max_length=60, default="EasyRep")
    notice = models.CharField("공지", max_length=240, blank=True)
    maintenance = models.BooleanField(
        "점검 모드", default=False, help_text="켜면 총괄 관리자만 접속할 수 있습니다."
    )


class AuditEvent(models.Model):
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=254, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
