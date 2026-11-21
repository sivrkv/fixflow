# FixFlow — Build a Device-Repair Marketplace in Django (Beginner Guide, 3–4 hours)

**What you will have at the end:** a working website where customers describe a broken device, pick a shop and a drop-off slot; shops accept/reject, receive the device, send a diagnosis and quote, get approval (or auto-approval inside a budget), repair, and notify the customer when it is ready. Includes express (pay-extra) service, a JSON API, a notification badge, and automated tests.

**Stack:** Python 3.10+ · Django 5 · Django REST Framework · SQLite (default) or MySQL · plain HTML/CSS/JS.
**You need:** Python knowledge (functions, classes, dicts, f-strings). **No Django knowledge required.**

---

## 0. How to use this guide

| Time | What you do |
|---|---|
| 0:00 – 0:30 | Read **Part 2 (Django fundamentals)**. Skim, don't memorise; come back when stuck. |
| 0:30 – 0:45 | **Part 3**: setup (virtualenv, project, app). |
| 0:45 – 2:45 | **Part 4**: type the files in order (Steps 1-9). Run the checkpoint after each step. |
| 2:45 – 3:15 | **Part 5**: run the app, walk through the whole repair flow with two accounts. |
| 3:15 – 3:45 | **Part 6-7**: tests, edge cases, MySQL switch, next steps. |

