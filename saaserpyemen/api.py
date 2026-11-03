# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	add_months,
	cint,
	flt,
	formatdate,
	getdate,
	nowdate,
	today,
	validate_email_address,
)

from saaserpyemen import provisioning, tenant_ops
from saaserpyemen.i18n import status_label
from saaserpyemen.utils import (
	convert_amount,
	create_provisioning_log,
	ensure_central,
	format_money,
	get_billing_period,
	get_central_url,
	get_days_left,
	get_domain,
	get_enabled_currencies,
	get_full_site_name,
	get_months_amount,
	get_owned_tenant,
	get_plan_by_identifier,
	get_plan_limits,
	get_plan_price,
	get_public_plans,
	get_site_url,
	get_tenant_for_user,
	get_tenant_subscription,
	get_trial_end,
	is_manager,
	is_subdomain_available,
	log_activity,
	normalize_subdomain,
	sanitize_redirect,
	serialize_plan,
	user_has_workspaces,
	validate_subdomain,
)
from saaserpyemen.utils import get_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to continue."), frappe.PermissionError)


def _rate_limit(bucket: str, limit: int, window: int = 3600):
	limit = cint(limit)
	if not limit:
		return
	ip = getattr(frappe.local, "request_ip", None) or "unknown"
	key = f"saas_rate:{bucket}:{ip}"
	count = cint(frappe.cache.get_value(key) or 0)
	if count >= limit:
		frappe.throw(_("Too many attempts. Please try again later."), frappe.RateLimitExceededError)
	frappe.cache.set_value(key, count + 1, expires_in_sec=window)


def _ensure_currency(currency: str) -> str:
	currency = (currency or "").upper()
	if not currency:
		currency = get_settings().default_currency or "USD"
	if not frappe.db.exists("Currency", {"name": currency, "enabled": 1}):
		frappe.throw(_("The selected currency is not available."))
	return currency


def _serialize_date(value):
	return str(value) if value else None


def _serialize_subscription(subscription) -> dict:
	if not subscription:
		return None
	plan = get_plan_by_identifier(subscription.plan)
	return {
		"name": subscription.name,
		"plan": subscription.plan,
		"plan_name": plan.plan_name if plan else subscription.plan,
		"status": subscription.status,
		"billing_cycle": subscription.billing_cycle,
		"currency": subscription.currency,
		"amount": flt(subscription.amount),
		"payment_status": subscription.payment_status,
		"start_date": _serialize_date(subscription.start_date),
		"trial_end_date": _serialize_date(subscription.trial_end_date),
		"end_date": _serialize_date(subscription.end_date),
		"next_billing_date": _serialize_date(subscription.next_billing_date),
		"days_left": get_days_left(subscription.end_date or subscription.trial_end_date),
		"auto_renew": bool(subscription.auto_renew),
		"cancelled_on": _serialize_date(subscription.cancelled_on),
		"cancel_reason": subscription.cancel_reason,
	}


def _serialize_payment(payment) -> dict:
	months = cint(payment.get("months")) or 1
	return {
		"name": payment.name,
		"amount": flt(payment.amount),
		"currency": payment.currency,
		"status": payment.status,
		"is_invoice": bool(cint(payment.get("is_invoice"))),
		"months": months,
		"months_label": _month_label(months),
		"billing_cycle": payment.billing_cycle,
		"period_start": _serialize_date(payment.period_start),
		"period_end": _serialize_date(payment.period_end),
		"due_date": _serialize_date(payment.get("due_date")),
		"invoice_key": payment.get("invoice_key"),
		"payment_method": payment.payment_method,
		"reference_no": payment.reference_no,
		"paid_on": _serialize_date(payment.paid_on),
		"receipt": payment.receipt,
		"notes": payment.notes,
		"creation": str(payment.creation),
		"pdf_url": f"/api/method/saaserpyemen.api.download_payment_invoice?payment={payment.name}",
	}


# Prepaid durations offered on the payment page. Twelve months are billed at
# the plan's yearly price, which usually carries a discount.
PAYMENT_MONTH_OPTIONS = (1, 2, 3, 4, 12)
PAYMENT_FIELDS = [
	"name",
	"tenant",
	"subscription",
	"plan",
	"amount",
	"currency",
	"status",
	"is_invoice",
	"months",
	"billing_cycle",
	"period_start",
	"period_end",
	"due_date",
	"invoice_key",
	"payment_method",
	"reference_no",
	"paid_on",
	"receipt",
	"notes",
	"creation",
]


def _month_label(months: int) -> str:
	if months == 12:
		return _("12 months (one year)")
	if months == 1:
		return _("1 month")
	if months == 2:
		return _("2 months")
	if months == 3:
		return _("3 months")
	if months == 4:
		return _("4 months")
	return _("{0} months").format(months)


def _normalize_months(subscription, value) -> int:
	months = cint(value)
	if months < 1 or months > 12:
		months = 12 if str(subscription.billing_cycle or "").lower().startswith("y") else 1
	return months


def _payment_amount(plan, subscription, months: int, currency: str | None = None) -> float:
	fallback = flt(subscription.amount)
	if str(subscription.billing_cycle or "").lower().startswith("y") and fallback:
		fallback = fallback / 12
	return get_months_amount(
		plan,
		currency or subscription.currency,
		months,
		fallback_monthly=fallback,
	)


def _payment_period(subscription, months: int, invoice=None):
	"""Return the period covered by a payment.

	When paying an issued invoice, its start date is authoritative so the
	new period begins where the previous one ended. If the subscription was
	already extended in the meantime, start after the current end date.
	"""
	start = None
	if invoice:
		start = invoice.get("period_start")
	if start:
		start = getdate(start)
		if subscription.end_date and getdate(subscription.end_date) >= start:
			start = add_days(getdate(subscription.end_date), 1)
		return start, add_days(add_months(start, months), -1)
	return get_billing_period(subscription, months=months)


