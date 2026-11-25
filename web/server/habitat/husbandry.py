"""Sensor-independent registration and scoped, append-only husbandry records."""

import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from django import forms
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from .access import allowed_enclosures
from .forms import EnclosureForm
from .models import AuditEvent, CareRecord, Enclosure
from .views import roles

PAGE_SIZE = 20


class RegistrationForm(EnclosureForm):
    submission = forms.CharField(widget=forms.HiddenInput)


class CareForm(forms.ModelForm):
    submission = forms.CharField(widget=forms.HiddenInput)
    occurred_at = forms.DateTimeField(
        label="발생 시각 (한국 시간)",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}
        ),
    )
    weight_g = forms.DecimalField(
        label="체중 (g)",
        required=False,
        min_value=Decimal("0.01"),
        max_value=Decimal("1000000"),
        max_digits=9,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
        help_text="체중 기록일 때만 입력하세요.",
    )

    class Meta:
        model = CareRecord
        fields = ["kind", "occurred_at", "weight_g", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 4, "maxlength": 2000})}

    def clean_occurred_at(self):
        value = self.cleaned_data["occurred_at"]
        if value > timezone.now() + timedelta(minutes=5):
            raise forms.ValidationError("미래의 기록은 등록할 수 없습니다.")
        return value

    def clean(self):
        data = super().clean()
        if data.get("kind") == CareRecord.Kind.WEIGHT:
            if data.get("weight_g") is None:
                self.add_error("weight_g", "체중을 입력하세요.")
        else:
            if data.get("weight_g") is not None:
                self.add_error("weight_g", "체중은 종류가 ‘체중’일 때만 입력하세요.")
            if not data.get("note"):
                self.add_error("note", "관리 내용을 입력하세요.")
        return data


class VoidForm(forms.Form):
    reason = forms.CharField(
        label="취소 사유", max_length=240, widget=forms.Textarea(attrs={"rows": 3})
    )


def new_submission(user, scope):
    return signing.dumps(
        {"id": str(uuid.uuid4()), "actor": user.pk, "scope": scope},
        salt="husbandry-submit",
    )


def submission_id(form, user, scope):
    try:
        data = signing.loads(
            form.cleaned_data["submission"], salt="husbandry-submit", max_age=86400
        )
        if data["actor"] != user.pk or data["scope"] != scope:
            raise ValueError
        return uuid.UUID(data["id"])
    except (signing.BadSignature, KeyError, ValueError, TypeError):
        # Preserve entered fields but renew an expired/invalid one-time submission.
        form.data = form.data.copy()
        form.data["submission"] = new_submission(user, scope)
        form.add_error(
            None,
            "작성 화면이 만료되었습니다. 입력 내용을 확인하고 다시 저장하세요.",
        )
        return None


@roles("owner")
@require_http_methods(["GET", "POST"])
def enclosure_create(request):
    form = RegistrationForm(
        request.POST if request.method == "POST" else None,
        initial={"submission": new_submission(request.user, "enclosure")},
    )
    if request.method == "POST" and form.is_valid():
        key = submission_id(form, request.user, "enclosure")
        if key:
            with transaction.atomic():
                item, created = Enclosure.objects.get_or_create(
                    pk=str(key),
                    defaults={
                        field: form.cleaned_data[field]
                        for field in ("name", "store", "species", "location")
                    },
                )
                if created:
                    AuditEvent.objects.create(
                        actor=request.user, action="사육장 등록", target=item.pk
                    )
            return redirect(f"/#management/{item.pk}")
    return render(
        request,
        "husbandry-form.html",
        {
            "title": "사육장 등록",
            "description": "센서 없이 먼저 등록할 수 있습니다. 장치가 연결되기 전에는 측정값을 표시하지 않습니다.",
            "form": form,
            "back": "/manage/",
            "submit_label": "사육장 등록",
        },
    )


@roles("owner", "manager")
@require_http_methods(["GET", "POST"])
def care_create(request, enclosure_id):
    # Scope is checked inside the write transaction as well, including retries.
    enclosure = get_object_or_404(allowed_enclosures(request.user), pk=enclosure_id)
    form = CareForm(
        request.POST if request.method == "POST" else None,
        initial={
            "occurred_at": timezone.localtime().replace(second=0, microsecond=0),
            "submission": new_submission(request.user, enclosure.pk),
        },
    )
    if request.method == "POST" and form.is_valid():
        key = submission_id(form, request.user, enclosure.pk)
        if key:
            with transaction.atomic():
                enclosure = get_object_or_404(
                    allowed_enclosures(request.user), pk=enclosure_id
                )
                record, created = CareRecord.objects.get_or_create(
                    pk=key,
                    defaults={
                        "enclosure": enclosure,
                        "created_by": request.user,
                        **{
                            field: form.cleaned_data[field]
                            for field in ("kind", "occurred_at", "note", "weight_g")
                        },
                    },
                )
                if created:
                    AuditEvent.objects.create(
                        actor=request.user,
                        action="사육 관리 기록 작성",
                        target=str(record.pk),
                    )
            return redirect(f"/?care_saved={enclosure.pk}#history/{enclosure.pk}?section=care")
    return render(
        request,
        "husbandry-form.html",
        {
            "title": "관리 기록 작성",
            "care_enclosure": enclosure,
            "description": f"{enclosure.name} · 직접 입력한 기록으로 저장됩니다.",
            "form": form,
            "back": f"/#history/{enclosure.pk}?section=care",
            "submit_label": "기록 저장",
        },
    )


