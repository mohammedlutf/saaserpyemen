# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt

from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, getdate, nowdate, today


DEFAULT_SETTINGS = {
	"enabled": 1,
	"brand_name": "Shopzad",
	"brand_name_ar": "شوب زاد",
	"website_domain": "shopzadmarket.com",
	"default_currency": "USD",
	"trial_days": 30,
	"grace_days": 3,
	"support_email": "support@shopzadmarket.com",
	"site_scheme": "http",
	"max_tenants_per_user": 0,
	"min_password_length": 8,
	"reserved_subdomains": "www,app,api,admin,mail,ftp,blog,support,billing,dashboard,status,cdn,static,assets,saas,demo,test,dev,staging,login,signup,payment,plans,docs,help,portal,erp,crm,shopzad,shopzadmarket",
}

SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])?$")


# ---------------------------------------------------------------------------
# Settings / environment
# ---------------------------------------------------------------------------
def get_settings():
	try:
		doc = frappe.get_cached_doc("SaaS Settings")
	except Exception:
		doc = frappe._dict(DEFAULT_SETTINGS)
	return doc


def is_tenant_site() -> bool:
	return bool(frappe.conf.get("saas_tenant"))


def is_central_site() -> bool:
	return not is_tenant_site()


def ensure_central():
	"""Redirect tenant sites to the ERPNext desk and block disabled platform."""
	if is_tenant_site():
		frappe.local.flags.redirect_location = "/app"
		raise frappe.Redirect

	settings = get_settings()
	if not cint(settings.enabled):
		frappe.throw(
			_("The SaaS platform is temporarily unavailable. Please try again later."),
			title=_("Maintenance"),
		)


def get_domain() -> str:
	domain = (get_settings().website_domain or "").strip().lower()
	domain = domain.replace("https://", "").replace("http://", "").strip("/")
	if not domain:
		domain = (frappe.local.site or "").replace("www.", "")
	return domain


def get_central_url() -> str:
	return (frappe.utils.get_url() or "").rstrip("/")


def get_site_url(subdomain: str) -> str:
	settings = get_settings()
	scheme = (settings.site_scheme or "http").strip().lower()
	return f"{scheme}://{subdomain}.{get_domain()}"


def get_full_site_name(subdomain: str) -> str:
	return f"{subdomain}.{get_domain()}"


def get_tenant_config(site: str | None = None) -> dict:
	site = site or frappe.local.site
	path = frappe.get_site_path("site_config.json") if site == frappe.local.site else None
	if path is None:
		path = frappe.utils.get_bench_path() + "/sites/" + site + "/site_config.json"
	try:
		with open(path) as fh:
			import json

			return json.load(fh)
	except Exception:
		return {}


# ---------------------------------------------------------------------------
# Subdomains
# ---------------------------------------------------------------------------
def normalize_subdomain(value: str | None) -> str:
	value = (value or "").strip().lower()
	value = value.replace("https://", "").replace("http://", "")
	value = value.split("/")[0].strip()
	if "." in value:
		value = value.split(".")[0]
	value = re.sub(r"[^a-z0-9-]+", "-", value)
	value = re.sub(r"-{2,}", "-", value).strip("-")
	return value


def get_reserved_subdomains() -> set[str]:
	raw = get_settings().reserved_subdomains or DEFAULT_SETTINGS["reserved_subdomains"]
	return {x.strip().lower() for x in re.split(r"[,\n]", raw) if x.strip()}


def validate_subdomain(value: str | None, check_availability: bool = False) -> str:
	sub = normalize_subdomain(value)
	if not sub:
		frappe.throw(_("Please enter a subdomain."))
	if len(sub) < 3:
		frappe.throw(_("Subdomain must be at least 3 characters long."))
	if len(sub) > 30:
		frappe.throw(_("Subdomain must be 30 characters or less."))
	if not SUBDOMAIN_RE.match(sub):
		frappe.throw(
			_("Use lowercase letters, numbers and hyphens only. It must start and end with a letter or number.")
		)
	if sub in get_reserved_subdomains():
		frappe.throw(_("This subdomain is reserved. Please choose another one."))
	if sub == get_domain().split(".")[0]:
		frappe.throw(_("This subdomain is reserved. Please choose another one."))

	if check_availability:
		if frappe.db.exists("SaaS Tenant", {"subdomain": sub}):
			frappe.throw(_("This subdomain is already taken. Please choose another one."))
		site = get_full_site_name(sub)
		settings = get_settings()
		if settings.sites_path:
			import os

			if os.path.exists(os.path.join(settings.sites_path, site)):
				frappe.throw(_("This subdomain is already taken. Please choose another one."))
		if frappe.db.exists("SaaS Tenant", sub):
			frappe.throw(_("This subdomain is already taken. Please choose another one."))
	return sub


