from django.contrib import admin

from .models import Notification, Profile, RepairRequest, Shop

admin.site.register([Profile, Shop, Notification])


@admin.register(RepairRequest)
class RepairRequestAdmin(admin.ModelAdmin):
    list_display = ["id", "device_name", "shop", "customer", "status", "express", "drop_slot"]
    list_filter = ["status", "express", "shop"]