**Rule for learning:** type the code yourself (don't paste) for at least `models.py`, `views.py` and one template. Typing is where Django "clicks".

The finished project is also provided as a ZIP. If something breaks, compare your file with the ZIP's file.

---

## 1. What you are building

### 1.1 The people
- **Customer** – searches shops, sends a repair request (what is wrong + when they will come), approves quotes, picks up the device.
- **Shop owner** – accepts/rejects, receives the device, diagnoses, quotes, repairs, marks ready, collects payment.

### 1.2 The life of one repair (state machine)

```
 PENDING ──accept──► ACCEPTED ──receive──► RECEIVED ──diagnose──► AWAITING_APPROVAL ──approve──► IN_REPAIR ──ready──► READY ──complete──► COMPLETED
    │                   │                     │  ▲                     │  ▲                         │
  reject/cancel     reject/cancel        unrepairable│                decline    (shop can revise quote any time before done)
    ▼                   ▼                     ▼  │                     ▼                            ▼
 REJECTED/CANCELLED                      UNREPAIRABLE ──returned──► RETURNED        DECLINED ──returned──► RETURNED
 
 Shortcut: if the quote ≤ customer's budget (or ≤ an amount they already approved) → RECEIVED jumps straight to IN_REPAIR (no waiting).
```

Why a **state machine**? Every bug in "order/booking" apps is "something happened in the wrong order". We list the *only* legal moves in one dictionary (`TRANSITIONS`) — everything else is impossible by design.

### 1.3 Your original idea → where it lives in code

| Your requirement | Implemented as |
|---|---|
| Customer tells shop the problem (speaker not working…) | `RepairRequest.problem` + `RequestForm` |
| Shop accepts / rejects (can/cannot do the work) | actions `accept` / `reject` (reason required) |
| Book a slot to come to the shop | `drop_slot` with validation (hours, Sundays, capacity) |
| Collect device, small jobs fixed fast | budget auto-approval → `IN_REPAIR` immediately |
| Basic diagnosis + estimated time | `DiagnoseForm` → `diagnosis`, `quoted_cost`, `estimated_days` |
| Call customer if diagnosis was wrong, ask to proceed | "Update quote" from `IN_REPAIR` → `AWAITING_APPROVAL` + notification with phone numbers |
| Pay extra for ASAP | `express` + `Shop.express_fee` (priority sorting, fee added to total) |
| Notify when ready | `Notification` + 🔔 badge (API polling) |

---

## 2. Django fundamentals (the 30-minute crash course)

### 2.1 How a page is produced (MVT)
Django = **M**odel · **V**iew · **T**emplate.
```
Browser ──URL──► urls.py ──picks──► view (function) ──asks──► model (database)
                                        │                         │
                                        └──► template (HTML) ◄────┘ data
                                        ▼
                                   HTML sent back
```
- **Model** – a Python class = a database table.
- **View** – a Python function: takes `request`, returns a response (usually a rendered template or a redirect).
- **Template** – HTML with placeholders.
- **URLconf** – a list mapping addresses to views.

### 2.2 Project vs app
- **Project** (`config/`) = the whole site's settings + root URLs.
- **App** (`core/`) = a feature package (models, views…). Big sites have many apps; ours has one (keeps it simple).

```
fixflow/
├── manage.py            # the command-line tool (runserver, migrate, test…)
├── requirements.txt
├── config/              # PROJECT: settings.py, urls.py, wsgi.py
├── core/                # APP: models.py views.py forms.py urls.py api.py admin.py tests.py
│   ├── migrations/      # auto-generated database history
│   └── management/commands/seed_demo.py
├── templates/           # HTML files
└── static/              # css/ and js/
```

### 2.3 Commands you will use constantly
```bash
python manage.py runserver          # start dev server at http://127.0.0.1:8000
python manage.py makemigrations     # turn model changes into a migration file
python manage.py migrate            # apply migrations to the database
python manage.py createsuperuser    # make an admin login
python manage.py shell              # Python prompt with Django loaded (experiment here!)
python manage.py test               # run automated tests
python manage.py check              # find configuration mistakes
```

### 2.4 URLs
```python
from django.urls import path
urlpatterns = [
    path("",                      views.home,   name="home"),         # exact: /
    path("shops/<int:pk>/",       views.detail, name="shop_detail"),  # /shops/7/  → detail(request, pk=7)
    path("do/<str:action>/",      views.act,    name="act"),          # <str:...> captures text
]
```
- `<int:pk>` captures a number and passes it to the view as the argument `pk`.
- `name="…"` lets you avoid hard-coding addresses: in Python `reverse("shop_detail", args=[7])`, in templates `{% url 'shop_detail' 7 %}`.
- `include("core.urls")` plugs another URL file in.

### 2.5 Views
```python
from django.shortcuts import render, redirect, get_object_or_404

def detail(request, pk):                        # request = everything about the visit
    shop = get_object_or_404(Shop, pk=pk)       # fetch or show a 404 page
    if request.method == "POST":                # form submitted
        ...
        return redirect("shop_list")            # send browser elsewhere (always redirect after a successful POST)
    return render(request, "shop_detail.html", {"shop": shop})   # template + context dict
```
Useful `request` parts: `request.user` (who), `request.GET` (query string `?a=1`), `request.POST` (form data), `request.method`, `request.path`.
Decorators: `@login_required` (must be logged in), `@require_POST` (only POST allowed).
Flash messages: `messages.success(request, "Saved")` – shown once on the next page.

### 2.6 Models (tables)
```python
class Shop(models.Model):
    name   = models.CharField(max_length=100)               # short text
    notes  = models.TextField(blank=True)                   # long text; blank=True = may be empty in forms
    fee    = models.DecimalField(max_digits=8, decimal_places=2, default=0)   # money (never use float!)
    active = models.BooleanField(default=True)
    made   = models.DateTimeField(auto_now_add=True)        # set once on creation
    seen   = models.DateTimeField(auto_now=True)            # updated on every save()
    owner  = models.OneToOneField(User, on_delete=models.CASCADE)           # exactly one-to-one
```
Relationships:
- `ForeignKey(Other, on_delete=models.CASCADE)` – **many-to-one** (many repairs → one shop). `CASCADE` = delete children when the parent is deleted.
- `OneToOneField` – exactly one (one user ↔ one profile).
- `related_name="repairs"` – the reverse lookup name: `shop.repairs.all()`.
- `choices=[("phone","Phone"), …]` – restricts values and gives `get_FIELD_display()`.
- `null=True` (database may store NULL) vs `blank=True` (form may be empty). For numbers/dates use both; for text use `blank=True` only.
- `class Meta: ordering = [...]` – default sort. `def __str__` – readable name in admin.
- Methods and `@property` add behaviour: `job.total_price` (property) vs `job.apply(...)` (method).

**Migrations**: you change `models.py` → run `makemigrations` (writes a recipe in `core/migrations/`) → `migrate` (executes it). Always both, every time you change a model.

### 2.7 The ORM (database queries without SQL)
```python
Shop.objects.all()                                  # everything
Shop.objects.filter(is_active=True)                 # WHERE is_active
Shop.objects.filter(name__contains="fix")           # LIKE '%fix%'
RepairRequest.objects.filter(cost__gte=500)         # >= ; also __lt __lte __gt __in __startswith
Shop.objects.exclude(is_active=False)
Shop.objects.get(pk=1)                              # exactly one or raises an error
Shop.objects.filter(...).count() / .exists() / .first()
RepairRequest.objects.order_by("-created_at")       # minus = descending
RepairRequest.objects.filter(pk=3).update(status="ready")   # one UPDATE, no save() needed
RepairRequest.objects.create(...)                   # INSERT
obj.save() ; obj.delete() ; obj.refresh_from_db()
Q(customer=u) | Q(shop__owner=u)                    # OR conditions; double underscore follows relations
F("quoted_cost")                                    # refer to another column inside the DB: update(approved_cost=F("quoted_cost"))
.select_related("shop")                             # JOIN now → avoids one extra query per row (N+1 problem)
```
QuerySets are **lazy**: nothing hits the database until you loop over them, `list()` them, or call `.count()`.

### 2.8 Templates
```html
{{ job.device_name }}                         <!-- print a value -->
{{ job.drop_slot|date:"D d M, H:i" }}         <!-- filter: transform a value -->
{% if job.express %}…{% elif x %}…{% else %}…{% endif %}
{% for s in shops %}…{% empty %}No shops{% endfor %}
{% url 'shop_detail' s.pk %}                  <!-- address from a URL name -->
{% csrf_token %}                              <!-- REQUIRED inside every POST form (security) -->
{% extends "base.html" %}{% block content %}…{% endblock %}   <!-- inheritance: base has the frame -->
{% include "_job_table.html" with jobs=active %}              <!-- reuse a snippet -->
{% load static %}<link href="{% static 'css/style.css' %}">   <!-- static files -->
```
Templates auto-escape HTML (protects from XSS attacks). `user` and `messages` are available everywhere thanks to context processors in settings.

### 2.9 Forms (HTML + validation in one)
```python
class RequestForm(forms.ModelForm):          # builds fields from a model
    class Meta:
        model = RepairRequest
        fields = ["device_name", "problem"]
    def clean_problem(self):                 # validate ONE field: clean_<fieldname>
        value = self.cleaned_data["problem"]
        if len(value) < 5: raise forms.ValidationError("Too short")
        return value
    def clean(self):                         # validate fields TOGETHER
        data = super().clean(); self.add_error("device_name", "message"); return data
```
Flow in a view:
```python
form = RequestForm(request.POST or None)     # GET → empty form; POST → filled form
if request.method == "POST" and form.is_valid():
    obj = form.save(commit=False)            # build the object but don't save yet
    obj.customer = request.user              # fill fields the user must not choose
    obj.save()
```
`form.as_p` renders it; errors show automatically.

### 2.10 Users & login
Django ships a complete `User` model (username, hashed password…). You get `request.user`, `@login_required`, `LoginView`, `LogoutView`, `UserCreationForm`. **Never store raw passwords:** use `create_user()` / `set_password()` — they hash.

### 2.11 Admin
`admin.site.register(Model)` gives you a free database editor at `/admin/`. Perfect for debugging.

### 2.12 Django REST Framework (JSON API)
```python
class ShopSerializer(serializers.ModelSerializer):     # model → JSON
    class Meta: model = Shop; fields = ["id", "name"]
class ShopViewSet(viewsets.ReadOnlyModelViewSet):      # gives list + detail endpoints
    queryset = Shop.objects.all(); serializer_class = ShopSerializer
router.register("shops", ShopViewSet)                  # /api/shops/ and /api/shops/3/
```
`@api_view(["GET"])` turns a function into a small API endpoint returning `Response({...})`.

### 2.13 Testing
```python
class MyTests(TestCase):                  # each test gets a fresh empty database
    def test_x(self):
        self.client.login(username="a", password="b")     # fake browser
        r = self.client.post(url, data); self.assertEqual(r.status_code, 302)
```
Run `python manage.py test`.

### 2.14 Python features used in this project
`f"..{x}.."` f-strings · dict/list comprehensions · `getattr(obj, "attr", default)` (safe attribute) · `*args/**kwargs` (pass-through arguments) · `@property` · decorators (`@login_required`) · `set` membership (`x in {A, B}`) · tuple unpacking (`a, b = pair`).

---

## 3. Setup (Step 0) — 15 minutes

```bash
mkdir fixflow && cd fixflow
python -m venv venv                       # an isolated Python for this project
# activate it:
source venv/bin/activate                  # macOS / Linux
venv\Scripts\activate                     # Windows (PowerShell: venv\Scripts\Activate.ps1)

pip install "Django>=5.0,<6" djangorestframework PyMySQL cryptography
pip freeze > requirements.txt             # (or copy the provided requirements.txt)

django-admin startproject config .        # NOTE the dot: put manage.py right here
python manage.py startapp core            # creates the core/ app
mkdir templates static static/css static/js
mkdir -p core/management/commands && touch core/management/__init__.py core/management/commands/__init__.py   # Windows: create these empty files in your editor
python manage.py runserver                # open http://127.0.0.1:8000 → rocket page = success. Ctrl+C to stop.
```
`requirements.txt` used by the provided project:
```text
Django>=5.0,<6
djangorestframework>=3.15
PyMySQL>=1.1
cryptography>=42
```

**Why a virtualenv?** Packages install into the project only, not your whole computer; `requirements.txt` lets anyone recreate it with `pip install -r requirements.txt`.

---

## 4. Build it, file by file

### Step 1 — `config/settings.py` (replace the whole file)
```python
# ---- config/settings.py ----
"""Project settings. Everything that configures Django lives here."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # the folder containing manage.py

# Read secrets from environment variables so they never get committed to Git.
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",  # Django REST Framework (the JSON API)
    "core",            # our own app
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],  # our HTML lives in /templates
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

WSGI_APPLICATION = "config.wsgi.application"

# ---- Database: SQLite by default, MySQL when DB_ENGINE=mysql ----
if os.environ.get("DB_ENGINE") == "mysql":
    import pymysql  # pure-python MySQL driver (easy to install on every OS)
    pymysql.version_info = (2, 2, 1, "final", 0)  # satisfy Django's version check
    pymysql.install_as_MySQLdb()
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "fixflow"),
        "USER": os.environ.get("DB_USER", "root"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"  # slot hours are checked in the shop's local time
USE_TZ = True               # store UTC in the DB, show local time to users

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "request_list"
LOGOUT_REDIRECT_URL = "shop_list"

REST_FRAMEWORK = {"DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticatedOrReadOnly"]}
```

**Walkthrough**
- `BASE_DIR` – `Path(__file__)` is this file; `.parent.parent` climbs to the folder with `manage.py`. Used to build file paths portably (`BASE_DIR / "templates"`).
- `os.environ.get("SECRET_KEY", "dev-only-change-me")` – reads an environment variable, falling back to a default. Real secrets must come from the environment in production, never from Git.
- `DEBUG` – detailed error pages. **Must be off in production.**
- `INSTALLED_APPS` – every app Django should load. We added `rest_framework` and `core`. Forgetting `core` = your models don't exist.
- `MIDDLEWARE` – a chain every request/response passes through (sessions, CSRF protection, login state, messages). Leave as generated.
- `TEMPLATES["DIRS"]` – tells Django to also look in `/templates`. `APP_DIRS: True` also finds templates inside apps (the admin uses that). Context processors make `request`, `user`, `messages` available in every template.
- `DATABASES` – an `if` chooses MySQL when you set `DB_ENGINE=mysql`, otherwise SQLite (a single file, zero setup – ideal for learning). `pymysql.install_as_MySQLdb()` makes the pure-Python PyMySQL pretend to be the C driver Django expects, avoiding painful compiler installs on Windows. The `version_info` line satisfies Django's driver-version check.
- `TIME_ZONE` + `USE_TZ=True` – the database stores UTC; Django converts to `Asia/Kolkata` for display. We check "9 to 18" in *local* time using `timezone.localtime()`.
- `STATICFILES_DIRS` – where our CSS/JS live. `STATIC_URL` – their web address prefix.
- `LOGIN_URL / LOGIN_REDIRECT_URL / LOGOUT_REDIRECT_URL` – where `@login_required` sends anonymous users and where to land after login/logout (these are URL *names*).
- `REST_FRAMEWORK` – default API permission: anyone can read, only logged-in users can write (we only expose reads anyway).

**Checkpoint:** `python manage.py check` → "System check identified no issues".

---

### Step 2 — `core/models.py` (the heart of the app)
```python
# ---- core/models.py ----
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
```

**Walkthrough (read slowly — this file is the design of the whole app)**

1. `DEVICE_CHOICES` – a list of `(stored value, label)`. Values (`phone`, `laptop`…) go to the database; labels show on screen.
2. `Profile` – Django's `User` has no "role", so we attach one extra table with `OneToOneField`. `related_name="profile"` makes `user.profile` work. `__str__` is what the admin displays.
3. `Shop` – one shop per owner (`OneToOneField`). `device_types` is a comma-separated string like `"phone,laptop"` — simple for a beginner project. `supports()` checks membership by splitting the string. (Safe `contains` filtering works because no key is a substring of another.) `express_fee = 0` means "no express". `slots_per_hour` limits how many drop-offs the shop accepts per hour.
4. `Status(models.TextChoices)` – a named list of states; `Status.PENDING` is the value `"pending"` with label "Waiting for shop". Using constants instead of raw strings means typos become errors.
5. `FINAL_STATUSES` – states after which nothing can happen (used to split "Active" vs "Closed").
6. `TRANSITIONS` – **the rulebook.** Each key is an action name; value is `(statuses it may start from, status it ends in, which role may do it)`. Example: `"accept": ({PENDING}, ACCEPTED, "shop")` = only the shop, only while pending.
7. `ACTION_INFO` – button label, CSS style, and whether a typed reason is required (rejections need one so customers aren't left guessing).
8. `RepairRequest` fields:
   - `customer`/`shop` – foreign keys (who and where).
   - `drop_slot` – when the customer will bring it.
   - `max_budget` – optional pre-approval limit (the "small jobs are fixed fast" shortcut).
   - `express` + `express_fee` – the fee is **copied** from the shop at booking time, so later fee changes don't alter existing orders (a classic loophole).
   - `quoted_cost` (what the shop currently asks) vs `approved_cost` (what the customer agreed to). Keeping them separate is what lets a revised quote force a new approval.
   - `is_paid` – set when the shop marks "Paid & collected" (payments are cash-at-shop in this MVP).
   - `Meta.ordering = ["-express", "drop_slot"]` – express jobs first, then earliest slot.
9. `total_price` – a `@property`: approved cost (or the quote) + express fee. Called like a field: `job.total_price`.
10. `actions_for(role)` – list comprehension that walks `TRANSITIONS` and returns only the buttons this role may press in the current status. The template just loops over it → **no permission logic in HTML.**
11. `apply(action, role, **extra)` – performs a transition:
    - checks the role;
    - runs `filter(pk=…, status__in=allowed).update(...)`. This is a **compare-and-set**: the UPDATE only matches if the status is *still* valid. If someone double-clicks or has two tabs open, the second attempt updates 0 rows → we raise `ValueError`. No double processing, no illegal jumps.
    - `**extra` lets the caller set extra columns in the same UPDATE (note, paid flag…).
    - `update()` skips `auto_now`, so we set `updated_at` manually.
12. `Notification` + `notify(user, message, request)` – a tiny in-app inbox. To send SMS/e-mail later, change only `notify()`.

**Checkpoint:** nothing to run yet — models become tables in Step 3.

---

### Step 3 — Admin + database
```python
# ---- core/admin.py ----
from django.contrib import admin

from .models import Notification, Profile, RepairRequest, Shop

admin.site.register([Profile, Shop, Notification])


@admin.register(RepairRequest)
class RepairRequestAdmin(admin.ModelAdmin):
    list_display = ["id", "device_name", "shop", "customer", "status", "express", "drop_slot"]
    list_filter = ["status", "express", "shop"]
```
```bash
python manage.py makemigrations core      # writes core/migrations/0001_initial.py
python manage.py migrate                  # creates all tables (Django's own + ours)
python manage.py createsuperuser          # choose a username/password
```
- `admin.site.register([...])` – quick registration.
- `@admin.register(RepairRequest)` + `ModelAdmin` – a decorator form that customises columns (`list_display`) and sidebar filters (`list_filter`).

**Checkpoint:** (after Step 7) visit `/admin/`, log in, and you can see your tables. Open `core/migrations/0001_initial.py` once to see what Django generated from your classes.

---

### Step 4 — `core/forms.py`
```python
# ---- core/forms.py ----
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
```

**Walkthrough**
- `PHONE_RULE` – a regular expression validator: optional `+`, then 10–13 digits.
- `RegisterForm(UserCreationForm)` – inherits username + two password fields (with strength rules and hashing) and adds `role` and `phone`. We override `save()`: call the parent (creates the user), then create the `Profile`.
- `ShopForm` – a `ModelForm`. `device_types` is declared by hand as a `MultipleChoiceField` rendered as checkboxes. A form field returns a *list*, but the model stores a *string*, so `clean_device_types` joins it (`",".join(...)`) and `__init__` splits it back when editing. `clean_phone` re-uses the validator.
- `RequestForm` – the validation showpiece:
  - `__init__(self, *args, shop, **kwargs)` – the `*` forces `shop=` to be passed by keyword; we store it so validators know which shop is being booked.
  - `widgets` – `type="datetime-local"` gives a native date-time picker.
  - `clean_drop_slot` – rules, in order: at least 1 h ahead → at most 14 days → not Sunday → between 09:00 and 18:00 local time → **capacity check**: count `PENDING`/`ACCEPTED` bookings inside the same clock hour; refuse when `>= slots_per_hour`. (`drop_slot__gte` / `__lt` is a half-open range, so 10:00 belongs to the 10:00 hour only.)
  - `clean` – cross-field rules: the shop must repair this device type; express is only allowed if the shop offers it. `add_error("field", "text")` attaches the message to that field.
- `DiagnoseForm` – a plain `forms.Form` (not tied to a model) used by the shop; `min_value` blocks negative costs.

---

### Step 5 — `core/views.py`
```python
# ---- core/views.py ----
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
```

**Walkthrough**
- `role_of(user)` – `getattr(user, "profile", None)`: the admin account has no profile, and a normal attribute access would crash; `getattr` with a default returns `None` instead.
- `load_request(user, pk)` – **the security gate.** Fetches a request, then returns `(job, "customer")` or `(job, "shop")` — otherwise raises **404** (not 403, so outsiders can't even confirm a request ID exists). Every request-related view calls it first. `select_related` pre-loads related rows in one query.
- `register` – `RegisterForm(request.POST or None)` (see 2.9), saves, logs the user in, and redirects shop owners to set up their shop.
- `shop_setup` – only `shop` role; `instance=getattr(request.user, "shop", None)` edits the existing shop or starts a new one. `commit=False` lets us set `owner` ourselves, so a user can never create a shop for someone else.
- `shop_list` – optional `?device=phone` filter. Validated against `dict(DEVICE_CHOICES)` so random text is ignored. Only active shops appear.
- `shop_detail` – GET shows the shop and the request form; POST creates the request: customer and shop come from the server (never from the form), `express_fee` is copied from the shop only if express was ticked, and the shop owner gets a notification.
- `request_list` – shops see requests for their shop, customers see their own; split into active/closed lists with comprehensions.
- `request_detail` – builds the `DiagnoseForm` only when the shop may still quote (`can_quote`), pre-filled with the current quote so corrections are easy.
- `NOTIFY` – a dict: action → (who is told, message template). Adding a notification = adding a line, no new code.
- `request_action` – the **one view for all buttons**: validate the action name → `load_request` → require a reason for reject/unrepairable → build `extra` columns (`F("quoted_cost")` copies the quoted cost into `approved_cost` *inside the database*, so if the shop edits the quote at the same instant the customer clicks approve, the customer approves exactly what is in the DB) → `job.apply(...)` inside `try/except ValueError` → notify the other side → redirect. `@require_POST` makes state changes impossible via a link/GET.
- `request_diagnose` – the diagnosis logic. `limit = max(approved_cost, max_budget)`; if the new quote fits → `IN_REPAIR` (small-job shortcut and "same price as already approved"), else `AWAITING_APPROVAL`. The update is again compare-and-set on the allowed statuses. The notification includes the shop phone number so the customer can call.
- `notifications` – converts the queryset to a list **before** marking as read (otherwise the page would show everything as already read).

---

### Step 6 — `core/api.py` (Django REST Framework)
```python
# ---- core/api.py ----
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
```

- Serializers convert model rows into JSON (`ModelSerializer` writes most of it for you). `source="get_status_display"` exposes the human label.
- `ShopViewSet` – read-only list/detail; `?device=phone` filter works like the web page.
- `MyRequestViewSet` – `get_queryset` returns only the requester's own requests (customer **or** shop owner) using `Q(...) | Q(...)`; `IsAuthenticated` blocks anonymous users.
- `unread_count` – `@api_view` + `@permission_classes` make a function-based endpoint. The JavaScript calls it every 30 s for the 🔔 badge.

---

### Step 7 — URLs
`core/urls.py` (create this file – `startapp` does not):
```python
# ---- core/urls.py ----
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
```
`config/urls.py` (replace):
```python
# ---- config/urls.py ----
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
```

- `LoginView.as_view(template_name=…, extra_context=…)` – a ready-made login page, re-using our generic `form.html`. `LogoutView` is POST-only in Django 5 (that's why the navbar logout is a small form).
- `<int:pk>` / `<str:action>` capture URL parts as view arguments.
- `DefaultRouter` auto-generates `/api/shops/`, `/api/shops/<id>/`, `/api/requests/…`. `basename` is required when the viewset has no `queryset` attribute.
- Order matters: `api/unread/` is listed before `include(router.urls)` so the router doesn't swallow it; the empty `""` include goes last as the catch-all for the site pages.

**Checkpoint:** `python manage.py check` → no issues.

---

### Step 8 — Templates (`templates/`)

#### `base.html` — the frame every page extends
```html
<!-- templates/base.html -->
{% load static %}
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}FixFlow{% endblock %}</title>
  <link rel="stylesheet" href="{% static 'css/style.css' %}">
</head>
<body>
<nav>
  <a class="brand" href="{% url 'shop_list' %}">🔧 FixFlow</a>
  {% if user.is_authenticated %}
    <a href="{% url 'request_list' %}">{% if user.profile.role == 'shop' %}Dashboard{% else %}My repairs{% endif %}</a>
    {% if user.profile.role == 'shop' %}<a href="{% url 'shop_setup' %}">My shop</a>{% endif %}
    <a href="{% url 'notifications' %}">🔔<span id="badge" class="badge" hidden></span></a>
    <form method="post" action="{% url 'logout' %}" class="inline">{% csrf_token %}
      <button class="link">Logout ({{ user.username }})</button></form>
  {% else %}
    <a href="{% url 'login' %}">Login</a>
    <a href="{% url 'register' %}">Register</a>
  {% endif %}
</nav>
<main>
  {% for m in messages %}<div class="msg {{ m.tags }}">{{ m }}</div>{% endfor %}
  {% block content %}{% endblock %}
</main>
<script src="{% static 'js/app.js' %}" data-unread-url="{% url 'api_unread' %}"></script>
</body>
</html>
```
- `{% load static %}` enables `{% static %}`.
- `user.profile.role` – if a user has no profile, Django templates silently treat it as empty instead of crashing.
- Logout is a `<form method="post">` with `{% csrf_token %}` (required for POST).
- `{% for m in messages %}` prints flash messages; `m.tags` (`success`, `error`) become CSS classes.
- `{% block content %}` – child templates fill this hole.
- `data-unread-url` hands the API address to JavaScript, so JS never hard-codes URLs.

#### `form.html` — one generic form page (register, login, shop setup)
```html
<!-- templates/form.html -->
{% extends "base.html" %}
{% block content %}
<div class="card narrow">
  <h1>{{ title }}</h1>
  <form method="post">{% csrf_token %}
    {{ form.as_p }}
    <button class="btn">{{ button|default:"Save" }}</button>
  </form>
</div>
{% endblock %}
```
`{{ form.as_p }}` renders every field with its label and errors. `{{ button|default:"Save" }}` uses "Save" when no button text is given.

#### `shop_list.html`
```html
<!-- templates/shop_list.html -->
{% extends "base.html" %}
{% block content %}
<h1>Find a repair shop</h1>
<form method="get" class="row">
  <select name="device">
    <option value="">Any device</option>
    {% for key, label in devices %}<option value="{{ key }}" {% if key == picked %}selected{% endif %}>{{ label }}</option>{% endfor %}
  </select>
  <button class="btn">Filter</button>
</form>
<input id="live" class="search" placeholder="Search these shops by name or area...">
{% for s in shops %}
  <div class="card shop">
    <h3><a href="{% url 'shop_detail' s.pk %}">{{ s.name }}</a></h3>
    <p>📍 {{ s.address }}</p>
    <p>Repairs: {{ s.device_labels }}</p>
    {% if s.express_fee > 0 %}<span class="tag">⚡ Express +₹{{ s.express_fee }}</span>{% endif %}
  </div>
{% empty %}
  <p>No shops match yet.</p>
{% endfor %}
{% endblock %}
```
Server-side filter (GET form → `?device=…`) plus a JS live search for the cards already on the page. `{% empty %}` runs when the list is empty.

#### `shop_detail.html`
```html
<!-- templates/shop_detail.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h1>{{ shop.name }}</h1>
  <p>📍 {{ shop.address }} &nbsp; 📞 {{ shop.phone }}</p>
  <p>Repairs: {{ shop.device_labels }}</p>
  <p>Open Mon-Sat, drop-off 9:00-18:00. {% if shop.express_fee > 0 %}⚡ Express service: +₹{{ shop.express_fee }}{% else %}No express service.{% endif %}</p>
</div>
{% if can_request %}
  <div class="card">
    <h2>Request a repair</h2>
    <form method="post">{% csrf_token %}{{ form.as_p }}<button class="btn">Send request</button></form>
  </div>
{% elif user.is_authenticated %}
  <p class="muted">Only customer accounts can send repair requests.</p>
{% else %}
  <p><a href="{% url 'login' %}?next={{ request.path }}">Login</a> or <a href="{% url 'register' %}">register</a> as a customer to request a repair.</p>
{% endif %}
{% endblock %}
```
Shows the request form only to customers; visitors see a login link (`?next=` returns them here after login).

#### `request_list.html` and its reusable table `_job_table.html`
```html
<!-- templates/request_list.html -->
{% extends "base.html" %}
{% block content %}
<h1>{% if user.profile.role == 'shop' %}Shop dashboard{% else %}My repairs{% endif %}</h1>
{% if user.profile.role == 'shop' and not user.shop %}
  <p class="msg warning">Set up your shop first: <a href="{% url 'shop_setup' %}">open shop details</a>.</p>
{% endif %}
<h2>Active</h2>
{% include "_job_table.html" with jobs=active %}
<h2>Closed</h2>
{% include "_job_table.html" with jobs=closed %}
{% endblock %}
```
```html
<!-- templates/_job_table.html -->
{% if jobs %}
<table>
  <tr><th>#</th><th>Device</th><th>{% if user.profile.role == 'shop' %}Customer{% else %}Shop{% endif %}</th><th>Drop-off</th><th>Status</th></tr>
  {% for j in jobs %}
  <tr>
    <td><a href="{% url 'request_detail' j.pk %}">#{{ j.pk }}</a></td>
    <td>{{ j.device_name }} {% if j.express %}<span class="tag">⚡ Express</span>{% endif %}</td>
    <td>{% if user.profile.role == 'shop' %}{{ j.customer.username }}{% else %}{{ j.shop.name }}{% endif %}</td>
    <td>{{ j.drop_slot|date:"D d M, H:i" }}</td>
    <td><span class="st st-{{ j.status }}">{{ j.get_status_display }}</span></td>
  </tr>
  {% endfor %}
</table>
{% else %}<p class="muted">Nothing here.</p>{% endif %}
```
`{% include ... with jobs=active %}` reuses one table twice. `{{ j.get_status_display }}` prints the label for a `choices` field; `st-{{ j.status }}` becomes a CSS class for colour.

#### `request_detail.html` — the most important page
```html
<!-- templates/request_detail.html -->
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h1>#{{ job.pk }} - {{ job.device_name }} {% if job.express %}<span class="tag">⚡ Express</span>{% endif %}</h1>
  <p><span class="st st-{{ job.status }}">{{ job.get_status_display }}</span></p>
  {% if job.status == 'awaiting_approval' and role == 'customer' %}
    <p class="msg warning">The shop needs your decision on the quote below. You can also call them: {{ job.shop.phone }}</p>
  {% endif %}
  <table class="kv">
    <tr><th>Device type</th><td>{{ job.get_device_type_display }}</td></tr>
    <tr><th>Problem</th><td>{{ job.problem|linebreaksbr }}</td></tr>
    <tr><th>Drop-off slot</th><td>{{ job.drop_slot|date:"D d M Y, H:i" }}</td></tr>
    {% if role == 'shop' %}
      <tr><th>Customer</th><td>{{ job.customer.username }} - 📞 {{ job.customer.profile.phone }}</td></tr>
      <tr><th>Customer budget limit</th><td>{% if job.max_budget %}₹{{ job.max_budget }}{% else %}not set{% endif %}</td></tr>
    {% else %}
      <tr><th>Shop</th><td>{{ job.shop.name }} - {{ job.shop.address }} - 📞 {{ job.shop.phone }}</td></tr>
    {% endif %}
    {% if job.diagnosis %}<tr><th>Diagnosis</th><td>{{ job.diagnosis|linebreaksbr }}</td></tr>{% endif %}
    {% if job.quoted_cost is not None %}<tr><th>Quote</th><td>₹{{ job.quoted_cost }} - about {{ job.estimated_days }} day(s)</td></tr>{% endif %}
    {% if job.express %}<tr><th>Express fee</th><td>₹{{ job.express_fee }}</td></tr>{% endif %}
    {% if job.quoted_cost is not None %}<tr><th>Total</th><td><strong>₹{{ job.total_price }}</strong> {% if job.is_paid %}(paid){% else %}(pay at the shop){% endif %}</td></tr>{% endif %}
    {% if job.shop_note %}<tr><th>Shop note</th><td>{{ job.shop_note }}</td></tr>{% endif %}
  </table>
</div>

{% if actions %}
<div class="card">
  <h2>Actions</h2>
  {% for a in actions %}
  <form method="post" action="{% url 'request_action' job.pk a.name %}" class="row" data-confirm="Are you sure?">
    {% csrf_token %}
    {% if a.needs_note %}<input name="note" placeholder="Reason (required)" required maxlength="300">{% endif %}
    <button class="btn {{ a.style }}">{{ a.label }}</button>
  </form>
  {% endfor %}
</div>
{% endif %}

{% if diagnose_form %}
<div class="card">
  <h2>{% if job.status == 'received' %}Send diagnosis & quote{% else %}Update / correct the quote{% endif %}</h2>
  <p class="muted">If the quote is within the customer's budget the repair starts at once; otherwise the customer is asked to approve.</p>
  <form method="post" action="{% url 'request_diagnose' job.pk %}">{% csrf_token %}{{ diagnose_form.as_p }}<button class="btn">Send to customer</button></form>
</div>
{% endif %}
{% endblock %}
```
- `role` decides what each side sees (shops see the customer's phone and budget; customers see the shop's contact info and a prominent banner when approval is needed).
- `{% for a in actions %}` – one tiny POST form per allowed button (computed by the model). `data-confirm` triggers the JS confirmation. `required` on the reason input stops empty rejections in the browser; the view re-checks on the server (never trust the browser).
- The diagnosis form appears only when `diagnose_form` exists.

#### `notifications.html`
```html
<!-- templates/notifications.html -->
{% extends "base.html" %}
{% block content %}
<h1>Notifications</h1>
{% for n in items %}
  <div class="card {% if not n.is_read %}unread{% endif %}">
    {{ n.message }} <span class="muted">({{ n.created_at|date:"d M, H:i" }})</span>
    {% if n.request_id %}<a href="{% url 'request_detail' n.request_id %}">Open</a>{% endif %}
  </div>
{% empty %}<p class="muted">No notifications yet.</p>{% endfor %}
{% endblock %}
```

---

### Step 9 — Static files (`static/`)
```css
*{box-sizing:border-box}body{font-family:system-ui,sans-serif;margin:0;background:#f4f6f8;color:#222}
nav{display:flex;gap:16px;align-items:center;background:#1f3a5f;padding:12px 20px}
nav a,nav .link{color:#fff;text-decoration:none}.brand{font-weight:700;margin-right:auto}
main{max-width:900px;margin:20px auto;padding:0 16px}
.card{background:#fff;border-radius:8px;padding:16px;margin:12px 0;box-shadow:0 1px 3px #0002}
.card.unread{border-left:4px solid #2e7d32}.narrow{max-width:460px;margin:30px auto}
input,select,textarea{width:100%;padding:8px;margin:4px 0;border:1px solid #bbb;border-radius:6px;font:inherit}
input[type=checkbox]{width:auto}ul{list-style:none;padding:0}
.btn{background:#1f3a5f;color:#fff;border:0;padding:9px 16px;border-radius:6px;cursor:pointer}
.btn.ok{background:#2e7d32}.btn.danger{background:#c62828}
.link{background:none;border:0;cursor:pointer;font:inherit;padding:0}.inline{display:inline;margin:0}
.row{display:flex;gap:8px;align-items:center;margin:8px 0}.row input{flex:1}.row select{width:auto}
.search{margin:8px 0}table{width:100%;border-collapse:collapse;background:#fff}
th,td{padding:8px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}.kv th{width:180px}
.tag{background:#fff3cd;padding:2px 8px;border-radius:12px;font-size:.8em}
.st{padding:3px 10px;border-radius:12px;background:#e0e0e0;font-size:.85em}
.st-pending,.st-awaiting_approval{background:#fff3cd}.st-accepted,.st-in_repair,.st-received{background:#d6e9ff}
.st-ready,.st-completed{background:#d4edda}.st-rejected,.st-cancelled,.st-declined,.st-unrepairable,.st-returned{background:#f8d7da}
.msg{padding:10px 14px;border-radius:6px;margin:8px 0;background:#e3f2fd}.msg.success{background:#d4edda}
.msg.error{background:#f8d7da}.msg.warning{background:#fff3cd}.muted{color:#777}
.badge{background:#e53935;color:#fff;border-radius:10px;padding:0 7px;font-size:.75em;margin-left:3px}.badge[hidden]{display:none}
.helptext{display:block;font-size:.8em;color:#777}.errorlist{color:#c62828;padding:0;margin:2px 0}
```
- `.badge[hidden]{display:none}` – without this rule `display:inline-block` would override the HTML `hidden` attribute.

```javascript
// 1) Notification badge: ask the API for the unread count every 30 seconds.
// 2) Confirm dialog on forms that have data-confirm.  3) Live search box on the shop list.
(function () {
  const url = document.currentScript.dataset.unreadUrl;
  const badge = document.getElementById("badge");

  async function refreshBadge() {
    if (!badge) return;                       // only logged-in pages have a badge
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      badge.textContent = data.unread;
      badge.hidden = data.unread === 0;
    } catch (e) { /* offline: ignore */ }
  }
  refreshBadge();
  setInterval(refreshBadge, 30000);

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  const live = document.getElementById("live");
  if (live) {
    live.addEventListener("input", function () {
      const q = live.value.toLowerCase();
      document.querySelectorAll(".shop").forEach(function (card) {
        card.style.display = card.textContent.toLowerCase().includes(q) ? "" : "none";
      });
    });
  }
})();
```
- `document.currentScript.dataset.unreadUrl` reads the `data-unread-url` attribute from the `<script>` tag.
- `fetch(url, {credentials:"same-origin"})` sends the login cookie; `res.json()` parses the API reply; `setInterval(fn, 30000)` repeats every 30 s.
- `querySelectorAll("form[data-confirm]")` – attach a submit listener to all forms with that attribute; `e.preventDefault()` cancels the submit when the user clicks Cancel.
- The live search lowercases both sides and uses `includes()` to show/hide cards.

---

## 5. Run it and test the whole flow (30 min)

### 5.1 Demo data
```python
# ---- core/management/commands/seed_demo.py ----
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
```
A **management command** = your own `manage.py` subcommand. `get_or_create` runs safely many times.
```bash
python manage.py seed_demo
python manage.py runserver
```
Accounts (password `demo12345`): `shopowner` and `customer`. Use two browsers (or one normal + one private window) so both stay logged in.

### 5.2 Walk-through script
1. **Customer:** open `/`, filter by *Speaker*, open *QuickFix Repairs*, request: speaker, "No sound", pick a weekday slot, tick **Express**. → request `#1`, status *Waiting for shop*.
2. **Shop:** 🔔 badge shows 1 → Dashboard → open `#1` → **Accept request**. Customer gets a notification with the slot.
3. **Shop:** (customer arrives) **Mark device received**.
4. **Shop:** fill *Diagnosis* "Blown driver", cost 500, days 2 → **Send to customer**. Customer sees the yellow banner and phone number.
5. **Customer:** **Approve quote**. Shop sees approval.
6. **Shop (diagnosis was wrong):** use *Update / correct the quote* → cost 900. Status flips back to *Waiting for approval* — repair is paused until the customer agrees (try both Approve and Decline).
7. **Shop:** **Repair done – ready for pickup** → customer is told the total (cost + express fee).
8. **Shop:** **Paid & collected** → *Completed*.
9. Repeat with a **budget** of 1000: when the shop sends a 500 quote it starts immediately (small-job shortcut).
10. Try to break it: open the request in two tabs and press Accept in both; type `/requests/1/` as a different customer (404); book the same hour twice (capacity error); book a Sunday; ask a phone-only shop for a TV.

### 5.3 Automated tests
```python
# ---- core/tests.py ----
"""Automated tests: run with  python manage.py test"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Notification, Profile, RepairRequest, Shop, Status


def next_weekday_slot(hour=10, days=2):
    """A valid drop-off time: some day soon, not Sunday, inside opening hours."""
    d = timezone.localtime() + timedelta(days=days)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0)


class FlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="pw12345pw")
        Profile.objects.create(user=self.owner, role="shop", phone="9876543210")
        self.shop = Shop.objects.create(owner=self.owner, name="FixIt", address="x", phone="9876543210",
                                        device_types="phone,speaker", express_fee=200, slots_per_hour=1)
        self.cust = User.objects.create_user("cust", password="pw12345pw")
        Profile.objects.create(user=self.cust, role="customer", phone="9123456780")
        self.other = User.objects.create_user("other", password="pw12345pw")
        Profile.objects.create(user=self.other, role="customer", phone="9000000000")

    def book(self, **over):
        self.client.login(username="cust", password="pw12345pw")
        data = {"device_type": "speaker", "device_name": "JBL Go", "problem": "No sound",
                "drop_slot": next_weekday_slot().strftime("%Y-%m-%dT%H:%M")}
        data.update(over)
        return self.client.post(reverse("shop_detail", args=[self.shop.pk]), data)

    def make_job(self, status=Status.PENDING, **kw):
        return RepairRequest.objects.create(customer=self.cust, shop=self.shop, device_type="speaker",
                                            device_name="JBL", problem="x", drop_slot=next_weekday_slot(),
                                            status=status, **kw)

    def act(self, user, job, action, **post):
        self.client.login(username=user, password="pw12345pw")
        return self.client.post(reverse("request_action", args=[job.pk, action]), post)

    def test_full_happy_path(self):
        self.book(express="on")
        job = RepairRequest.objects.get()
        self.assertEqual(job.express_fee, Decimal("200"))
        self.assertTrue(Notification.objects.filter(user=self.owner).exists())
        self.act("owner", job, "accept")
        self.act("owner", job, "receive")
        self.client.login(username="owner", password="pw12345pw")
        self.client.post(reverse("request_diagnose", args=[job.pk]), {"diagnosis": "Blown driver", "cost": "500", "days": "2"})
        job.refresh_from_db()
        self.assertEqual(job.status, Status.AWAITING_APPROVAL)
        self.act("cust", job, "approve")
        job.refresh_from_db()
        self.assertEqual(job.approved_cost, Decimal("500"))
        self.act("owner", job, "ready")
        self.act("owner", job, "complete")
        job.refresh_from_db()
        self.assertEqual(job.status, Status.COMPLETED)
        self.assertTrue(job.is_paid)
        self.assertEqual(job.total_price, Decimal("700"))

    def test_budget_auto_approves(self):
        job = self.make_job(Status.RECEIVED, max_budget=Decimal("600"))
        self.client.login(username="owner", password="pw12345pw")
        self.client.post(reverse("request_diagnose", args=[job.pk]), {"diagnosis": "Fan", "cost": "400", "days": "0"})
        job.refresh_from_db()
        self.assertEqual(job.status, Status.IN_REPAIR)

    def test_revised_quote_needs_new_approval(self):
        job = self.make_job(Status.IN_REPAIR, approved_cost=Decimal("400"), quoted_cost=Decimal("400"))
        self.client.login(username="owner", password="pw12345pw")
        self.client.post(reverse("request_diagnose", args=[job.pk]), {"diagnosis": "Worse than thought", "cost": "900", "days": "3"})
        job.refresh_from_db()
        self.assertEqual(job.status, Status.AWAITING_APPROVAL)

    def test_slot_capacity_and_rules(self):
        self.book()
        self.assertEqual(RepairRequest.objects.count(), 1)
        self.book()                                   # same hour, capacity is 1
        self.assertEqual(RepairRequest.objects.count(), 1)
        self.book(drop_slot=(timezone.localtime() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"))
        self.book(drop_slot=next_weekday_slot(hour=22, days=3).strftime("%Y-%m-%dT%H:%M"))
        self.assertEqual(RepairRequest.objects.count(), 1)

    def test_unsupported_device_and_express(self):
        self.book(device_type="tv")
        self.assertEqual(RepairRequest.objects.count(), 0)
        self.shop.express_fee = 0
        self.shop.save()
        self.book(express="on")
        self.assertEqual(RepairRequest.objects.count(), 0)

    def test_permissions_and_illegal_moves(self):
        job = self.make_job()
        self.assertEqual(self.act("other", job, "cancel").status_code, 404)    # stranger
        self.act("cust", job, "accept")                                        # customer can't accept
        job.refresh_from_db(); self.assertEqual(job.status, Status.PENDING)
        self.act("owner", job, "ready")                                        # can't skip steps
        job.refresh_from_db(); self.assertEqual(job.status, Status.PENDING)
        self.act("owner", job, "reject")                                       # reason required
        job.refresh_from_db(); self.assertEqual(job.status, Status.PENDING)
        self.act("owner", job, "reject", note="Parts unavailable")
        job.refresh_from_db(); self.assertEqual(job.status, Status.REJECTED)
        self.act("owner", job, "accept")                                       # finished jobs stay finished
        job.refresh_from_db(); self.assertEqual(job.status, Status.REJECTED)

    def test_decline_then_return(self):
        job = self.make_job(Status.AWAITING_APPROVAL, quoted_cost=Decimal("999"))
        self.act("cust", job, "decline")
        self.act("owner", job, "returned")
        job.refresh_from_db(); self.assertEqual(job.status, Status.RETURNED)

    def test_api_only_shows_own_requests(self):
        self.make_job()
        self.client.login(username="other", password="pw12345pw")
        self.assertEqual(len(self.client.get("/api/requests/").json()), 0)
        self.client.login(username="cust", password="pw12345pw")
        self.assertEqual(len(self.client.get("/api/requests/").json()), 1)
        self.assertEqual(self.client.get("/api/unread/").json(), {"unread": 0})
```
```bash
python manage.py test
```
- `setUp` runs before each test and builds users, a shop, etc. in a throwaway database.
- `self.client` is a pretend browser; `reverse()` builds URLs from names.
- Tests cover: happy path, budget shortcut, revised quote, slot rules/capacity, unsupported device/express, permissions and illegal moves, decline→return, and API privacy. **Whenever you change a rule, add a test first** — that is how professionals keep apps from breaking.

---

## 6. Loopholes found and how they are fixed

| Loophole / edge case | Fix |
|---|---|
| Customer double-clicks or two tabs → action runs twice | Compare-and-set `UPDATE … WHERE status IN (allowed)` in `apply()` |
| User jumps states by URL guessing (`/do/complete/`) | `TRANSITIONS` whitelist + `role` check + `@require_POST` |
| Customer reads someone else's request by changing the ID | `load_request()` → 404; API `get_queryset` filters by user |
| Shop edits the quote while customer clicks approve | `approved_cost = F("quoted_cost")` evaluated in the database |
| Diagnosis wrong after repair has started | Quote can be revised from `IN_REPAIR`; goes back to approval unless within the approved amount |
| Customer never answers a quote | Request stays `AWAITING_APPROVAL`; shop sees phone and can call (auto-expiry listed in Next steps) |
| Shop can't do the work / device unrepairable | `reject` / `unrepairable` require a written reason; device goes to `RETURNED` flow |
| Customer declines the quote | `DECLINED` → shop hands back → `RETURNED`; no charge |
| Express fee changes after booking | Fee copied into the request at booking time |
| Express asked from a shop without it | Form validation |
| Overbooking one hour | Capacity check by `slots_per_hour` |
| Past times, Sundays, midnight drop-offs, 6-month-ahead bookings | `clean_drop_slot` rules (checked in local time) |
| Negative costs, absurd durations | `min_value` / `max_value` in forms and validators on models |
| Shop doesn't repair that device | Form check + device filter on shop list |
| Customer asks to cancel after the device is received | Cancel only exists in `PENDING`/`ACCEPTED` |
| Shop account sends requests / customer sets up a shop | Role checks in views |
| Inactive shop still bookable | `is_active=True` filter in list and detail |
| HTML/script injection in text | Django auto-escaping; no `|safe` used anywhere |
| Cross-site request forgery | `{% csrf_token %}` + CSRF middleware |
| Raw passwords | `UserCreationForm` / `create_user` hash them |
| Secrets in code | Environment variables in `settings.py` |
| Payment | **Not integrated** (cash at shop; `is_paid` flag). Add a gateway later. |

---

## 7. Switching to MySQL

1. Install MySQL, then in the MySQL shell:
   ```sql
   CREATE DATABASE fixflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'fixflow'@'localhost' IDENTIFIED BY 'a-strong-password';
   GRANT ALL PRIVILEGES ON fixflow.* TO 'fixflow'@'localhost';
   ```
2. Set environment variables, then migrate **again** (a new database is empty):
   ```bash
   # macOS/Linux
   export DB_ENGINE=mysql DB_NAME=fixflow DB_USER=fixflow DB_PASSWORD='a-strong-password'
   # Windows PowerShell:  $env:DB_ENGINE="mysql"; $env:DB_NAME="fixflow"; $env:DB_USER="fixflow"; $env:DB_PASSWORD="a-strong-password"
   python manage.py migrate
   python manage.py seed_demo
   python manage.py runserver
   ```
3. Common errors: *Access denied* → wrong user/password; *Can't connect* → MySQL not running / wrong `DB_HOST`; *cryptography package required* → `pip install cryptography`.

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `TemplateDoesNotExist` | Template not in `/templates`, or `DIRS` in settings missing; check the file name |
| `NoReverseMatch` | The URL `name=` or its arguments don't match `{% url %}` |
| `no such table` | You forgot `makemigrations` + `migrate` |
| `CSRF verification failed` | Missing `{% csrf_token %}` inside a POST form |
| `ModuleNotFoundError: rest_framework` | venv not activated / `pip install` skipped |
| CSS not loading | `STATICFILES_DIRS` / `{% load static %}` missing; hard-refresh the browser |
| Changed a model, errors appear | Run `makemigrations` and `migrate`. In development, delete `db.sqlite3` and the migration files (not `__init__.py`) to start fresh |
| Page shows old data in a test | Use `obj.refresh_from_db()` |

When stuck: read the **last line** of the error first, then the first line that mentions *your* file.

---

## 9. Next steps (pick one at a time)
1. Auto-expire unanswered quotes after N days (a management command run by cron).
2. E-mail/SMS in `notify()` (Django `send_mail`, or Twilio).
3. Real payments (Razorpay) in place of cash.
4. Ratings/reviews after `COMPLETED`.
5. Pagination, photo upload (`ImageField`), a diagnosis fee for declined quotes.
6. Deploy: `DEBUG=0`, real `SECRET_KEY`, `ALLOWED_HOSTS`, `python manage.py collectstatic`, gunicorn + whitenoise.

---

## 10. The repeatable recipe for *any* Django app

1. **Write the story** (who does what, in what order). Draw the states.
2. **List the nouns** → these become **models**; list the verbs → **views**/actions.
3. `startproject`, `startapp`, add the app to `INSTALLED_APPS`.
4. Write **models** → `makemigrations` → `migrate` → register in **admin** and click around.
5. For each page: **URL → view → template** (build one page fully before the next).
6. Add **forms** wherever users type; put every rule in `clean_*`.
7. Protect everything: `@login_required`, ownership checks (`load_request` style), `@require_POST` for changes, `{% csrf_token %}`.
8. Add **tests** for the rules that would hurt most if broken.
9. Only then add polish: API, JavaScript, CSS.

**One-line memory aid:** *Model it → Migrate it → Route it → View it → Template it → Test it.*

### Cheat-sheet of every command
```bash
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
django-admin startproject config .
python manage.py startapp core
python manage.py makemigrations && python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo
python manage.py runserver
python manage.py test
```
