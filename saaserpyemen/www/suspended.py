from __future__ import annotations

import frappe

from saaserpyemen.utils import get_tenant_for_user
from saaserpyemen.website import base_context


def get_context(context):
	base_context(context)
	site = (frappe.local.request.args.get("site") or "").strip().lower()
	context.site = site
	context.suspended_tenant = None
	if site:
		name = frappe.db.get_value("SaaS Tenant", {"subdomain": site}, "name")
		if name:
			context.suspended_tenant = frappe.db.get_value(
				"SaaS Tenant",
				name,
				["tenant_name", "subdomain", "status", "admin_email"],
				as_dict=True,
			)
	context.tenant = get_tenant_for_user() if frappe.session.user != "Guest" else None
	context.title = f"Workspace suspended — {context.brand_name}"
	context.metatags = {
		"description": f"This {context.brand_name} workspace is temporarily suspended.",
		"robots": "noindex, nofollow",
	}
