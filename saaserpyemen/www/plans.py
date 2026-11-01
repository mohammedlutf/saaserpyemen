from __future__ import annotations

import frappe

from saaserpyemen.utils import get_tenant_for_user, get_tenant_subscription, user_has_workspaces
from saaserpyemen.website import base_context, plans_context


def _build_comparison(plans: list[dict]) -> list[dict]:
	"""Build a stable feature comparison matrix for the plans table."""
	rows: list[dict] = []
	index: dict[str, int] = {}
	for plan_index, plan in enumerate(plans):
		for feature in plan.get("features") or []:
			key = (feature.get("en") or "").strip().lower()
			if not key:
				continue
			if key not in index:
				index[key] = len(rows)
				rows.append(
					{
						"en": feature.get("en"),
						"ar": feature.get("ar") or feature.get("en"),
						"included": [False] * len(plans),
					}
				)
			rows[index[key]]["included"][plan_index] = bool(feature.get("included"))
	return rows


def get_context(context):
	base_context(context)
	currency = frappe.local.request.args.get("currency")
	cycle = frappe.local.request.args.get("cycle", "Monthly")
	cycle = "Yearly" if str(cycle).lower().startswith("y") else "Monthly"
	plans_context(context, currency)
	context.cycle = cycle
	context.compare_features = _build_comparison(context.plans)
	context.tenant = None
	context.change_mode = frappe.local.request.args.get("change") in ("1", "true", "yes")
	context.new_mode = frappe.local.request.args.get("new") in ("1", "true", "yes")
	if context.new_mode:
		context.change_mode = False
	context.selected_tenant = None if context.new_mode else frappe.local.request.args.get("tenant")
	context.trial_available = True
	if context.logged_in:
		context.tenant = get_tenant_for_user()
		context.subscription = get_tenant_subscription(context.tenant) if context.tenant else None
		context.trial_available = not user_has_workspaces()
	context.title = f"Plans & pricing — {context.brand_name}"
	context.metatags = {
		"description": "Simple, transparent ERP pricing. Choose the plan that fits your team."
	}
