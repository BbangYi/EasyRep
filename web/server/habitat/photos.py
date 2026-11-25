"""Owner-managed representative photos, readable only within enclosure scope."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from .access import allowed_enclosures
from .models import AuditEvent, EnclosurePhoto
from .photo_processing import MAX_UPLOAD_BYTES, normalize


class PhotoForm(forms.Form):
    photo = forms.FileField(
        label="대표 사진",
        help_text="JPG · PNG · WebP, 최대 5 MB · 2,400만 화소. 저장 시 크기를 줄이고 위치 정보를 제거합니다.",
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp", "data-max-bytes": MAX_UPLOAD_BYTES}),
    )

    def clean_photo(self):
        return normalize(self.cleaned_data["photo"])


@require_GET
def read(request, enclosure_id):
    enclosure = get_object_or_404(allowed_enclosures(request.user), pk=enclosure_id)
    field = "thumbnail" if request.GET.get("size") == "thumbnail" else "content"
    photo = get_object_or_404(EnclosurePhoto.objects.only(field), enclosure=enclosure)
    response = HttpResponse(bytes(getattr(photo, field)), content_type="image/jpeg")
    response["Content-Disposition"] = 'inline; filename="enclosure-photo.jpg"'
    response["Cache-Control"] = "private, no-store"
    return response


@require_http_methods(["GET", "POST"])
def edit(request, enclosure_id):
    if request.user.role != "owner":
        raise PermissionDenied
    enclosure = get_object_or_404(allowed_enclosures(request.user), pk=enclosure_id)
    form = PhotoForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
    )
    if request.method == "POST":
        if request.POST.get("action") == "remove":
            with transaction.atomic():
                deleted, _ = EnclosurePhoto.objects.filter(enclosure=enclosure).delete()
                if deleted:
                    AuditEvent.objects.create(actor=request.user, action="사육장 대표 사진 삭제", target=enclosure.pk)
            messages.success(request, "대표 사진을 삭제했습니다.")
            return redirect(request.path)
        if form.is_valid():
            with transaction.atomic():
                EnclosurePhoto.objects.update_or_create(enclosure=enclosure, defaults=form.cleaned_data["photo"])
                AuditEvent.objects.create(actor=request.user, action="사육장 대표 사진 등록", target=enclosure.pk)
            messages.success(request, "대표 사진을 저장했습니다.")
            return redirect(request.path)
    return render(request, "enclosure-photo.html", {
        "enclosure": enclosure,
        "photo": EnclosurePhoto.objects.defer("content", "thumbnail").filter(enclosure=enclosure).first(),
        "form": form,
    })
