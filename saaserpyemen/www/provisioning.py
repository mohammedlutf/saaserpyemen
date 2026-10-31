from __future__ import annotations

import frappe

from saaserpyemen.utils import get_site_url, get_tenant_for_user, is_manager
from saaserpyemen.website import base_context, require_login


def get_context(context):
	base_context(context)
	require_login(context)
	tenant_name = frappe.local.request.args.get("tenant")
	tenant = get_tenant_for_user() if not tenant_name else frappe.get_doc("SaaS Tenant", tenant_name)
	if not tenant:
		frappe.local.flags.redirect_location = "/plans"
		raise frappe.Redirect
	if tenant.owner_user != frappe.session.user and not is_manager():
		frappe.throw(frappe._("You do not have permission to view this workspace."), frappe.PermissionError)

	context.tenant = tenant
	context.site_url = get_site_url(tenant.subdomain)
	context.completed = tenant.provisioning_status == "Completed"
	context.failed = tenant.provisioning_status == "Failed"
	context.title = "Setting up your workspace — Shopzad"
	context.metatags = {"description": "Your Shopzad workspace is being provisioned."}