@roles("owner", "manager")
@require_http_methods(["GET", "POST"])
def care_void(request, enclosure_id, record_id):
    enclosure = get_object_or_404(allowed_enclosures(request.user), pk=enclosure_id)
    record = get_object_or_404(CareRecord, enclosure=enclosure, pk=record_id)
    form = VoidForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            enclosure = get_object_or_404(
                allowed_enclosures(request.user), pk=enclosure_id
            )
            changed = CareRecord.objects.filter(
                pk=record.pk, enclosure=enclosure, voided_at__isnull=True
            ).update(
                voided_at=timezone.now(),
                voided_by=request.user,
                void_reason=form.cleaned_data["reason"],
            )
            if changed:
                AuditEvent.objects.create(
                    actor=request.user,
                    action="사육 관리 기록 취소",
                    target=str(record.pk),
                )
        return redirect(f"/#history/{enclosure.pk}?section=care")
    return render(
        request,
        "husbandry-form.html",
        {
            "title": "기록 취소",
            "description": "원본과 취소 사유를 보존합니다. 잘못 입력한 기록은 취소한 뒤 새로 작성하세요.",
            "form": form,
            "record": record,
            "back": f"/#history/{enclosure.pk}?section=care",
            "submit_label": "기록 취소",
        },
    )


def date_boundary(value):
    day = datetime.strptime(value, "%Y-%m-%d").date()
    return timezone.make_aware(datetime.combine(day, time.min))


@require_GET
def care_records(request, enclosure_id):
    enclosure = get_object_or_404(allowed_enclosures(request.user), pk=enclosure_id)
    records = (
        CareRecord.objects.filter(enclosure=enclosure)
        .select_related("created_by", "voided_by")
        .only(
            "id",
            "enclosure_id",
            "kind",
            "occurred_at",
            "note",
            "weight_g",
            "created_at",
            "created_by__display_name",
            "created_by__username",
            "voided_at",
            "voided_by__display_name",
            "voided_by__username",
            "void_reason",
        )
    )
    kind = request.GET.get("kind", "all")
    status = request.GET.get("status", "active")
    keyword = request.GET.get("q", "").strip()
    if (
        kind not in ["all", *CareRecord.Kind.values]
        or status not in ("active", "all", "voided")
        or len(keyword) > 80
    ):
        return JsonResponse({"error": "invalid_filter"}, status=400)
    if kind != "all":
        records = records.filter(kind=kind)
    if status != "all":
        records = records.filter(voided_at__isnull=status == "active")
    if keyword:
        records = records.filter(note__icontains=keyword)
    try:
        start = date_boundary(request.GET["from"]) if request.GET.get("from") else None
        end = (
            date_boundary(request.GET["to"]) + timedelta(days=1)
            if request.GET.get("to")
            else None
        )
        if start and end and start >= end:
            raise ValueError
        if start:
            records = records.filter(occurred_at__gte=start)
        if end:
            records = records.filter(occurred_at__lt=end)
        if request.GET.get("before"):
            stamp, key = request.GET["before"].split("|", 1)
            stamp = datetime.fromisoformat(stamp)
            key = uuid.UUID(key)
            if timezone.is_naive(stamp):
                raise ValueError
            records = records.filter(
                Q(occurred_at__lt=stamp) | Q(occurred_at=stamp, pk__lt=key)
            )
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({"error": "invalid_period_or_cursor"}, status=400)
    rows = list(records.order_by("-occurred_at", "-pk")[: PAGE_SIZE + 1])
    page = rows[:PAGE_SIZE]
    return JsonResponse(
        {
            "items": [
                {
                    "id": str(row.pk),
                    "kind": row.kind,
                    "kindLabel": row.get_kind_display(),
                    "at": row.occurred_at.isoformat(),
                    "note": row.note,
                    "weightG": str(row.weight_g) if row.weight_g is not None else None,
                    "author": str(row.created_by),
                    "createdAt": row.created_at.isoformat(),
                    "voidedAt": row.voided_at.isoformat() if row.voided_at else None,
                    "voidedBy": str(row.voided_by) if row.voided_by else None,
                    "voidReason": row.void_reason,
                }
                for row in page
            ],
            "next": (
                f"{page[-1].occurred_at.isoformat()}|{page[-1].pk}"
                if len(rows) > PAGE_SIZE
                else None
            ),
        }
    )
