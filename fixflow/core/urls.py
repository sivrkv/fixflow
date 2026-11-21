"""URLs for the core app: address -> view function."""
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("", views.shop_list, name="shop_list"),
    path("register/", views.register, name="register"),
    path("login/", LoginView.as_view(template_name="form.html",
                                     extra_context={"title": "Login", "button": "Login"}), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("shops/<int:pk>/", views.shop_detail, name="shop_detail"),
    path("my-shop/", views.shop_setup, name="shop_setup"),
    path("requests/", views.request_list, name="request_list"),
    path("requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("requests/<int:pk>/do/<str:action>/", views.request_action, name="request_action"),
    path("requests/<int:pk>/diagnose/", views.request_diagnose, name="request_diagnose"),
    path("notifications/", views.notifications, name="notifications"),
]
