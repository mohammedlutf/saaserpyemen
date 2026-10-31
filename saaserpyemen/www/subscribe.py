from __future__ import annotations

import frappe

from saaserpyemen.utils import (
	get_countries,
	get_plan_by_identifier,
	get_tenant_for_user,
	get_tenant_subscription,
)
from saaserpyemen.website import base_context, plans_context, require_login


def get_context(context):
	base_context(context)
	require_login(context)

	args = frappe.local.request.args
	plans_context(context, args.get("currency"))
	context.countries = get_countries()

	tenant = get_tenant_for_user()
	tenant_arg = args.get("tenant")
	context.tenant = tenant if (tenant and (not tenant_arg or tenant_arg == tenant.name)) else None
	context.is_change = bool(context.tenant)
	context.existing_tenant = context.tenant.name if context.tenant else ""

	selected = args.get("plan") or (context.tenant.plan if context.tenant else "")
	plan = get_plan_by_identifier(selected)
	if not plan and context.plans:
		plan = get_plan_by_identifier(context.plans[0]["name"])
	if not plan:
		frappe.local.flags.redirect_location = "/plans"
		raise frappe.Redirect

	context.plan = plan
	context.selected_plan = plan.name
	context.cycle = "Yearly" if str(args.get("cycle", "")).lower().startswith("y") else "Monthly"
	requested_currency = args.get("currency")
	if not requested_currency and context.tenant:
		requested_currency = context.tenant.currency
	context.currency = (requested_currency or context.default_currency or "USD").upper()
	if context.currency not in {row["name"] for row in context.currencies}:
		context.currency = context.default_currency
	context.subscription = get_tenant_subscription(context.tenant) if context.tenant else None

	from saaserpyemen.utils import get_plan_prices

	context.prices = get_plan_prices(plan, context.currency)
	context.currency_prices = {
		row["name"]: get_plan_prices(plan, row["name"]) for row in context.currencies
	}

	user = frappe.get_doc("User", frappe.session.user)
	context.user = user
	context.prefill = {
		"company_name": context.tenant.tenant_name if context.tenant else (user.get("saas_company_name") or ""),
		"phone": context.tenant.phone if context.tenant else (user.get("saas_phone") or ""),
		"country": context.tenant.country if context.tenant else (user.get("saas_country") or ""),
		"email": user.email,
		"full_name": user.full_name,
	}
	context.suggested_subdomain = ""
	if not context.is_change:
		import re

		base = (user.get("saas_company_name") or user.full_name or "workspace").lower()
		context.suggested_subdomain = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:24] or "workspace"

	context.title = ("Change plan" if context.is_change else "Choose your workspace") + " — Shopzad"
	context.metatags = {"description": "Choose your plan and subdomain to create your Shopzad workspace."}
