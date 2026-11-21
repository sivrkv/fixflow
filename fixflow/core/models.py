"""Database tables. Each class = one table, each attribute = one column."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

DEVICE_CHOICES = [
    ("phone", "Phone"), ("laptop", "Laptop"), ("desktop", "Desktop PC"),
    ("tablet", "Tablet"), ("speaker", "Speaker / Audio"), ("tv", "TV"), ("other", "Other"),
]


class Profile(models.Model):
    """Extra info for a User: are they a customer or a shop owner?"""
    ROLE_CHOICES = [("customer", "Customer"), ("shop", "Service shop")]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    phone = models.CharField(max_length=15)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class Shop(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name="shop")
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=200)
    phone = models.CharField(max_length=15)
    device_types = models.CharField(max_length=100)  # "phone,laptop" (keys never overlap, so 'contains' is safe)
    express_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0,
                                      validators=[MinValueValidator(0)],
                                      help_text="Extra charge for priority repair. 0 = no express service.")
    slots_per_hour = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1)],
                                                      help_text="How many drop-offs you can handle per hour.")
    is_active = models.BooleanField(default=True)

    def supports(self, device):
        return device in self.device_types.split(",")

    def device_labels(self):
        names = dict(DEVICE_CHOICES)
        return ", ".join(names[d] for d in self.device_types.split(",") if d in names)

    def __str__(self):
        return self.name


class Status(models.TextChoices):
    PENDING = "pending", "Waiting for shop"
    ACCEPTED = "accepted", "Accepted - bring the device"
    REJECTED = "rejected", "Rejected by shop"
    CANCELLED = "cancelled", "Cancelled"
    RECEIVED = "received", "Device received - diagnosing"
    AWAITING_APPROVAL = "awaiting_approval", "Waiting for your approval"
    IN_REPAIR = "in_repair", "Being repaired"
    READY = "ready", "Ready for collection"
    COMPLETED = "completed", "Completed"
    DECLINED = "declined", "Quote declined - collect device"
    UNREPAIRABLE = "unrepairable", "Cannot be repaired - collect device"
    RETURNED = "returned", "Returned unrepaired"


FINAL_STATUSES = {Status.REJECTED, Status.CANCELLED, Status.COMPLETED, Status.RETURNED}

# The state machine: action -> (allowed current statuses, new status, who may do it)
# Anything not listed here is IMPOSSIBLE, which removes a whole class of bugs.
TRANSITIONS = {
    "accept":       ({Status.PENDING},                         Status.ACCEPTED,     "shop"),
    "reject":       ({Status.PENDING, Status.ACCEPTED},        Status.REJECTED,     "shop"),
    "cancel":       ({Status.PENDING, Status.ACCEPTED},        Status.CANCELLED,    "customer"),
    "receive":      ({Status.ACCEPTED},                        Status.RECEIVED,     "shop"),
    "approve":      ({Status.AWAITING_APPROVAL},               Status.IN_REPAIR,    "customer"),
    "decline":      ({Status.AWAITING_APPROVAL},               Status.DECLINED,     "customer"),
    "ready":        ({Status.IN_REPAIR},                       Status.READY,        "shop"),
    "unrepairable": ({Status.RECEIVED, Status.IN_REPAIR},      Status.UNREPAIRABLE, "shop"),
    "complete":     ({Status.READY},                           Status.COMPLETED,    "shop"),
    "returned":     ({Status.DECLINED, Status.UNREPAIRABLE},   Status.RETURNED,     "shop"),
}

# Button text, CSS style, and whether the user must type a reason.
ACTION_INFO = {
    "accept": ("Accept request", "ok", False),
    "reject": ("Reject", "danger", True),
    "cancel": ("Cancel request", "danger", False),
    "receive": ("Mark device received", "ok", False),
    "approve": ("Approve quote", "ok", False),
    "decline": ("Decline quote", "danger", False),
    "ready": ("Repair done - ready for pickup", "ok", False),
    "unrepairable": ("Cannot be repaired", "danger", True),
    "complete": ("Paid & collected", "ok", False),
    "returned": ("Device handed back", "ok", False),
}


class RepairRequest(models.Model):
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="repairs")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="repairs")
    device_type = models.CharField(max_length=10, choices=DEVICE_CHOICES)
    device_name = models.CharField(max_length=100, help_text="Brand and model, e.g. Dell Inspiron 15")
    problem = models.TextField(help_text="What is wrong? e.g. speaker has no sound")
    drop_slot = models.DateTimeField(help_text="When will you bring the device?")
    max_budget = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True,
                                     validators=[MinValueValidator(0)],
                                     help_text="Optional. If the quote is within this amount the shop starts immediately.")
    express = models.BooleanField(default=False, help_text="Pay extra to get it done first.")
    express_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)  # copied from shop at booking time
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    diagnosis = models.TextField(blank=True)
    quoted_cost = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    approved_cost = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    estimated_days = models.PositiveSmallIntegerField(null=True, blank=True)
    shop_note = models.CharField(max_length=300, blank=True)
    is_paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-express", "drop_slot"]  # express jobs float to the top

    def __str__(self):
        return f"#{self.pk} {self.device_name}"

    @property
    def total_price(self):
        base = self.approved_cost if self.approved_cost is not None else (self.quoted_cost or Decimal(0))
        return base + self.express_fee

    @property
    def is_final(self):
        return self.status in FINAL_STATUSES

    def actions_for(self, role):
        """Buttons this role may press right now."""
        return [
            {"name": n, "label": ACTION_INFO[n][0], "style": ACTION_INFO[n][1], "needs_note": ACTION_INFO[n][2]}
            for n, (allowed, _new, who) in TRANSITIONS.items()
            if who == role and self.status in allowed
        ]

    def apply(self, action, role, **extra):
        """Move to the next status safely. Raises ValueError if not allowed."""
        allowed, new_status, who = TRANSITIONS[action]
        if role != who:
            raise ValueError("You are not allowed to do that.")
        # Compare-and-set: the UPDATE only matches if the status is STILL what we expect,
        # so a double-click or two browser tabs can never apply an action twice.
        done = RepairRequest.objects.filter(pk=self.pk, status__in=allowed).update(
            status=new_status, updated_at=timezone.now(), **extra)
        if not done:
            raise ValueError("This request has already moved on - please refresh the page.")
        self.refresh_from_db()


class Notification(models.Model):
    """In-app message. (Swap for SMS/email later by changing notify() only.)"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    request = models.ForeignKey(RepairRequest, on_delete=models.CASCADE, null=True, blank=True)
    message = models.CharField(max_length=300)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


def notify(user, message, request=None):
    Notification.objects.create(user=user, message=message[:300], request=request)
