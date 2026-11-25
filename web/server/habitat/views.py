import uuid
from datetime import timedelta
from functools import wraps
from urllib.parse import urlencode
from django.core.paginator import Paginator
from django.db.models import Q
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.forms import SetPasswordForm, PasswordChangeForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from .access import allowed_enclosures, manageable_accounts, visible_accounts
from .forms import (
    LoginForm,
    AccountForm,
    ProfileForm,
    StoreForm,
    EnclosureForm,
    SiteForm,
)
from .models import User, Store, Enclosure, SiteSettings, AuditEvent
from .forms import GatewayForm
from edge.models import Gateway


class SignIn(LoginView):
    template_name = "login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session.set_expiry(
            timezone.now() + timedelta(days=30) if form.cleaned_data["remember_device"] else 0
        )
        return response


def roles(*allowed):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.role not in allowed:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorate


def activation_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    # Fragments never reach proxy/access logs. Browser transfers these to POST.
    return f"{settings.PUBLIC_ORIGIN}/activate/#uid={uid}&token={token}"


@require_GET
def index(request, document="index.html"):
    try:
        return FileResponse(
            (settings.FRONTEND_DIR / document).open("rb"),
            content_type="text/html; charset=utf-8",
        )
    except FileNotFoundError:
        return render(
            request,
            "message.html",
            {"title": "화면 준비 중", "description": "잠시 후 다시 접속해 주세요."},
            status=503,
        )


@require_GET
def session(request):
    user = request.user
    site = SiteSettings.objects.get(pk=1)
    return JsonResponse(
        {
            "csrfToken": get_token(request),
            "user": {
                "id": str(user.pk),
                "name": str(user),
                "loginId": user.username,
                "role": user.role,
                "roleLabel": user.get_role_display(),
                "storeName": str(user.store) if user.store_id else "전체 매장",
            },
            "enclosures": list(allowed_enclosures(user).values("id", "name")),
            "site": {"title": site.title, "notice": site.notice},
        }
    )


@require_POST
def sign_out(request):
    actor = request.user
    AuditEvent.objects.create(actor=actor, action="로그아웃", target=actor.username)
    logout(request)
    return redirect("/login/")


@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def activate(request):
    form = None
    error = ""
    if request.method == "POST":
        with transaction.atomic():
            try:
                user = User.objects.get(
                    pk=force_str(urlsafe_base64_decode(request.POST.get("uid", ""))),
                    is_active=True,
                )
            except (
                ValueError,
                TypeError,
                OverflowError,
                User.DoesNotExist,
                UnicodeDecodeError,
            ):
                user = None
            if user is None or not default_token_generator.check_token(
                user, request.POST.get("token", "")
            ):
                error = "설정 링크가 만료되었거나 이미 사용되었습니다. 관리자에게 새 링크를 요청하세요."
            else:
                form = SetPasswordForm(user, request.POST)
                if form.is_valid():
                    form.save()
                    user.session_generation = uuid.uuid4()
                    user.save(update_fields=["session_generation"])
                    AuditEvent.objects.create(
                        actor=user, action="비밀번호 설정", target=user.username
                    )
                    messages.success(
                        request, "비밀번호가 설정되었습니다. 로그인해 주세요."
                    )
                    return redirect("/login/")
    return render(
        request,
        "activate.html",
        {
            "form": form,
            "error": error,
            "uid": request.POST.get("uid", ""),
            "token": request.POST.get("token", ""),
        },
        status=400 if error else 200,
    )