def _notify_payment_submitted(payment, tenant):
	settings = get_settings()
	recipients = []
	if settings.support_email:
		recipients.append(settings.support_email)
	# Notify users with SaaS Manager / System Manager roles without scanning every user.
	manager_emails = frappe.db.sql(
		"""
		select distinct u.email
		from `tabUser` u
		inner join `tabHas Role` hr on hr.parent = u.name
		where hr.role in ('System Manager', 'SaaS Manager')
			and u.enabled = 1
			and u.email is not null
		""",
		as_dict=True,
	)
	recipients.extend(row.email for row in manager_emails if row.email)
	recipients = list(dict.fromkeys(recipients))
	if not recipients:
		return
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=_("New manual payment awaiting review: {0}").format(tenant.tenant_name),
			message=f"""
				<p>A new manual payment was submitted.</p>
				<ul>
					<li><b>Tenant:</b> {frappe.utils.escape_html(tenant.tenant_name)} ({frappe.utils.escape_html(tenant.name)})</li>
					<li><b>Payment:</b> {frappe.utils.escape_html(payment.name)}</li>
					<li><b>Amount:</b> {frappe.utils.escape_html(str(payment.amount))} {frappe.utils.escape_html(payment.currency or "")}</li>
					<li><b>Reference:</b> {frappe.utils.escape_html(payment.reference_no or "-")}</li>
				</ul>
				<p><a href="{get_central_url()}/app/saas-payment/{frappe.utils.escape_html(payment.name)}">Review payment</a></p>
			""",
			now=False,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS Payment Notification")


def _notify_tenant(tenant, subject, message):
	if not tenant.admin_email:
		return
	try:
		frappe.sendmail(recipients=[tenant.admin_email], subject=subject, message=message, now=False)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS Tenant Notification")


def _attach_receipt(payment, file_url: str) -> None:
	"""Link an uploaded private file to the payment so permissions follow the document."""
	try:
		file_name = frappe.db.get_value("File", {"file_url": file_url}, "name", order_by="creation desc")
		if not file_name:
			return
		file_doc = frappe.get_doc("File", file_name)
		if file_doc.owner not in (frappe.session.user, "Administrator") and not is_manager():
			return
		file_doc.attached_to_doctype = "SaaS Payment"
		file_doc.attached_to_name = payment.name
		file_doc.attached_to_field = "receipt"
		file_doc.flags.ignore_permissions = True
		file_doc.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS payment receipt attach")


# ---------------------------------------------------------------------------
# Public catalogue
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
def get_plans(currency: str | None = None):
	settings = get_settings()
	currency = (currency or settings.default_currency or "USD").upper()
	currencies = get_enabled_currencies()
	allowed = {row["name"] for row in currencies}
	if currency not in allowed:
		currency = settings.default_currency if settings.default_currency in allowed else next(iter(allowed), "USD")

	plans = get_public_plans(currency)
	return {
		"plans": plans,
		"currencies": currencies,
		"default_currency": currency,
		"domain": get_domain(),
		"trial_days": cint(settings.trial_days) or 30,
		"brand_name": settings.brand_name,
		"brand_name_ar": settings.brand_name_ar,
	}


@frappe.whitelist(allow_guest=True)
def get_currencies():
	return get_enabled_currencies()


@frappe.whitelist(allow_guest=True)
def check_subdomain(subdomain: str):
	available, normalized, message = is_subdomain_available(subdomain)
	return {
		"available": available,
		"subdomain": normalized,
		"site_name": get_full_site_name(normalized) if normalized else "",
		"url": get_site_url(normalized) if normalized and available else "",
		"message": message,
	}


