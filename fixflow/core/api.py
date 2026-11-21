"""Small read-only JSON API built with Django REST Framework."""
from django.db.models import Q
from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification, RepairRequest, Shop


class ShopSerializer(serializers.ModelSerializer):   # model -> JSON converter
    class Meta:
        model = Shop
        fields = ["id", "name", "address", "phone", "device_types", "express_fee"]


class RequestSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    total_price = serializers.DecimalField(max_digits=9, decimal_places=2, read_only=True)

    class Meta:
        model = RepairRequest
        fields = ["id", "device_name", "problem", "status", "status_label", "drop_slot", "express",
                  "quoted_cost", "total_price", "estimated_days"]


class ShopViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ShopSerializer

    def get_queryset(self):
        shops = Shop.objects.filter(is_active=True)
        device = self.request.query_params.get("device")   # /api/shops/?device=phone
        return shops.filter(device_types__contains=device) if device else shops


class MyRequestViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):   # users only ever see THEIR OWN requests
        u = self.request.user
        return RepairRequest.objects.filter(Q(customer=u) | Q(shop__owner=u))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def unread_count(request):
    return Response({"unread": Notification.objects.filter(user=request.user, is_read=False).count()})
