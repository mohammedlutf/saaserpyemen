# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt
"""Shared context helpers for the public website and customer portal."""

from __future__ import annotations

from urllib.parse import quote

import frappe
from frappe.utils import cint, nowdate

from saaserpyemen.utils import (
	get_domain,
	get_enabled_currencies,
	get_plan_by_identifier,
	get_plan_limits,
	get_public_plans,
	get_settings,
	get_site_url,
	get_tenant_for_user,
	get_tenant_subscription,
	is_manager,
)


def get_language() -> str:
	user = frappe.session.user
	lang = None
	if user and user != "Guest":
		lang = frappe.db.get_value("User", user, "language")
	lang = lang or frappe.local.lang or "en"
	return "ar" if str(lang).lower().startswith("ar") else "en"


def base_context(context) -> None:
	settings = get_settings()
	user = frappe.session.user
	context.no_cache = 1
	context.body_class = "saas-site"
	context.settings = settings
	context.lang = get_language()
	context.domain = get_domain()
	context.default_currency = settings.default_currency or "USD"
	context.currencies = get_enabled_currencies()
	context.is_manager = is_manager()
	context.logged_in = user != "Guest"
	context.year = nowdate()[:4]
	context.brand_name = settings.brand_name or "Shopzad"
	context.brand_name_ar = settings.brand_name_ar or "شوب زاد"
	context.support_email = settings.support_email
	context.support_phone = settings.support_phone
	try:
		context.csrf_token = frappe.sessions.get_csrf_token()
	except Exception:
		context.csrf_token = ""


def current_path() -> str:
	try:
		return frappe.local.request.full_path or frappe.local.request.path or "/"
	except Exception:
		return "/"


def require_login(context, redirect: str | None = None) -> None:
	if frappe.session.user != "Guest":
		return
	target = redirect or current_path()
	frappe.local.flags.redirect_location = "/signin?redirect=" + quote(target, safe="")
	raise frappe.Redirect


def tenant_context(context, tenant: str | None = None) -> None:
	"""Populate the current tenant, plan, subscription and usage."""
	require_login(context)
	tenant_doc = get_tenant_for_user() if not tenant else frappe.get_doc("SaaS Tenant", tenant)
	if not tenant_doc:
		context.tenant = None
		context.subscription = None
		context.plan = None
		context.usage = None
		return

	if tenant_doc.owner_user != frappe.session.user and not is_manager():
		frappe.throw(frappe._("You do not have permission to view this workspace."), frappe.PermissionError)

	subscription = get_tenant_subscription(tenant_doc)
	plan = get_plan_by_identifier(tenant_doc.plan) if tenant_doc.plan else None
	limits = get_plan_limits(plan) if plan else {}
	context.tenant = tenant_doc
	context.subscription = subscription
	context.plan = plan
	context.plan_limits = limits
	context.site_url = get_site_url(tenant_doc.subdomain)
	context.usage = {
		"users": {
			"used": cint(tenant_doc.users_count),
			"limit": limits.get("max_users", 0),
			"percent": min(100, round(cint(tenant_doc.users_count) / limits["max_users"] * 100))
			if limits.get("max_users")
			else 0,
		},
		"branches": {
			"used": cint(tenant_doc.branches_count),
			"limit": limits.get("max_branches", 0),
			"percent": min(100, round(cint(tenant_doc.branches_count) / limits["max_branches"] * 100))
			if limits.get("max_branches")
			else 0,
		},
		"companies": {
			"used": cint(tenant_doc.companies_count),
			"limit": limits.get("max_companies", 0),
			"percent": min(100, round(cint(tenant_doc.companies_count) / limits["max_companies"] * 100))
			if limits.get("max_companies")
			else 0,
		},
		"storage": {
			"used_mb": tenant_doc.storage_used_mb or 0,
			"limit_gb": limits.get("storage_gb", 0),
			"percent": (
				min(100, round((tenant_doc.storage_used_mb or 0) / (limits["storage_gb"] * 1024) * 100))
				if limits.get("storage_gb")
				else 0
			),
		},
	}


def plans_context(context, currency: str | None = None) -> None:
	settings = get_settings()
	currency = (currency or settings.default_currency or "USD").upper()
	allowed = {row["name"] for row in context.currencies}
	if currency not in allowed:
		currency = (
			settings.default_currency
			if settings.default_currency in allowed
			else next(iter(sorted(allowed)), "USD")
		)
	context.plans = get_public_plans(currency)
	context.currency = currency