# ---------------------------------------------------------------------------
# Signup / auth
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
def signup(
	full_name: str,
	email: str,
	password: str,
	username: str | None = None,
	company_name: str | None = None,
	phone: str | None = None,
	country: str | None = None,
	language: str = "en",
	redirect: str | None = None,
):
	ensure_central()
	settings = get_settings()
	_rate_limit("signup", settings.signup_rate_limit or 10)

	full_name = (full_name or "").strip()
	email = (email or "").strip().lower()
	password = password or ""
	username = (username or "").strip().lower()
	language = language if language in ("en", "ar") else "en"

	if not full_name:
		frappe.throw(_("Please enter your full name."))
	if not email:
		frappe.throw(_("Please enter your email address."))
	validate_email_address(email, throw=True)
	if len(password) < (cint(settings.min_password_length) or 8):
		frappe.throw(_("Password must be at least {0} characters long.").format(cint(settings.min_password_length) or 8))
	if username and not re.match(r"^[a-zA-Z0-9._-]{3,30}$", username):
		frappe.throw(_("Username may contain letters, numbers, dots, underscores and hyphens only."))

	if frappe.db.exists("User", email):
		frappe.throw(_("An account with this email already exists. Please sign in instead."))
	if username and frappe.db.exists("User", {"username": username}):
		frappe.throw(_("This username is already taken."))

	parts = full_name.split(" ", 1)
	user = frappe.new_doc("User")
	user.update(
		{
			"email": email,
			"first_name": parts[0],
			"last_name": parts[1] if len(parts) > 1 else "",
			"enabled": 1,
			"user_type": "Website User",
			"new_password": password,
			"send_welcome_email": 0,
			"username": username or None,
			"saas_company_name": (company_name or "").strip(),
			"saas_phone": (phone or "").strip(),
			"saas_country": country or None,
			"saas_preferred_language": language,
			"saas_signup_source": "Email",
		}
	)
	user.flags.ignore_permissions = True
	user.flags.no_welcome_mail = True
	user.insert(ignore_permissions=True)

	if frappe.db.exists("Role", "SaaS Customer"):
		user.add_roles("SaaS Customer")

	log_activity(None, "Signup", f"New account created via website: {email}", user=user.name)
	frappe.db.commit()

	try:
		frappe.local.login_manager.login_as(user.name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS Signup Login")

	redirect = sanitize_redirect(redirect, "/plans")
	return {"ok": True, "redirect": redirect, "user": user.name}


# ---------------------------------------------------------------------------
# Subscriptions / tenants
# ---------------------------------------------------------------------------
@frappe.whitelist()
def create_subscription(
	plan: str,
	billing_cycle: str = "Monthly",
	currency: str = "USD",
	subdomain: str | None = None,
	company_name: str | None = None,
	phone: str | None = None,
	country: str | None = None,
	language: str = "en",
	existing_tenant: str | None = None,
):
	_require_login()
	ensure_central()
	settings = get_settings()

	plan_doc = get_plan_by_identifier(plan)
	if not plan_doc or not cint(plan_doc.enabled):
		frappe.throw(_("The selected plan is not available."))

	if existing_tenant:
		return change_plan(existing_tenant, plan_doc.name, billing_cycle, currency)

	billing_cycle = "Yearly" if (billing_cycle or "").lower().startswith("y") else "Monthly"
	currency = _ensure_currency(currency)
	language = language if language in ("en", "ar") else "en"
	company_name = (company_name or "").strip()
	if not company_name:
		frappe.throw(_("Please enter your company or workspace name."))

	max_tenants = cint(settings.max_tenants_per_user)
	if max_tenants:
		tenant_count = frappe.db.count("SaaS Tenant", {"owner_user": frappe.session.user})
		if tenant_count >= max_tenants:
			frappe.throw(_("You have reached the maximum number of workspaces for your account."))

	# The free trial belongs to the customer's first workspace only.  Any
	# additional workspace is a paid subscription: it stays pending until the
	# first payment is approved, and only then is its site provisioned.
	is_first_workspace = not user_has_workspaces()

	subdomain = validate_subdomain(subdomain, check_availability=True)

	tenant = frappe.new_doc("SaaS Tenant")
	tenant.update(
		{
			"tenant_name": company_name,
			"subdomain": subdomain,
			"plan": plan_doc.name,
			"owner_user": frappe.session.user,
			"admin_full_name": frappe.db.get_value("User", frappe.session.user, "full_name")
			or frappe.session.user,
			"admin_email": frappe.db.get_value("User", frappe.session.user, "email") or frappe.session.user,
			"phone": (phone or "").strip() or frappe.db.get_value("User", frappe.session.user, "saas_phone"),
			"country": country or frappe.db.get_value("User", frappe.session.user, "saas_country"),
			"currency": currency,
			"language": language,
			"status": "Provisioning" if is_first_workspace else "Pending Payment",
			"provisioning_status": "Pending",
			"created_via": "Website",
		}
	)
	tenant.flags.ignore_permissions = True
	tenant.insert(ignore_permissions=True)

	amount = get_plan_price(plan_doc, currency, billing_cycle)
	if is_first_workspace:
		trial_end = get_trial_end(plan_doc)
		subscription_status = "Trial"
		period_end = trial_end
	else:
		trial_end = None
		subscription_status = "Pending"
		period_end = today()

	subscription = frappe.new_doc("SaaS Subscription")
	subscription.update(
		{
			"tenant": tenant.name,
			"plan": plan_doc.name,
			"status": subscription_status,
			"billing_cycle": billing_cycle,
			"currency": currency,
			"amount": amount,
			"start_date": today(),
			"trial_end_date": trial_end,
			"end_date": period_end,
			"next_billing_date": period_end if is_first_workspace else None,
			"payment_status": "Unpaid",
			"auto_renew": 1,
		}
	)
	subscription.flags.ignore_permissions = True
	subscription.insert(ignore_permissions=True)

	tenant.db_set("subscription", subscription.name, update_modified=False)
	tenant.db_set("trial_ends_on", trial_end, update_modified=False)
	tenant.db_set("subscription_ends_on", period_end, update_modified=False)

	frappe.db.commit()

	if is_first_workspace:
		provisioning.enqueue_provisioning(tenant.name)
		redirect = f"/provisioning?tenant={tenant.name}"
	else:
		redirect = f"/payment?tenant={tenant.name}"

	log_activity(
		tenant.name,
		"Subscription created",
		(
			f"Plan: {plan_doc.plan_name}, cycle: {billing_cycle}, trial ends: {trial_end}"
			if is_first_workspace
			else f"Plan: {plan_doc.plan_name}, cycle: {billing_cycle}, awaiting first payment"
		),
	)

	return {
		"ok": True,
		"tenant": tenant.name,
		"subscription": subscription.name,
		"requires_payment": not is_first_workspace,
		"redirect": redirect,
	}


@frappe.whitelist()
def change_plan(tenant: str, plan: str, billing_cycle: str = "Monthly", currency: str = "USD", force: int = 0):
	_require_login()
	tenant_doc = get_owned_tenant(tenant)
	plan_doc = get_plan_by_identifier(plan)
	if not plan_doc or not cint(plan_doc.enabled):
		frappe.throw(_("The selected plan is not available."))

	billing_cycle = "Yearly" if (billing_cycle or "").lower().startswith("y") else "Monthly"
	currency = _ensure_currency(currency)

	if not (cint(force) and is_manager()):
		limits = get_plan_limits(plan_doc)
		checks = [
			("users_count", "max_users", _("users")),
			("branches_count", "max_branches", _("branches")),
			("companies_count", "max_companies", _("companies")),
		]
		for used_field, limit_field, label in checks:
			limit = limits[limit_field]
			used = cint(tenant_doc.get(used_field))
			if limit and used > limit:
				frappe.throw(
					_("Your current usage ({0} {1}) exceeds the {2} plan limit ({3}). Please upgrade or reduce usage first.").format(
						used, label, plan_doc.plan_name, limit
					)
				)

	subscription = get_tenant_subscription(tenant_doc)
	if not subscription:
		frappe.throw(_("This workspace has no subscription."))

	subscription.plan = plan_doc.name
	subscription.billing_cycle = billing_cycle
	subscription.currency = currency
	subscription.amount = get_plan_price(plan_doc, currency, billing_cycle)
	subscription.flags.ignore_permissions = True
	subscription.save(ignore_permissions=True)

	tenant_doc.plan = plan_doc.name
	tenant_doc.currency = currency
	tenant_doc.flags.ignore_permissions = True
	tenant_doc.save(ignore_permissions=True)

	frappe.db.commit()
	tenant_ops.push_limits(tenant_doc)
	log_activity(
		tenant_doc.name,
		"Plan changed",
		f"New plan: {plan_doc.plan_name}, cycle: {billing_cycle}, currency: {currency}",
	)
	return {"ok": True, "redirect": f"/dashboard?tenant={tenant_doc.name}&tab=billing"}


@frappe.whitelist()
def get_dashboard(tenant: str | None = None):
	_require_login()
	tenant_doc = get_owned_tenant(tenant)
	subscription = get_tenant_subscription(tenant_doc)
	plan = get_plan_by_identifier(tenant_doc.plan) if tenant_doc.plan else None
	payments = frappe.get_all(
		"SaaS Payment",
		filters={"tenant": tenant_doc.name},
		fields=PAYMENT_FIELDS,
		order_by="creation desc",
		limit=20,
	)
	open_invoices = frappe.get_all(
		"SaaS Payment",
		filters={"tenant": tenant_doc.name, "status": "Unpaid"},
		fields=PAYMENT_FIELDS,
		order_by="due_date asc, creation asc",
	)
	pending_rows = frappe.get_all(
		"SaaS Payment",
		filters={"tenant": tenant_doc.name, "status": "Pending Review"},
		fields=PAYMENT_FIELDS,
		order_by="creation desc",
		limit=1,
	)
	pending = pending_rows[0] if pending_rows else None
	limits = get_plan_limits(plan) if plan else {}
	usage = {
		"users": {
			"used": cint(tenant_doc.users_count),
			"limit": limits.get("max_users", 0),
			"percent": min(100, round((cint(tenant_doc.users_count) / limits["max_users"]) * 100)) if limits.get("max_users") else 0,
		},
		"branches": {
			"used": cint(tenant_doc.branches_count),
			"limit": limits.get("max_branches", 0),
			"percent": min(100, round((cint(tenant_doc.branches_count) / limits["max_branches"]) * 100)) if limits.get("max_branches") else 0,
		},
		"companies": {
			"used": cint(tenant_doc.companies_count),
			"limit": limits.get("max_companies", 0),
			"percent": min(100, round((cint(tenant_doc.companies_count) / limits["max_companies"]) * 100)) if limits.get("max_companies") else 0,
		},
		"storage": {
			"used_mb": flt(tenant_doc.storage_used_mb),
			"limit_gb": limits.get("storage_gb", 0),
			"percent": min(100, round((flt(tenant_doc.storage_used_mb) / (limits["storage_gb"] * 1024)) * 100)) if limits.get("storage_gb") else 0,
		},
	}
	return {
		"tenant": {
			"name": tenant_doc.name,
			"tenant_name": tenant_doc.tenant_name,
			"subdomain": tenant_doc.subdomain,
			"site_name": tenant_doc.site_name,
			"status": tenant_doc.status,
			"provisioning_status": tenant_doc.provisioning_status,
			"plan": tenant_doc.plan,
			"site_url": get_site_url(tenant_doc.subdomain),
			"admin_email": tenant_doc.admin_email,
			"currency": tenant_doc.currency,
			"language": tenant_doc.language,
			"trial_ends_on": _serialize_date(tenant_doc.trial_ends_on),
			"subscription_ends_on": _serialize_date(tenant_doc.subscription_ends_on),
			"last_usage_sync": str(tenant_doc.last_usage_sync) if tenant_doc.last_usage_sync else None,
		},
		"plan": serialize_plan(plan, tenant_doc.currency) if plan else None,
		"subscription": _serialize_subscription(subscription),
		"usage": usage,
		"payments": [_serialize_payment(frappe._dict(row)) for row in payments],
		"pending_payment": _serialize_payment(frappe._dict(pending)) if pending else None,
		"open_invoices": [_serialize_payment(frappe._dict(row)) for row in open_invoices],
		"open_invoice": _serialize_payment(frappe._dict(open_invoices[0])) if open_invoices else None,
		"days_left": (
			get_days_left(subscription.end_date or subscription.trial_end_date)
			if subscription and subscription.status != "Pending"
			else None
		),
		"payment_url": f"/payment?tenant={tenant_doc.name}",
		"upgrade_url": f"/plans?change=1&tenant={tenant_doc.name}",
		"dashboard_url": "/dashboard",
	}


@frappe.whitelist()
def get_provisioning_status(tenant: str):
	_require_login()
	tenant_doc = get_owned_tenant(tenant)
	log_text = tenant_doc.provisioning_log or ""
	return {
		"tenant": tenant_doc.name,
		"tenant_name": tenant_doc.tenant_name,
		"status": tenant_doc.status,
		"provisioning_status": tenant_doc.provisioning_status,
		"site_url": get_site_url(tenant_doc.subdomain),
		"log": log_text[-6000:],
		"completed": tenant_doc.provisioning_status == "Completed",
		"failed": tenant_doc.provisioning_status == "Failed",
		"redirect": "/dashboard" if tenant_doc.provisioning_status == "Completed" else None,
	}


@frappe.whitelist()
def get_tenant_credentials(tenant: str):
	_require_login()
	tenant_doc = get_owned_tenant(tenant)
	password = tenant_doc.get_password("admin_temp_password", raise_exception=False)
	if not is_manager():
		log_activity(tenant_doc.name, "Credentials viewed", "Workspace credentials revealed by owner.")
	return {
		"email": tenant_doc.admin_email,
		"password": password,
		"login_url": get_site_url(tenant_doc.subdomain) + "/login",
		"site_url": get_site_url(tenant_doc.subdomain),
	}


@frappe.whitelist()
def update_profile(
	tenant: str,
	company_name: str | None = None,
	phone: str | None = None,
	country: str | None = None,
	language: str | None = None,
):
	_require_login()
	tenant_doc = get_owned_tenant(tenant)
	old_name = tenant_doc.tenant_name

	if company_name:
		tenant_doc.tenant_name = company_name.strip()
	if phone is not None:
		tenant_doc.phone = phone.strip()
	if country is not None:
		tenant_doc.country = country or None
	if language in ("en", "ar"):
		tenant_doc.language = language

	tenant_doc.flags.ignore_permissions = True
	tenant_doc.save(ignore_permissions=True)

	user = frappe.get_doc("User", frappe.session.user)
	user.saas_company_name = tenant_doc.tenant_name
	user.saas_phone = tenant_doc.phone
	user.saas_country = tenant_doc.country
	user.saas_preferred_language = tenant_doc.language
	user.flags.ignore_permissions = True
	user.save(ignore_permissions=True)

	frappe.db.commit()
	if old_name != tenant_doc.tenant_name:
		frappe.enqueue(
			"saaserpyemen.tenant_ops.update_site_company",
			queue="short",
			timeout=300,
			tenant=tenant_doc.name,
			company_name=tenant_doc.tenant_name,
		)
	return {"ok": True, "message": _("Profile updated.")}


@frappe.whitelist()
def cancel_subscription(tenant: str, reason: str | None = None):
	_require_login()
	tenant_doc = get_owned_tenant(tenant)
	subscription = get_tenant_subscription(tenant_doc)
	if not subscription:
		frappe.throw(_("This workspace has no subscription."))
	subscription.auto_renew = 0
	subscription.cancelled_on = today()
	subscription.cancel_reason = (reason or "").strip() or _("Cancelled by customer")
	if subscription.status == "Pending":
		# A workspace that was never paid for has no period to run out: cancel it
		# immediately so it cannot be paid for or provisioned later.
		subscription.status = "Cancelled"
	subscription.flags.ignore_permissions = True
	subscription.save(ignore_permissions=True)
	frappe.db.commit()
	log_activity(tenant_doc.name, "Subscription cancelled", subscription.cancel_reason)

	# Invoices are issued ahead of the billing period, so a cancellation closes
	# any invoice that has not been paid yet instead of leaving a stale debt on
	# the dashboard.
	open_invoices = frappe.get_all(
		"SaaS Payment",
		filters={"tenant": tenant_doc.name, "status": "Unpaid"},
		pluck="name",
	)
	if open_invoices:
		current_user = frappe.session.user
		frappe.set_user("Administrator")
		try:
			for payment_name in open_invoices:
				invoice = frappe.get_doc("SaaS Payment", payment_name)
				invoice.status = "Rejected"
				invoice.notes = (
					(invoice.notes or "")
					+ "\n"
					+ _("Closed because the workspace subscription was cancelled.")
				).strip()
				invoice.flags.ignore_permissions = True
				invoice.save(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "SaaS close invoices on cancellation")
		finally:
			frappe.set_user(current_user)
		frappe.db.commit()

	if subscription.status == "Cancelled":
		# Reject any payment that was waiting for review so it cannot be
		# approved later and silently reactivate a cancelled workspace.
		current_user = frappe.session.user
		frappe.set_user("Administrator")
		try:
			for payment_name in frappe.get_all(
				"SaaS Payment",
				filters={"tenant": tenant_doc.name, "status": "Pending Review"},
				pluck="name",
			):
				frappe.get_doc("SaaS Payment", payment_name).reject(
					_("Workspace cancelled before activation")
				)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "SaaS reject payments on cancellation")
		finally:
			frappe.set_user(current_user)
		return {
			"ok": True,
			"message": _("This workspace was cancelled before activation."),
		}
	return {
		"ok": True,
		"message": _("Your subscription will not renew. You can keep using the workspace until {0}.").format(
			subscription.end_date or subscription.trial_end_date
		),
	}


