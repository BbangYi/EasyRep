import re
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import User, Store, Enclosure, SiteSettings


class LoginForm(AuthenticationForm):
    remember_device = forms.BooleanField(
        label="이 기기에서 30일간 로그인 유지", required=False,
        help_text="개인 기기에서만 선택하세요. 공용 기기에서는 선택하지 마세요.",
    )
    username = forms.CharField(
        label="이메일 또는 관리자 ID",
        max_length=254,
        widget=forms.TextInput(
            attrs={
                "autofocus": True,
                "autocomplete": "username",
                "autocapitalize": "none",
            }
        ),
    )
    error_messages = {
        "invalid_login": "로그인 정보를 확인해 주세요.",
        "inactive": "로그인 정보를 확인해 주세요.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().casefold()


class AccountForm(forms.ModelForm):
    username = forms.EmailField(label="로그인 이메일", max_length=254)

    class Meta:
        model = User
        fields = [
            "display_name",
            "username",
            "role",
            "store",
            "enclosures",
            "is_active",
        ]
        labels = {"is_active": "접속 허용"}
        widgets = {"enclosures": forms.CheckboxSelectMultiple()}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.fields["role"].choices = [
            (User.Role.MANAGER, "매장 관리자"),
            (User.Role.USER, "사용자"),
        ]
        self.fields["store"].required = True
        self.fields["enclosures"].queryset = Enclosure.objects.select_related("store")
        self.fields["enclosures"].help_text = (
            "사용자에게는 선택한 사육장만 표시됩니다. 매장 관리자는 소속 매장 전체를 봅니다."
        )
        if actor.role == User.Role.MANAGER:
            self.fields["role"].choices = [(User.Role.USER, "사용자")]
            self.fields["store"].queryset = Store.objects.filter(pk=actor.store_id)
            self.fields["store"].initial = actor.store_id
            self.fields["enclosures"].queryset = self.fields[
                "enclosures"
            ].queryset.filter(store_id=actor.store_id)

    def clean_username(self):
        value = self.cleaned_data["username"].strip().casefold()
        if (
            User.objects.filter(username__iexact=value)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("이미 사용 중인 로그인 ID입니다.")
        return value

    def clean(self):
        data = super().clean()
        store = data.get("store")
        if store and any(
            item.store_id != store.pk for item in data.get("enclosures", [])
        ):
            self.add_error("enclosures", "소속 매장의 사육장만 선택하세요.")
        if data.get("role") == User.Role.MANAGER:
            data["enclosures"] = Enclosure.objects.none()
        return data

    def save(self, commit=True):
        self.instance.email = self.cleaned_data["username"]
        return super().save(commit)


class ProfileForm(forms.ModelForm):
    current_password = forms.CharField(
        label="현재 비밀번호",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    class Meta:
        model = User
        fields = ["display_name", "username"]

    def clean_current_password(self):
        value = self.cleaned_data["current_password"]
        if not self.instance.check_password(value):
            raise forms.ValidationError("현재 비밀번호를 확인하세요.")
        return value

    def clean_username(self):
        value = self.cleaned_data["username"].strip().casefold()
        if self.instance.role == User.Role.OWNER:
            if not re.fullmatch(r"[a-z0-9][a-z0-9._@+-]{2,149}", value):
                raise forms.ValidationError(
                    "영문 소문자·숫자·기호 . _ @ + - 로 3~150자를 입력하세요."
                )
        else:
            forms.EmailField().clean(value)
        if (
            User.objects.filter(username__iexact=value)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("이미 사용 중인 로그인 ID입니다.")
        return value


class StoreForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = ["name", "region"]


class EnclosureForm(forms.ModelForm):
    class Meta:
        model = Enclosure
        fields = ["name", "store", "species", "location"]

    def clean_store(self):
        store = self.cleaned_data["store"]
        if (
            self.instance.pk
            and (hasattr(self.instance, "edge_binding") or self.instance.care_records.exists())
            and store.pk != self.instance.store_id
        ):
            raise forms.ValidationError(
                "장치 연결 또는 관리 기록이 있는 사육장은 소속을 변경할 수 없습니다. 기존 이력을 보존해 주세요."
            )
        return store


class SiteForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ["title", "notice", "maintenance"]
        widgets = {"notice": forms.Textarea(attrs={"rows": 3})}


class GatewayForm(forms.ModelForm):
    from edge.models import Gateway

    class Meta:
        from edge.models import Gateway

        model = Gateway
        fields = ["active", "allow_simulation", "offline_after_s"]
        help_texts = {
            "active": "끄면 이 Pi의 데이터 수신이 거절됩니다.",
            "allow_simulation": "실제 센서 연결 전 검증할 때만 허용하세요.",
        }