@require_http_methods(["GET", "POST"])
@sensitive_post_parameters()
def profile(request):
    user = request.user
    changing_password = request.POST.get("action") == "password"
    profile_form = ProfileForm(
        request.POST if request.method == "POST" and not changing_password else None,
        instance=user,
    )
    password_form = PasswordChangeForm(
        user, request.POST if request.method == "POST" and changing_password else None
    )
    if request.method == "POST":
        form = password_form if changing_password else profile_form
        if form.is_valid():
            with transaction.atomic():
                saved = form.save()
                if not changing_password and user.role != User.Role.OWNER:
                    saved.email = saved.username
                saved.session_generation = uuid.uuid4()
                saved.save()
                AuditEvent.objects.create(
                    actor=user,
                    action="비밀번호 변경" if changing_password else "내 계정 변경",
                    target=saved.username,
                )
            logout(request)
            messages.success(request, "변경되었습니다. 새 정보로 다시 로그인해 주세요.")
            return redirect("/login/")
    return render(
        request,
        "profile.html",
        {"profile_form": profile_form, "password_form": password_form},
    )


@require_GET
def manage(request):
    actor = request.user
    scope = {
        User.Role.OWNER: ("사이트·계정 관리", "전체 매장과 관리자·사용자의 접속 권한을 관리합니다."),
        User.Role.MANAGER: ("매장·사용자 관리", "소속 매장의 사용자와 사육장을 확인합니다. 사용자 계정과 담당 사육장을 관리할 수 있습니다."),
        User.Role.USER: ("내 배정 정보", "내 계정과 배정된 사육장을 확인합니다. 배정 변경은 소속 관리자에게 요청하세요."),
    }
    title, description = scope[actor.role]
    stores = Store.objects.all() if actor.role == User.Role.OWNER else Store.objects.filter(pk=actor.store_id)
    accounts = visible_accounts(actor).select_related("store")
    keyword = request.GET.get("q", "").strip()[:80]
    role = request.GET.get("role", "")
    status = request.GET.get("status", "")
    store_id = request.GET.get("store", "")
    # Filters always narrow the server-authorized account set.
    if keyword:
        accounts = accounts.filter(Q(display_name__icontains=keyword) | Q(username__icontains=keyword))
    if role in User.Role.values:
        accounts = accounts.filter(role=role)
    else:
        role = ""
    if status == "active":
        accounts = accounts.filter(is_active=True).exclude(password__startswith="!")
    elif status == "pending":
        accounts = accounts.filter(is_active=True, password__startswith="!")
    elif status == "inactive":
        accounts = accounts.filter(is_active=False)
    else:
        status = ""
    if actor.role == User.Role.OWNER and store_id.isascii() and store_id.isdecimal() and len(store_id) <= 18:
        accounts = accounts.filter(store_id=int(store_id))
    else:
        store_id = ""
    page = Paginator(accounts.order_by("-date_joined", "-pk"), 20).get_page(request.GET.get("page"))
    page_accounts = list(page.object_list)
    return render(
        request,
        "manage.html",
        {
            "gateways": (
                Gateway.objects.select_related("store").all()
                if request.user.role == "owner"
                else (
                    Gateway.objects.select_related("store").filter(
                        store_id=request.user.store_id
                    )
                    if request.user.role == "manager"
                    else []
                )
            ),
            "management_title": title,
            "management_description": description,
            "accounts": page_accounts,
            "account_page": page,
            "account_filters": {"q": keyword, "role": role, "status": status, "store": store_id},
            "account_query": urlencode({"q": keyword, "role": role, "status": status, "store": store_id}),
            "editable_ids": list(
                manageable_accounts(actor).filter(pk__in=[item.pk for item in page_accounts]).values_list("pk", flat=True)
            ),
            "stores": stores.order_by("name", "pk"),
            "enclosures": allowed_enclosures(actor).select_related("store").order_by("store__name", "name", "pk"),
            "events": (
                AuditEvent.objects.all()[:15]
                if request.user.role == User.Role.OWNER
                else []
            ),
        },
    )