# ---------------------------------------------------------------------------
# Manual payments
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_payment_context(tenant: str | None = None):
	_require_login()
	tenant_doc = get_owned_tenant(tenant)
	subscription = get_tenant_subscription(tenant_doc)
	if not subscription:
		frappe.throw(_("This workspace has no subscription."))

	plan = get_plan_by_identifier(subscription.plan)
	currency = subscription.currency or tenant_doc.currency or get_settings().default_currency or "USD"
	payments = frappe.get_all(
		"SaaS Payment",
		filters={"tenant": tenant_doc.name},
		fields=PAYMENT_FIELDS,
		order_by="creation desc",
		limit=50,
	)
	open_invoices = frappe.get_all(
		"SaaS Payment",
		filters={"tenant": tenant_doc.name, "status": "Unpaid"},
		fields=PAYMENT_FIELDS,
		order_by="due_date asc, creation asc",
	)
	pending_rows = frappe.get_all(
		"SaaS Payment",
		filters={"tenant": tenant_doc.name, "status": "Pending Review"},
		fields=PAYMENT_FIELDS,
		order_by="creation desc",
		limit=1,
	)
	pending = pending_rows[0] if pending_rows else None

	# `?invoice=...` comes from the "Pay now" buttons on the dashboard.
	requested = (frappe.local.request.args.get("invoice") or "").strip() if getattr(frappe.local, "request", None) else ""
	invoice = None
	if requested:
		invoice = next((row for row in open_invoices if row.name == requested), None)
		if not invoice:
			row = frappe.db.get_value(
				"SaaS Payment", requested, PAYMENT_FIELDS, as_dict=True
			)
			if not row or row.tenant != tenant_doc.name:
				frappe.throw(_("Invoice not found."))
			invoice = row
		if invoice.status not in ("Unpaid", "Pending Review"):
			frappe.throw(_("This invoice is no longer open for payment."))
	elif open_invoices:
		invoice = open_invoices[0]

	months = _normalize_months(subscription, invoice.months if invoice else None)
	period_start, period_end = _payment_period(subscription, months, invoice)
	amount = _payment_amount(plan, subscription, months, currency)

	options = list(PAYMENT_MONTH_OPTIONS)
	if months not in options:
		options.append(months)
		options.sort()
	month_options = []
	for value in options:
		option_start, option_end = _payment_period(subscription, value, invoice)
		option_amount = _payment_amount(plan, subscription, value, currency)
		month_options.append(
			{
				"months": value,
				"label": _month_label(value),
				"amount": option_amount,
				"amount_display": format_money(option_amount, currency),
				"billing_cycle": "Yearly" if value == 12 else "Monthly",
				"period_start": str(option_start),
				"period_end": str(option_end),
				"period_display": "{0} – {1}".format(
					formatdate(option_start, "dd MMM yyyy"),
					formatdate(option_end, "dd MMM yyyy"),
				),
			}
		)

	settings = get_settings()
	return {
		"tenant": {
			"name": tenant_doc.name,
			"tenant_name": tenant_doc.tenant_name,
			"subdomain": tenant_doc.subdomain,
			"currency": tenant_doc.currency,
			"status": tenant_doc.status,
		},
		"subscription": _serialize_subscription(subscription),
		"plan": serialize_plan(plan, subscription.currency) if plan else None,
		"amount": amount,
		"amount_display": format_money(amount, currency),
		"currency": currency,
		"months": months,
		"months_label": _month_label(months),
		"month_options": month_options,
		"period_start": str(period_start),
		"period_end": str(period_end),
		"period_display": "{0} – {1}".format(
			formatdate(period_start, "dd MMM yyyy"),
			formatdate(period_end, "dd MMM yyyy"),
		),
		"invoice": _serialize_payment(invoice) if invoice else None,
		"open_invoices": [_serialize_payment(row) for row in open_invoices],
		"bank_details": settings.bank_details,
		"bank_details_ar": settings.bank_details_ar,
		"payment_note_en": settings.payment_note_en,
		"payment_note_ar": settings.payment_note_ar,
		"payments": [_serialize_payment(row) for row in payments],
		"pending_payment": _serialize_payment(pending) if pending else None,
	}


