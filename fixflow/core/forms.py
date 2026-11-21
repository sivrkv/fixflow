"""Forms: build HTML inputs AND validate what the user typed."""
from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import RegexValidator
from django.utils import timezone

from .models import DEVICE_CHOICES, Profile, RepairRequest, Shop, Status

PHONE_RULE = RegexValidator(r"^\+?\d{10,13}$", "Enter a valid phone number (10-13 digits).")


class RegisterForm(UserCreationForm):
    role = forms.ChoiceField(choices=Profile.ROLE_CHOICES, label="I am a")
    phone = forms.CharField(max_length=15, validators=[PHONE_RULE])

    def save(self, commit=True):
        user = super().save(commit=True)  # creates the User with a hashed password
        Profile.objects.create(user=user, role=self.cleaned_data["role"], phone=self.cleaned_data["phone"])
        return user


class ShopForm(forms.ModelForm):
    device_types = forms.MultipleChoiceField(choices=DEVICE_CHOICES, widget=forms.CheckboxSelectMultiple,
                                             label="Devices you repair")

    class Meta:
        model = Shop
        fields = ["name", "address", "phone", "device_types", "express_fee", "slots_per_hour", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:  # editing: turn "phone,laptop" back into a list for the checkboxes
            self.initial["device_types"] = self.instance.device_types.split(",")

    def clean_device_types(self):
        return ",".join(self.cleaned_data["device_types"])  # list -> "phone,laptop"

    def clean_phone(self):
        PHONE_RULE(self.cleaned_data["phone"])
        return self.cleaned_data["phone"]


class RequestForm(forms.ModelForm):
    class Meta:
        model = RepairRequest
        fields = ["device_type", "device_name", "problem", "drop_slot", "max_budget", "express"]
        widgets = {
            "drop_slot": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "problem": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, shop, **kwargs):
        super().__init__(*args, **kwargs)
        self.shop = shop  # needed by the validators below

    def clean_drop_slot(self):
        slot = self.cleaned_data["drop_slot"]
        now = timezone.now()
        local = timezone.localtime(slot)
        if slot < now + timedelta(hours=1):
            raise forms.ValidationError("Pick a time at least 1 hour from now.")
        if slot > now + timedelta(days=14):
            raise forms.ValidationError("You can book at most 14 days ahead.")
        if local.weekday() == 6:
            raise forms.ValidationError("Shops are closed on Sundays.")
        if not 9 <= local.hour < 18:
            raise forms.ValidationError("Drop-off hours are 9:00 to 18:00.")
        hour_start = local.replace(minute=0, second=0, microsecond=0)
        booked = RepairRequest.objects.filter(
            shop=self.shop, drop_slot__gte=hour_start, drop_slot__lt=hour_start + timedelta(hours=1),
            status__in=[Status.PENDING, Status.ACCEPTED]).count()
        if booked >= self.shop.slots_per_hour:
            raise forms.ValidationError("That hour is fully booked. Please choose another time.")
        return slot

    def clean(self):
        data = super().clean()
        device = data.get("device_type")
        if device and not self.shop.supports(device):
            self.add_error("device_type", f"{self.shop.name} does not repair this type of device.")
        if data.get("express") and self.shop.express_fee <= 0:
            self.add_error("express", "This shop does not offer express service.")
        return data


class DiagnoseForm(forms.Form):
    diagnosis = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), label="What is wrong / what will you do?")
    cost = forms.DecimalField(min_value=0, max_digits=8, decimal_places=2, label="Repair cost (Rs)")
    days = forms.IntegerField(min_value=0, max_value=60, label="Estimated days (0 = same day)")
