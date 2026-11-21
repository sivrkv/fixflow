"""Run: python manage.py seed_demo   -> creates demo users so you can try the app instantly."""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from core.models import Profile, Shop


class Command(BaseCommand):
    help = "Create demo shop + customer accounts (password: demo12345)"

    def handle(self, *args, **options):
        for username, role, phone in [("shopowner", "shop", "9876543210"), ("customer", "customer", "9123456780")]:
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password("demo12345")   # set_password hashes it; never store raw passwords
                user.save()
                Profile.objects.create(user=user, role=role, phone=phone)
        owner = User.objects.get(username="shopowner")
        Shop.objects.get_or_create(owner=owner, defaults=dict(
            name="QuickFix Repairs", address="12 Market Road, Secunderabad", phone="9876543210",
            device_types="phone,laptop,speaker,tv", express_fee=300, slots_per_hour=3))
        self.stdout.write(self.style.SUCCESS("Demo ready: shopowner / customer, password demo12345"))