@frappe.whitelist()
def submit_payment(
	tenant: str | None = None,
	reference_no: str | None = None,
	payment_method: str = "Bank Transfer",
	notes: str | None = None,
	receipt: str | None = None,
	amount: float | None = None,
	invoice: str | None = None,
	months: int | None = None,
):
	_require_login()

	invoice_row = None
	invoice = (invoice or "").strip() or None
	if invoice:
		invoice_row = frappe.db.get_value(
			"SaaS Payment", invoice, PAYMENT_FIELDS, as_dict=True
		)
		if not invoice_row:
			frappe.throw(_("Invoice not found."))
		if tenant and tenant != invoice_row.tenant:
			frappe.throw(_("This invoice does not belong to the selected workspace."))
		tenant = invoice_row.tenant
		if invoice_row.status != "Unpaid":
			frappe.throw(_("This invoice is no longer open for payment."))

	if not tenant:
		frappe.throw(_("A valid workspace is required."))
	tenant_doc = get_owned_tenant(tenant)
	subscription = get_tenant_subscription(tenant_doc)
	if not subscription:
		frappe.throw(_("This workspace has no subscription."))
	if subscription.status == "Cancelled":
		frappe.throw(
			_("This workspace has been cancelled. Please create a new workspace to continue.")
		)

	pending = frappe.db.get_value(
		"SaaS Payment", {"tenant": tenant_doc.name, "status": "Pending Review"}, "name"
	)
	if pending and (not invoice_row or pending != invoice_row.name):
		frappe.throw(
			_("You already have a payment awaiting review. Please wait for our team to approve it before submitting another one.")
		)

	# If the customer opened the plain payment page while an invoice is open,
	# reuse that invoice instead of creating a duplicate obligation.
	if not invoice_row:
		open_invoice = frappe.db.get_value(
			"SaaS Payment",
			{"tenant": tenant_doc.name, "status": "Unpaid"},
			PAYMENT_FIELDS,
			as_dict=True,
			order_by="creation desc",
		)
		if open_invoice:
			invoice_row = open_invoice

	payment_method = (payment_method or "Bank Transfer").strip()
	allowed_methods = {"Bank Transfer", "Cash", "Card", "PayPal", "Other"}
	if payment_method not in allowed_methods:
		payment_method = "Bank Transfer"
	reference_no = (reference_no or "").strip()
	receipt = (receipt or "").strip()
	if not reference_no and not receipt:
		frappe.throw(_("Please enter the transfer reference or upload your payment receipt."))
	if receipt and not (receipt.startswith("/files/") or receipt.startswith("/private/")):
		frappe.throw(_("The uploaded receipt is not valid. Please upload it again."))

	months = _normalize_months(
		subscription,
		months or (invoice_row.months if invoice_row else None),
	)
	currency = (
		(invoice_row.currency if invoice_row else None)
		or subscription.currency
		or tenant_doc.currency
		or get_settings().default_currency
		or "USD"
	)
	plan = get_plan_by_identifier(subscription.plan)
	server_amount = _payment_amount(plan, subscription, months, currency)
	if not flt(server_amount):
		frappe.throw(_("The amount due could not be calculated. Please contact support."))

	period_start, period_end = _payment_period(subscription, months, invoice_row)
	user_notes = (notes or "").strip()

	if invoice_row:
		payment = frappe.get_doc("SaaS Payment", invoice_row.name)
		existing_notes = payment.notes or ""
		payment.update(
			{
				"amount": server_amount,
				"currency": currency,
				"months": months,
				"billing_cycle": "Yearly" if months == 12 else "Monthly",
				"period_start": period_start,
				"period_end": period_end,
				"status": "Pending Review",
				"payment_method": payment_method,
				"reference_no": reference_no,
				"receipt": receipt or payment.receipt,
				"notes": f"{existing_notes}\n{user_notes}".strip() if user_notes else existing_notes,
			}
		)
		payment.flags.ignore_permissions = True
		payment.save(ignore_permissions=True)
	else:
		payment = frappe.new_doc("SaaS Payment")
		payment.update(
			{
				"tenant": tenant_doc.name,
				"subscription": subscription.name,
				"plan": subscription.plan,
				"amount": server_amount,
				"currency": currency,
				"months": months,
				"billing_cycle": "Yearly" if months == 12 else "Monthly",
				"period_start": period_start,
				"period_end": period_end,
				"due_date": period_start,
				"status": "Pending Review",
				"is_invoice": 0,
				"payment_method": payment_method,
				"reference_no": reference_no,
				"notes": user_notes,
				"receipt": receipt or None,
			}
		)
		payment.flags.ignore_permissions = True
		payment.insert(ignore_permissions=True)

	if receipt:
		_attach_receipt(payment, receipt)

	subscription.payment_status = "Pending Review"
	subscription.flags.ignore_permissions = True
	subscription.save(ignore_permissions=True)
	frappe.db.commit()

	log_activity(
		tenant_doc.name,
		"Payment submitted",
		f"Payment {payment.name} for {server_amount} {currency} ({months} month(s))",
	)
	_notify_payment_submitted(payment, tenant_doc)
	return {
		"ok": True,
		"payment": payment.name,
		"amount": server_amount,
		"months": months,
		"period_start": str(period_start),
		"period_end": str(period_end),
		"message": _("Payment submitted. We will review it within one business day."),
	}


