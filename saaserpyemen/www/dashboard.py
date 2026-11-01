from __future__ import annotations

import frappe

from saaserpyemen import api
from saaserpyemen.utils import (
	get_countries,
	get_tenant_for_user,
	get_user_tenants,
	is_manager,
	user_has_workspaces,
)
from saaserpyemen.website import base_context, require_login

TABS = ("overview", "usage", "billing", "payments", "credentials", "profile")


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

	context.active_tab = frappe.local.request.args.get("tab") or "overview"
	if context.active_tab not in TABS:
		context.active_tab = "overview"
	context.tenant = tenant
	context.workspaces = get_user_tenants()
	context.trial_used = user_has_workspaces()
	context.countries = get_countries()
	context.account_user = frappe.get_doc("User", frappe.session.user)
	context.data = None
	context.payment = None

	if tenant:
		try:
			context.data = api.get_dashboard(tenant.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "SaaS dashboard context")
			context.data = None

	context.title = "My workspace — Shopzad"
	context.metatags = {
		"description": "Manage your Shopzad workspace, plan, usage, payments and credentials.",
		"robots": "noindex, nofollow",
	}