def is_subdomain_available(value: str | None) -> tuple[bool, str, str]:
	try:
		sub = validate_subdomain(value, check_availability=True)
		return True, sub, ""
	except frappe.ValidationError as exc:
		return False, normalize_subdomain(value), str(exc)
	except Exception:
		return False, normalize_subdomain(value), _("Unable to validate this subdomain.")


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
def get_enabled_currencies() -> list[dict]:
	rows = frappe.get_all(
		"Currency",
		filters={"enabled": 1},
		fields=["name", "currency_name", "symbol", "symbol_on_right", "number_format"],
		order_by="name asc",
	)
	for row in rows:
		row["symbol_on_left"] = not bool(row.get("symbol_on_right"))
	if not rows:
		default = get_settings().default_currency or "USD"
		rows = [
			{
				"name": default,
				"currency_name": default,
				"symbol": default,
				"symbol_on_right": 0,
				"symbol_on_left": True,
			}
		]
	return rows


def get_currency_symbol(currency: str | None) -> str:
	if not currency:
		return ""
	symbol = frappe.db.get_value("Currency", currency, "symbol")
	return symbol or currency


def get_exchange_rate(from_currency: str, to_currency: str) -> float | None:
	if not from_currency or not to_currency:
		return None
	if from_currency == to_currency:
		return 1.0

	rate = frappe.db.get_value(
		"Currency Exchange",
		{
			"from_currency": from_currency,
			"to_currency": to_currency,
			"date": ["<=", nowdate()],
		},
		"exchange_rate",
		order_by="date desc",
	)
	if rate:
		return flt(rate)

	rate = frappe.db.get_value(
		"Currency Exchange",
		{
			"from_currency": to_currency,
			"to_currency": from_currency,
			"date": ["<=", nowdate()],
		},
		"exchange_rate",
		order_by="date desc",
	)
	if rate:
		return 1.0 / flt(rate)
	return None


def convert_amount(amount: float, from_currency: str, to_currency: str) -> float:
	amount = flt(amount)
	if not from_currency or not to_currency or from_currency == to_currency:
		return amount
	rate = get_exchange_rate(from_currency, to_currency)
	if rate is None:
		return amount
	return flt(amount * rate, 2)


def round_price(amount: float, currency: str | None) -> float:
	amount = flt(amount)
	if not amount:
		return 0.0
	if currency in ("YER", "IDR", "VND", "KRW", "CLP", "IQD"):
		return float(round(amount, 0))
	if currency in ("KWD", "BHD", "OMR"):
		return float(round(amount, 3))
	return float(round(amount, 2))


def get_plan_price(plan, currency: str | None = None, cycle: str = "Monthly") -> float:
	if isinstance(plan, str):
		plan = frappe.get_cached_doc("SaaS Plan", plan)

	currency = (currency or plan.currency or get_settings().default_currency or "USD").upper()
	cycle = (cycle or "Monthly").title()
	field = "yearly_price" if cycle == "Yearly" else "monthly_price"

	if currency == (plan.currency or "").upper():
		return round_price(flt(plan.get(field)), currency)

	for row in plan.get("prices") or []:
		if (row.currency or "").upper() == currency:
			value = flt(row.get(field))
			if value:
				return round_price(value, currency)

	base = flt(plan.get(field))
	if not base:
		return 0.0
	return round_price(convert_amount(base, plan.currency or "USD", currency), currency)