# ---------------------------------------------------------------------------
# Admin actions (Desk)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def approve_payment(payment: str):
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	doc = frappe.get_doc("SaaS Payment", payment)
	doc.approve()
	frappe.db.commit()
	return {"ok": True, "message": _("Payment approved and subscription extended.")}


@frappe.whitelist()
def reject_payment(payment: str, reason: str | None = None):
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	doc = frappe.get_doc("SaaS Payment", payment)
	doc.reject(reason)
	frappe.db.commit()
	return {"ok": True, "message": _("Payment rejected.")}


@frappe.whitelist()
def create_payment_invoice(payment: str):
	"""Create (or retry) the Sales Invoice for an approved payment."""
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	doc = frappe.get_doc("SaaS Payment", payment)
	if doc.sales_invoice and frappe.db.exists("Sales Invoice", doc.sales_invoice):
		return {"ok": True, "invoice": doc.sales_invoice, "message": _("Invoice already exists.")}
	invoice = doc.create_sales_invoice()
	if not invoice:
		frappe.throw(_("Could not create the invoice. Check the company and default accounts."))
	doc.db_set("sales_invoice", invoice.name, update_modified=False)
	frappe.db.commit()
	return {"ok": True, "invoice": invoice.name, "message": _("Invoice created.")}


@frappe.whitelist()
def download_payment_invoice(payment: str, lang: str | None = None):
	"""Render a downloadable PDF invoice for a SaaS Payment."""
	_require_login()
	if not frappe.db.exists("SaaS Payment", payment):
		frappe.throw(_("Invoice not found."))
	doc = frappe.get_doc("SaaS Payment", payment)
	tenant_doc = get_owned_tenant(doc.tenant)

	lang = "ar" if str(lang or "").lower().startswith("ar") else "en"
	context = _payment_invoice_context(doc, tenant_doc, lang)
	try:
		html = frappe.render_template("templates/print_formats/saas_payment_invoice.html", context)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"SaaS invoice template {doc.name}")
		frappe.throw(_("The invoice could not be generated. Please contact support."))

	try:
		from frappe.utils.pdf import get_pdf

		content = get_pdf(html)
		filename = f"{doc.name}.pdf"
		content_type = "application/pdf"
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"SaaS invoice PDF {doc.name}")
		content = html.encode("utf-8")
		filename = f"{doc.name}.html"
		content_type = "text/html"

	frappe.local.response.filename = filename
	frappe.local.response.filecontent = content
	frappe.local.response.content_type = content_type
	frappe.local.response.type = "download"


