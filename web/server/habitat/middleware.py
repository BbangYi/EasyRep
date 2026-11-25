from django.contrib.auth import logout
from urllib.parse import urlencode
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.cache import add_never_cache_headers
from .models import SiteSettings


class AccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # This namespace uses a Pi bearer credential, never a browser cookie.
        if request.path.startswith("/v1/"):
            response = self.get_response(request)
            add_never_cache_headers(response)
            return response
        public = request.path in ("/login/", "/activate/", "/demo", "/demo/") or request.path.startswith(
            ("/auth-static/", "/brand/", "/textures/", "/assets/", "/enclosures/")
        )
        if request.user.is_authenticated and request.session.get("generation") != str(
            request.user.session_generation
        ):
            logout(request)
            request.session["ended_elsewhere"] = True
        if not public and not request.user.is_authenticated:
            response = (
                JsonResponse(
                    {"error": "session_ended", "message": "로그인이 필요합니다."},
                    status=401,
                )
                if request.path.startswith("/api/")
                else redirect("/login/?" + urlencode({"next": request.get_full_path()}))
            )
        elif (
            request.user.is_authenticated
            and request.user.role != "owner"
            and request.path != "/logout/"
            and SiteSettings.objects.filter(pk=1, maintenance=True).exists()
        ):
            response = (
                JsonResponse({"error": "maintenance"}, status=503)
                if request.path.startswith("/api/")
                else render(
                    request,
                    "message.html",
                    {
                        "title": "사이트 점검 중",
                        "description": "점검이 끝난 뒤 다시 접속해 주세요.",
                    },
                    status=503,
                )
            )
        else:
            response = self.get_response(request)
        add_never_cache_headers(response)
        response["Referrer-Policy"] = "same-origin"
        response["X-Content-Type-Options"] = "nosniff"
        return response