def get_plan_prices(plan, currency: str | None = None) -> dict:
	currency = (currency or plan.currency or get_settings().default_currency or "USD").upper()
	monthly = get_plan_price(plan, currency, "Monthly")
	yearly = get_plan_price(plan, currency, "Yearly")
	discount = 0
	if monthly and yearly and monthly * 12:
		discount = max(0, round((1 - (yearly / (monthly * 12))) * 100))
	return {
		"currency": currency,
		"monthly": monthly,
		"yearly": yearly,
		"yearly_discount": discount,
	}


def format_money(amount: float, currency: str | None = None) -> str:
	currency = currency or get_settings().default_currency or "USD"
	symbol = get_currency_symbol(currency)
	amount = flt(amount)
	if currency in ("YER", "IDR", "VND", "KRW", "CLP", "IQD"):
		value = f"{amount:,.0f}"
	elif currency in ("KWD", "BHD", "OMR"):
		value = f"{amount:,.3f}"
	else:
		value = f"{amount:,.2f}"
	if symbol == currency:
		return f"{value} {currency}"
	return f"{symbol}{value}"


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------
def get_plan_by_identifier(identifier: str | None):
	if not identifier:
		return None
	if frappe.db.exists("SaaS Plan", identifier):
		return frappe.get_cached_doc("SaaS Plan", identifier)
	name = frappe.db.get_value("SaaS Plan", {"slug": identifier}, "name")
	if name:
		return frappe.get_cached_doc("SaaS Plan", name)
	return None


def serialize_plan(plan, currency: str | None = None) -> dict:
	prices = get_plan_prices(plan, currency)
	features = []
	for row in plan.get("features") or []:
		features.append(
			{
				"en": row.feature_en,
				"ar": row.feature_ar or row.feature_en,
				"included": bool(row.included),
				"icon": row.icon or "check",
			}
		)
	return {
		"name": plan.name,
		"slug": plan.slug or frappe.scrub(plan.plan_name).replace("_", "-"),
		"plan_name": plan.plan_name,
		"tagline_en": plan.tagline_en,
		"tagline_ar": plan.tagline_ar or plan.tagline_en,
		"description_en": plan.description_en,
		"description_ar": plan.description_ar or plan.description_en,
		"color": plan.color or "#6366f1",
		"icon": plan.icon or "sparkles",
		"featured": bool(plan.is_featured),
		"currency": prices["currency"],
		"monthly": prices["monthly"],
		"yearly": prices["yearly"],
		"yearly_discount": prices["yearly_discount"],
		"trial_days": cint(plan.trial_days) or cint(get_settings().trial_days) or 30,
		"max_users": cint(plan.max_users),
		"max_branches": cint(plan.max_branches),
		"max_companies": cint(plan.max_companies),
		"storage_gb": cint(plan.storage_gb),
		"features": features,
		"website_description": plan.website_description,
	}


def get_public_plans(currency: str | None = None) -> list[dict]:
	plans = frappe.get_all(
		"SaaS Plan",
		filters={"enabled": 1},
		fields=["name"],
		order_by="sort_order asc, monthly_price asc",
	)
	return [serialize_plan(frappe.get_cached_doc("SaaS Plan", row.name), currency) for row in plans]


def get_plan_limits(plan) -> dict:
	if isinstance(plan, str):
		plan = frappe.get_cached_doc("SaaS Plan", plan)
	return {
		"plan": plan.name,
		"max_users": cint(plan.max_users),
		"max_branches": cint(plan.max_branches),
		"max_companies": cint(plan.max_companies),
		"storage_gb": cint(plan.storage_gb),
	}


# ---------------------------------------------------------------------------
# Subscriptions / billing periods
# ---------------------------------------------------------------------------
def get_trial_end(plan=None, start: date | None = None) -> date:
	start = getdate(start or today())
	days = cint(plan.trial_days) if plan else 0
	if not days:
		days = cint(get_settings().trial_days) or 30
	return add_days(start, days)


def get_billing_period(subscription, cycle: str | None = None) -> tuple[date, date]:
	"""Return the next period a manual payment should cover."""
	cycle = (cycle or subscription.billing_cycle or "Monthly").title()
	months = 12 if cycle == "Yearly" else 1
	current = getdate(today())

	base = current
	if subscription.status == "Pending":
		# First payment for an additional workspace: bill from the start date
		# (or today, whichever is later) and ignore the placeholder end date.
		start = getdate(subscription.start_date or today())
		if start > current:
			base = start
	elif subscription.status == "Trial" and subscription.trial_end_date:
		trial_end = getdate(subscription.trial_end_date)
		if trial_end >= current:
			base = add_days(trial_end, 1)
	elif subscription.end_date:
		end = getdate(subscription.end_date)
		if end >= current:
			base = add_days(end, 1)

	end = add_days(add_months(base, months), -1)
	return base, end