def _payment_invoice_context(doc, tenant_doc, lang: str = "en") -> dict:
	"""Build the template context for a SaaS Payment invoice."""
	frappe.local.lang = lang
	settings = get_settings()
	plan = get_plan_by_identifier(doc.plan)
	currency = (
		doc.currency
		or (tenant_doc.currency if tenant_doc else None)
		or settings.default_currency
		or "USD"
	)
	brand = (
		(settings.brand_name_ar or settings.brand_name)
		if lang == "ar"
		else (settings.brand_name or "Sahbix")
	)
	return {
		"doc": doc,
		"tenant": tenant_doc,
		"plan": plan,
		"settings": settings,
		"lang": lang,
		"dir": "rtl" if lang == "ar" else "ltr",
		"brand": brand,
		"support_email": settings.support_email,
		"support_phone": settings.support_phone,
		"website_domain": get_domain(),
		"currency": currency,
		"amount_display": format_money(doc.amount, currency),
		"status_label_text": status_label(doc.status, lang),
		"issue_date": formatdate(doc.creation, "dd MMM yyyy"),
		"due_date_display": formatdate(doc.due_date, "dd MMM yyyy") if doc.due_date else "—",
		"period_start_display": formatdate(doc.period_start, "dd MMM yyyy")
		if doc.period_start
		else "—",
		"period_end_display": formatdate(doc.period_end, "dd MMM yyyy") if doc.period_end else "—",
		"months_label": _month_label(cint(doc.months) or 1),
		"plan_name": plan.plan_name if plan else (doc.plan or "—"),
		"bank_details": settings.bank_details_ar if lang == "ar" else settings.bank_details,
		"payment_note": settings.payment_note_ar if lang == "ar" else settings.payment_note_en,
	}


@frappe.whitelist()
def provision_tenant(tenant: str):
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	provisioning.enqueue_provisioning(tenant)
	return {"ok": True, "message": _("Provisioning queued.")}


@frappe.whitelist()
def suspend_tenant(tenant: str, reason: str | None = None):
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	tenant_ops.suspend_tenant(tenant, reason)
	return {"ok": True, "message": _("Workspace suspended.")}


@frappe.whitelist()
def unsuspend_tenant(tenant: str):
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	tenant_ops.unsuspend_tenant(tenant)
	return {"ok": True, "message": _("Workspace reactivated.")}


@frappe.whitelist()
def sync_usage(tenant: str | None = None):
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if tenant:
		tenant_ops.sync_usage(tenant)
	else:
		tenant_ops.sync_all_tenants()
	return {"ok": True, "message": _("Usage synced.")}


@frappe.whitelist()
def extend_subscription(tenant: str, cycle: str = "Monthly"):
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	tenant_doc = frappe.get_doc("SaaS Tenant", tenant)
	subscription = get_tenant_subscription(tenant_doc)
	if not subscription:
		frappe.throw(_("This workspace has no subscription."))
	subscription.extend(cycle, note=_("Manual extension by administrator"))
	frappe.db.commit()
	return {"ok": True, "message": _("Subscription extended.")}


@frappe.whitelist()
def create_sales_invoice(payment: str):
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	doc = frappe.get_doc("SaaS Payment", payment)
	invoice = doc.create_sales_invoice()
	frappe.db.commit()
	return {"ok": True, "invoice": invoice.name if invoice else None}


