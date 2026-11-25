from django.urls import path, re_path
from edge import views as edge_views, queries
from edge.overview import overview
from habitat import views, photos, husbandry, camera_ir

urlpatterns = [
    path("", views.index),
    path("index.html", views.index),
    path("demo/", views.index, {"document": "demo.html"}),
    path("login/", views.SignIn.as_view()),
    path("logout/", views.sign_out),
    path("activate/", views.activate),
    path("profile/", views.profile),
    path("api/session/", views.session),
    path("v1/edge/sync", edge_views.sync),
    path("v1/edge/health", edge_views.health),
    re_path(r"^v1/.*$", edge_views.unknown),
    path("api/enclosures/", queries.enclosures),
    path("api/enclosures/<slug:enclosure_id>/", queries.current),
    path("api/enclosures/<slug:enclosure_id>/history/", queries.history),
    path("api/enclosures/<slug:enclosure_id>/overview/", overview),
    path("api/enclosures/<slug:enclosure_id>/records/", queries.records),
    path("api/enclosures/<slug:enclosure_id>/commands/", queries.commands),
    path("api/enclosures/<slug:enclosure_id>/photo/", photos.read),
    path("api/enclosures/<slug:enclosure_id>/care/", husbandry.care_records),
    path("api/camera/", camera_ir.cameras),
    path("api/camera/ir/", camera_ir.ir_status),
    path("api/camera/ir/command/", camera_ir.ir_command),
    path("api/camera/hls/<slug:camera_id>/index.m3u8", camera_ir.playlist),
    path("api/camera/hls/<slug:camera_id>/<uuid:session_id>/<int:sequence>.ts", camera_ir.segment),
    path("api/enclosures/<slug:enclosure_id>/camera/", camera_ir.cameras),
    path("api/enclosures/<slug:enclosure_id>/camera/ir/", camera_ir.ir_status),
    path("api/enclosures/<slug:enclosure_id>/camera/ir/command/", camera_ir.ir_command),
    path("api/enclosures/<slug:enclosure_id>/camera/hls/<slug:camera_id>/index.m3u8", camera_ir.playlist),
    path("api/enclosures/<slug:enclosure_id>/camera/hls/<slug:camera_id>/<uuid:session_id>/<int:sequence>.ts", camera_ir.segment),
    re_path(r"^api/.*$", edge_views.unknown),
    path("manage/gateways/<uuid:gateway_id>/", views.gateway_edit),
    path("manage/", views.manage),
    path("manage/enclosures/new/", husbandry.enclosure_create),
    path("manage/enclosures/<slug:enclosure_id>/care/new/", husbandry.care_create),
    path("manage/enclosures/<slug:enclosure_id>/care/<uuid:record_id>/void/", husbandry.care_void),
    path("manage/accounts/new/", views.account_edit),
    path("manage/accounts/<int:account_id>/", views.account_edit),
    path("manage/accounts/<int:account_id>/reset/", views.reset_account),
    path("manage/stores/new/", views.store_edit),
    path("manage/stores/<int:store_id>/", views.store_edit),
    path("manage/enclosures/<slug:enclosure_id>/", views.enclosure_edit),
    path("manage/enclosures/<slug:enclosure_id>/photo/", photos.edit),
    path("manage/site/", views.site_edit),
]

# Local preview only; production Nginx serves these explicitly allowed assets.
from django.conf import settings
from django.conf.urls.static import static

if settings.DEBUG:
    for directory in ("assets", "brand", "textures", "enclosures"):
        urlpatterns += static(
            f"/{directory}/", document_root=settings.FRONTEND_DIR / directory
        )
