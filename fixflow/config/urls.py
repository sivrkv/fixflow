"""Root URL table: sends each address to the right place."""
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core import api

router = DefaultRouter()                       # auto-creates list/detail URLs
router.register("shops", api.ShopViewSet, basename="shop")
router.register("requests", api.MyRequestViewSet, basename="request")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/unread/", api.unread_count, name="api_unread"),  # must come before the router include
    path("api/", include(router.urls)),
    path("", include("core.urls")),            # everything else is handled by our app
]
