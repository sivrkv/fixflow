"""Views: receive a request, talk to the database, return a page."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import DiagnoseForm, RegisterForm, RequestForm, ShopForm
from .models import (DEVICE_CHOICES, FINAL_STATUSES, TRANSITIONS, Notification, RepairRequest,
                     Shop, Status, notify)


def role_of(user):
    """'customer', 'shop' or None (e.g. the admin account has no profile)."""
    profile = getattr(user, "profile", None)
    return profile.role if profile else None


def load_request(user, pk):
    """Fetch a request AND check the user is allowed to see it. Strangers get a 404."""
    obj = get_object_or_404(RepairRequest.objects.select_related("shop", "customer", "customer__profile"), pk=pk)
    if obj.customer_id == user.id:
        return obj, "customer"
    if obj.shop.owner_id == user.id:
        return obj, "shop"
    raise Http404


# ---------- accounts ----------
def register(request):
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome to FixFlow!")
        return redirect("shop_setup" if user.profile.role == "shop" else "shop_list")
    return render(request, "form.html", {"form": form, "title": "Create account", "button": "Register"})


# ---------- shops ----------
@login_required
def shop_setup(request):
    if role_of(request.user) != "shop":
        messages.error(request, "Only service-shop accounts can set up a shop.")
        return redirect("shop_list")
    form = ShopForm(request.POST or None, instance=getattr(request.user, "shop", None))
    if request.method == "POST" and form.is_valid():
        shop = form.save(commit=False)
        shop.owner = request.user
        shop.save()
        messages.success(request, "Shop details saved.")
        return redirect("request_list")
    return render(request, "form.html", {"form": form, "title": "Your shop", "button": "Save shop"})


def shop_list(request):
    shops = Shop.objects.filter(is_active=True)
    device = request.GET.get("device", "")
    if device in dict(DEVICE_CHOICES):
        shops = shops.filter(device_types__contains=device)
    return render(request, "shop_list.html", {"shops": shops, "devices": DEVICE_CHOICES, "picked": device})


def shop_detail(request, pk):
    shop = get_object_or_404(Shop, pk=pk, is_active=True)
    form = None
    can_request = request.user.is_authenticated and role_of(request.user) == "customer"
    if can_request:
        form = RequestForm(request.POST or None, shop=shop)
        if request.method == "POST" and form.is_valid():
            job = form.save(commit=False)
            job.customer = request.user
            job.shop = shop
            job.express_fee = shop.express_fee if job.express else Decimal(0)
            job.save()
            notify(shop.owner, f"New repair request #{job.pk}: {job.device_name} - {job.problem[:80]}", job)
            messages.success(request, "Request sent! The shop will accept or reject it soon.")
            return redirect("request_detail", pk=job.pk)
    return render(request, "shop_detail.html", {"shop": shop, "form": form, "can_request": can_request})


# ---------- repair requests ----------
@login_required
def request_list(request):
    if role_of(request.user) == "shop":
        qs = RepairRequest.objects.filter(shop__owner=request.user)
    else:
        qs = RepairRequest.objects.filter(customer=request.user)
    jobs = list(qs.select_related("shop", "customer"))
    return render(request, "request_list.html", {
        "active": [j for j in jobs if j.status not in FINAL_STATUSES],
        "closed": [j for j in jobs if j.status in FINAL_STATUSES],
    })


@login_required
def request_detail(request, pk):
    job, role = load_request(request.user, pk)
    can_quote = role == "shop" and job.status in (Status.RECEIVED, Status.IN_REPAIR, Status.AWAITING_APPROVAL)
    diagnose_form = DiagnoseForm(initial={
        "diagnosis": job.diagnosis, "cost": job.quoted_cost, "days": job.estimated_days}) if can_quote else None
    return render(request, "request_detail.html", {
        "job": job, "role": role, "actions": job.actions_for(role), "diagnose_form": diagnose_form})


# What to tell the other person after each action: (who gets it, message)
NOTIFY = {
    "accept": ("customer", "{shop} accepted request #{id}. Please bring your device on {slot}."),
    "reject": ("customer", "{shop} cannot take request #{id}. Reason: {note}"),
    "cancel": ("shop", "The customer cancelled request #{id}."),
    "receive": ("customer", "{shop} received your device (request #{id}). A diagnosis will follow."),
    "approve": ("shop", "The customer approved the quote for request #{id}. Go ahead with the repair."),
    "decline": ("shop", "The customer declined the quote for request #{id}. Keep the device ready for return."),
    "ready": ("customer", "Your device is READY at {shop} (request #{id}). Total to pay: Rs {total}."),
    "unrepairable": ("customer", "{shop} cannot repair your device (request #{id}). Reason: {note}. Please collect it."),
    "complete": ("customer", "Request #{id} is complete. Thank you for using FixFlow!"),
    "returned": ("customer", "Your device was handed back. Request #{id} is closed."),
}
NOTE_REQUIRED = {"reject", "unrepairable"}


@login_required
@require_POST
def request_action(request, pk, action):
    if action not in TRANSITIONS:
        raise Http404
    job, role = load_request(request.user, pk)
    note = request.POST.get("note", "").strip()[:300]
    if action in NOTE_REQUIRED and not note:
        messages.error(request, "Please type a reason.")
        return redirect("request_detail", pk=pk)

    extra = {}
    if action in NOTE_REQUIRED:
        extra["shop_note"] = note
    if action == "approve":
        extra["approved_cost"] = F("quoted_cost")  # copied inside the database, atomically
    if action == "complete":
        extra["is_paid"] = True

    try:
        job.apply(action, role, **extra)
    except ValueError as err:
        messages.error(request, str(err))
        return redirect("request_detail", pk=pk)

    target, text = NOTIFY[action]
    person = job.customer if target == "customer" else job.shop.owner
    notify(person, text.format(shop=job.shop.name, id=job.pk, note=note, total=job.total_price,
                               slot=timezone.localtime(job.drop_slot).strftime("%a %d %b, %H:%M")), job)
    messages.success(request, "Done.")
    return redirect("request_detail", pk=pk)


@login_required
@require_POST
def request_diagnose(request, pk):
    job, role = load_request(request.user, pk)
    form = DiagnoseForm(request.POST)
    if role != "shop":
        messages.error(request, "Only the shop can send a diagnosis.")
        return redirect("request_detail", pk=pk)
    if not form.is_valid():
        messages.error(request, "Please check the diagnosis form (cost and days must be valid numbers).")
        return redirect("request_detail", pk=pk)

    cost, days = form.cleaned_data["cost"], form.cleaned_data["days"]
    # Small-job shortcut: if the quote fits the customer's budget (or an amount they already approved),
    # start the repair right away. Otherwise the customer must approve first.
    limit = max(job.approved_cost or Decimal(0), job.max_budget or Decimal(0))
    auto = limit > 0 and cost <= limit
    new_status = Status.IN_REPAIR if auto else Status.AWAITING_APPROVAL

    updated = RepairRequest.objects.filter(
        pk=job.pk, status__in=[Status.RECEIVED, Status.IN_REPAIR, Status.AWAITING_APPROVAL]).update(
        status=new_status, diagnosis=form.cleaned_data["diagnosis"], quoted_cost=cost, estimated_days=days,
        approved_cost=cost if auto else job.approved_cost, updated_at=timezone.now())
    if not updated:
        messages.error(request, "You can only send a quote while the device is with you and not yet repaired.")
        return redirect("request_detail", pk=pk)

    job.refresh_from_db()
    if auto:
        notify(job.customer, f"{job.shop.name} diagnosed request #{job.pk}: Rs {cost}, about {days} day(s). "
                             f"It is within your budget so the repair has started.", job)
    else:
        notify(job.customer, f"{job.shop.name} needs your approval for request #{job.pk}: Rs {cost}, about {days} "
                             f"day(s). Open the request to approve or decline (or call {job.shop.phone}).", job)
    messages.success(request, "Diagnosis sent to the customer." if not auto else "Within budget - repair started.")
    return redirect("request_detail", pk=pk)


# ---------- notifications ----------
@login_required
def notifications(request):
    qs = Notification.objects.filter(user=request.user)
    items = list(qs[:50])                       # evaluate first, then mark as read
    qs.filter(is_read=False).update(is_read=True)
    return render(request, "notifications.html", {"items": items})