@frappe.whitelist()
def request_ssl(tenant: str):
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	provisioning.enqueue_ssl(tenant)
	return {"ok": True, "message": _("SSL request queued.")}


@frappe.whitelist()
def delete_tenant(tenant: str, confirm: str | None = None):
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	tenant_ops.delete_tenant(tenant, confirm)
	return {"ok": True, "message": _("Workspace deleted.")}


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_admin_dashboard():
	if not is_manager():
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	settings = get_settings()
	base_currency = settings.default_currency or "USD"

	total_tenants = frappe.db.count("SaaS Tenant")
	active_tenants = frappe.db.count("SaaS Tenant", {"status": "Active"})
	trial_tenants = frappe.db.count("SaaS Tenant", {"status": "Trial"})
	past_due = frappe.db.count("SaaS Tenant", {"status": "Past Due"})
	suspended = frappe.db.count("SaaS Tenant", {"status": "Suspended"})
	failed = frappe.db.count("SaaS Tenant", {"status": "Failed"})
	pending_payments = frappe.db.count("SaaS Payment", {"status": "Pending Review"})

	mrr = 0.0
	active_subs = frappe.get_all(
		"SaaS Subscription",
		filters={"status": ["in", ["Active", "Trial", "Past Due"]]},
		fields=["amount", "currency", "billing_cycle"],
	)
	for row in active_subs:
		amount = flt(row.amount)
		if (row.billing_cycle or "Monthly") == "Yearly":
			amount = amount / 12.0
		mrr += convert_amount(amount, row.currency, base_currency)

	paid_this_month = 0.0
	paid_rows = frappe.get_all(
		"SaaS Payment",
		filters={"status": "Paid", "paid_on": [">=", today()[:8] + "01"]},
		fields=["amount", "currency"],
	)
	for row in paid_rows:
		paid_this_month += convert_amount(flt(row.amount), row.currency, base_currency)

	# Signups per month for the last 12 months.
	signups = frappe.db.sql(
		"""
		select date_format(creation, '%Y-%m') as month, count(*) as total
		from `tabSaaS Tenant`
		where creation >= date_sub(curdate(), interval 12 month)
		group by date_format(creation, '%Y-%m')
		order by month asc
		""",
		as_dict=True,
	)

	# Revenue per month for the last 12 months.
	revenue_rows = frappe.get_all(
		"SaaS Payment",
		filters={"status": "Paid", "paid_on": [">=", add_days(today(), -365)]},
		fields=["amount", "currency", "paid_on"],
	)
	revenue_map = {}
	for row in revenue_rows:
		if not row.paid_on:
			continue
		month = str(row.paid_on)[:7]
		revenue_map[month] = revenue_map.get(month, 0.0) + convert_amount(
			flt(row.amount), row.currency, base_currency
		)
	revenue = [{"month": key, "total": round(value, 2)} for key, value in sorted(revenue_map.items())]

	by_plan = frappe.db.sql(
		"""
		select coalesce(plan, 'No plan') as plan, count(*) as total
		from `tabSaaS Tenant`
		where status not in ('Cancelled')
		group by plan
		order by total desc
		""",
		as_dict=True,
	)

	recent_tenants = frappe.get_all(
		"SaaS Tenant",
		fields=["name", "tenant_name", "subdomain", "status", "plan", "creation", "admin_email", "users_count", "storage_used_mb"],
		order_by="creation desc",
		limit=10,
	)

	pending = frappe.get_all(
		"SaaS Payment",
		filters={"status": "Pending Review"},
		fields=["name", "tenant", "tenant_name", "amount", "currency", "creation", "reference_no", "receipt"],
		order_by="creation desc",
		limit=10,
	)

	expiring = frappe.get_all(
		"SaaS Subscription",
		filters={
			"status": ["in", ["Trial", "Active", "Past Due"]],
			"end_date": ["between", [today(), add_days(today(), 14)]],
		},
		fields=["name", "tenant", "tenant_name", "plan", "status", "end_date", "amount", "currency"],
		order_by="end_date asc",
		limit=10,
	)

	return {
		"currency": base_currency,
		"kpis": {
			"total_tenants": total_tenants,
			"active_tenants": active_tenants,
			"trial_tenants": trial_tenants,
			"past_due": past_due,
			"suspended": suspended,
			"failed": failed,
			"pending_payments": pending_payments,
			"mrr": round(mrr, 2),
			"arr": round(mrr * 12, 2),
			"paid_this_month": round(paid_this_month, 2),
		},
		"signups": signups,
		"revenue": revenue,
		"by_plan": by_plan,
		"recent_tenants": recent_tenants,
		"pending_payments_list": pending,
		"expiring": expiring,
		"website_url": get_central_url(),
	}


# ---------------------------------------------------------------------------
# Misc endpoints
# ---------------------------------------------------------------------------
@frappe.whitelist()
def has_app_permission():
	"""Used by the apps screen to decide whether to show this app."""
	return is_manager()


@frappe.whitelist(allow_guest=True)
def get_public_settings():
	settings = get_settings()
	return {
		"brand_name": settings.brand_name,
		"brand_name_ar": settings.brand_name_ar,
		"tagline_en": settings.tagline_en,
		"tagline_ar": settings.tagline_ar,
		"support_email": settings.support_email,
		"support_phone": settings.support_phone,
		"website_domain": get_domain(),
		"trial_days": cint(settings.trial_days) or 30,
		"currencies": get_enabled_currencies(),
		"default_currency": settings.default_currency or "USD",
	}


@frappe.whitelist()
def get_current_user_context():
	if frappe.session.user == "Guest":
		return {"logged_in": False}
	user = frappe.get_doc("User", frappe.session.user)
	tenant = get_tenant_for_user()
	return {
		"logged_in": True,
		"user": {
			"name": user.name,
			"full_name": user.full_name,
			"email": user.email,
			"user_image": user.user_image,
			"language": user.language,
		},
		"tenant": tenant.name if tenant else None,
		"is_manager": is_manager(),
	}