@roles("owner", "manager")
@require_http_methods(["GET", "POST"])
def account_edit(request, account_id=None):
    target = (
        get_object_or_404(manageable_accounts(request.user), pk=account_id)
        if account_id
        else User()
    )
    form = AccountForm(request.POST or None, instance=target, actor=request.user)
    link = None
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            is_new = target.pk is None
            target = form.save(commit=False)
            target.session_generation = uuid.uuid4()
            if is_new:
                target.set_unusable_password()
            target.save()
            form.save_m2m()
            AuditEvent.objects.create(
                actor=request.user,
                action="계정 생성" if is_new else "계정·권한 변경",
                target=target.username,
            )
            if is_new:
                link = activation_link(target)
            else:
                messages.success(request, "계정을 변경하고 기존 접속을 종료했습니다.")
                return redirect("/manage/")
    return render(
        request,
        "edit.html",
        {
            "form": form,
            "title": "계정 추가" if account_id is None else "계정 수정",
            "link": link,
            "target": target,
            "can_reset": bool(account_id),
        },
    )


@roles("owner", "manager")
@require_POST
def reset_account(request, account_id):
    with transaction.atomic():
        target = get_object_or_404(
            manageable_accounts(request.user), pk=account_id, is_active=True
        )
        target.set_unusable_password()
        target.session_generation = uuid.uuid4()
        target.save(update_fields=["password", "session_generation"])
        AuditEvent.objects.create(
            actor=request.user,
            action="비밀번호 재설정 링크 발급",
            target=target.username,
        )
        link = activation_link(target)
    return render(
        request,
        "edit.html",
        {"title": "비밀번호 재설정", "link": link, "target": target},
    )


@roles("owner")
@require_http_methods(["GET", "POST"])
def store_edit(request, store_id=None):
    store = get_object_or_404(Store, pk=store_id) if store_id else Store()
    form = StoreForm(request.POST or None, instance=store)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            AuditEvent.objects.create(
                actor=request.user, action="매장 정보 변경", target=store.name
            )
        return redirect("/manage/")
    return render(
        request,
        "edit.html",
        {"title": "매장 수정" if store_id else "매장 추가", "form": form},
    )


@roles("owner")
@require_http_methods(["GET", "POST"])
def enclosure_edit(request, enclosure_id):
    item = get_object_or_404(Enclosure, pk=enclosure_id)
    form = EnclosureForm(instance=item)
    if request.method == "POST":
        with transaction.atomic():
            item = get_object_or_404(Enclosure, pk=enclosure_id)
            previous_store = item.store_id
            form = EnclosureForm(request.POST, instance=item)
            if form.is_valid():
                item = form.save()
                if item.store_id != previous_store:
                    item.user_set.clear()
                    User.objects.filter(
                        store_id__in=[previous_store, item.store_id]
                    ).update(session_generation=uuid.uuid4())
                AuditEvent.objects.create(
                    actor=request.user, action="사육장 정보 변경", target=item.name
                )
                return redirect("/manage/")
    return render(request, "edit.html", {"title": "사육장 기본 정보", "form": form, "photo_enclosure": item})


@roles("owner")
@require_http_methods(["GET", "POST"])
def site_edit(request):
    site = SiteSettings.objects.get(pk=1)
    form = SiteForm(request.POST or None, instance=site)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            AuditEvent.objects.create(
                actor=request.user, action="사이트 설정 변경", target=site.title
            )
        messages.success(request, "사이트 설정을 저장했습니다.")
        return redirect("/manage/")
    return render(request, "edit.html", {"title": "사이트 설정", "form": form})


def csrf_failure(request, reason=""):
    return render(
        request,
        "message.html",
        {
            "title": "화면을 새로 열어 주세요",
            "description": "접속 확인 정보가 만료되었습니다. 로그인 화면을 다시 열고 시도하세요.",
        },
        status=403,
    )


@roles("owner")
@require_http_methods(["GET", "POST"])
def gateway_edit(request, gateway_id):
    gateway = get_object_or_404(Gateway, pk=gateway_id)
    form = GatewayForm(request.POST or None, instance=gateway)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            AuditEvent.objects.create(
                actor=request.user,
                action="Pi 수신 설정 변경",
                target=gateway.edge_gateway_id,
            )
        return redirect("/manage/")
    return render(
        request,
        "edit.html",
        {"title": f"Pi 수신 설정 · {gateway.edge_gateway_id}", "form": form},
    )
