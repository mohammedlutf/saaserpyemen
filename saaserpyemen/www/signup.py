from __future__ import annotations

import frappe

from saaserpyemen.utils import (
	format_money,
	get_countries,
	get_plan_by_identifier,
	get_plan_price,
)
from saaserpyemen.website import base_context, plans_context


def get_context(context):
	base_context(context)
	if frappe.session.user != "Guest":
		frappe.local.flags.redirect_location = "/dashboard"
		raise frappe.Redirect

	plans_context(context)
	context.countries = get_countries()
	context.selected_plan = frappe.local.request.args.get("plan") or ""
	context.selected_cycle = (
		"Yearly" if str(frappe.local.request.args.get("cycle", "")).lower().startswith("y") else "Monthly"
	)
	context.selected_currency = (
		frappe.local.request.args.get("currency") or context.default_currency
	).upper()
	if context.selected_currency not in {row["name"] for row in context.currencies}:
		context.selected_currency = context.default_currency
	context.plan_doc = get_plan_by_identifier(context.selected_plan) if context.selected_plan else None
	context.plan_price = None
	context.plan_price_label = ""
	if context.plan_doc:
		context.plan_price = get_plan_price(
			context.plan_doc, context.selected_currency, context.selected_cycle
		)
		context.plan_price_label = format_money(context.plan_price, context.selected_currency)
	from frappe import _

	context.title = f"{_('Create your account')} — {context.brand_name}"
	context.metatags = {"description": _("Create your free {0} account and start a 14-day trial.").format(context.brand_name)}
