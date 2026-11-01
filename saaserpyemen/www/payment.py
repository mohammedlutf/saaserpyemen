from __future__ import annotations

import frappe

from saaserpyemen import api
from saaserpyemen.utils import get_tenant_for_user, is_manager
from saaserpyemen.website import base_context, require_login


def get_context(context):
	base_context(context)
	require_login(context)

	tenant_arg = frappe.local.request.args.get("tenant")
	tenant = None
	if tenant_arg:
		if frappe.db.exists("SaaS Tenant", tenant_arg):
			tenant = frappe.get_doc("SaaS Tenant", tenant_arg)
			if tenant.owner_user != frappe.session.user and not is_manager():
				frappe.throw(
					frappe._("You do not have permission to view this workspace."),
					frappe.PermissionError,
				)
	else:
		tenant = get_tenant_for_user()

	if not tenant:
		frappe.local.flags.redirect_location = "/plans"
		raise frappe.Redirect

	context.tenant = tenant
	context.data = None
	try:
		context.data = api.get_payment_context(tenant.name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS payment context")

	context.title = f"Manual payment — {context.brand_name}"
	context.metatags = {
		"description": f"Complete your {context.brand_name} subscription payment by bank transfer.",
		"robots": "noindex, nofollow",
	}