def get_days_left(value) -> int:
	if not value:
		return 0
	return (getdate(value) - getdate(today())).days


# ---------------------------------------------------------------------------
# Tenants / users
# ---------------------------------------------------------------------------
def is_manager() -> bool:
	roles = set(frappe.get_roles())
	return bool(roles & {"System Manager", "SaaS Manager"})


def get_user_tenants(user: str | None = None, include_cancelled: bool = False) -> list:
	user = user or frappe.session.user
	filters = {"owner_user": user}
	if not include_cancelled:
		filters["status"] = ["not in", ["Cancelled"]]
	return frappe.get_all(
		"SaaS Tenant",
		filters=filters,
		fields=["name", "tenant_name", "subdomain", "status", "plan"],
		order_by="creation desc",
	)


def get_tenant_for_user(user: str | None = None):
	user = user or frappe.session.user
	rows = get_user_tenants(user)
	if not rows:
		return None
	return frappe.get_doc("SaaS Tenant", rows[0].name)


def user_has_workspaces(user: str | None = None) -> bool:
	"""Return True when the user has ever created a workspace (trial used)."""
	user = user or frappe.session.user
	return bool(frappe.db.exists("SaaS Tenant", {"owner_user": user}))


def get_owned_tenant(tenant: str | None = None):
	if not tenant:
		doc = get_tenant_for_user()
		if not doc:
			frappe.throw(_("You do not have a workspace yet."))
		return doc

	if not frappe.db.exists("SaaS Tenant", tenant):
		frappe.throw(_("Workspace not found."))

	doc = frappe.get_doc("SaaS Tenant", tenant)
	if not is_manager() and doc.owner_user != frappe.session.user:
		frappe.throw(_("You do not have permission to access this workspace."), frappe.PermissionError)
	return doc


def get_tenant_subscription(tenant):
	if not tenant:
		return None
	if tenant.subscription and frappe.db.exists("SaaS Subscription", tenant.subscription):
		return frappe.get_doc("SaaS Subscription", tenant.subscription)
	name = frappe.db.get_value(
		"SaaS Subscription", {"tenant": tenant.name}, "name", order_by="creation desc"
	)
	return frappe.get_doc("SaaS Subscription", name) if name else None


def log_activity(tenant: str | None, action: str, details: str | None = None, user: str | None = None):
	try:
		frappe.get_doc(
			{
				"doctype": "SaaS Activity",
				"tenant": tenant,
				"user": user or frappe.session.user,
				"action": action,
				"details": details,
				"ip_address": getattr(frappe.local, "request_ip", None),
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS Activity Log Error")


def create_provisioning_log(tenant: str | None, site_name: str, action: str = "Provision"):
	try:
		return frappe.get_doc(
			{
				"doctype": "SaaS Provisioning Log",
				"tenant": tenant,
				"site_name": site_name,
				"action": action,
				"status": "Running",
				"started_on": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS Provisioning Log Error")
		return None


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def sanitize_redirect(value: str | None, fallback: str = "/dashboard") -> str:
	if not value:
		return fallback
	value = value.strip()
	if not value.startswith("/") or value.startswith("//"):
		return fallback
	return value


def generate_password(length: int = 18) -> str:
	alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%"
	return "".join(secrets.choice(alphabet) for _ in range(length))


def get_countries() -> list[dict]:
	try:
		return frappe.get_all("Country", fields=["name"], order_by="name asc")
	except Exception:
		return []


def get_currency_options() -> list[dict]:
	return get_enabled_currencies()


def parse_date(value):
	if not value:
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	return getdate(value)


def get_plan_limit_label(value: int, en: str, ar: str) -> dict:
	return {
		"value": value,
		"en": _("Unlimited") if not value else f"{value} {en}",
		"ar": _("غير محدود") if not value else f"{value} {ar}",
	}
