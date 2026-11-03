from __future__ import annotations

from urllib.parse import urlencode

import frappe

from saaserpyemen import api
from saaserpyemen.i18n import localized_url
from saaserpyemen.utils import get_tenant_for_user, get_tenant_subscription, is_manager
from saaserpyemen.website import base_context, require_login


def _request_arg(name: str) -> str:
	request = getattr(frappe.local, "request", None)
	args = getattr(request, "args", None) if request else None
	if not args:
		return ""
	value = args.get(name)
	if value is None:
		return ""
	return str(value).strip()


def _redirect_to_dashboard(tenant: str, notice: str | None = None):
	query = {"tenant": tenant, "tab": "payments"}
	if notice:
		query["notice"] = notice
	frappe.local.flags.redirect_location = localized_url(f"/dashboard?{urlencode(query)}")
	raise frappe.Redirect


def _check_requested_invoice(tenant, requested: str):
	"""Send the visitor back to the dashboard when the invoice is not payable."""
	if not requested:
		return

	row = frappe.db.get_value(
		"SaaS Payment",
		requested,
		["name", "tenant", "status"],
		as_dict=True,
	)
	if not row or row.tenant != tenant.name:
		_redirect_to_dashboard(tenant.name, "invoice_not_found")

	if row.status not in ("Unpaid", "Pending Review"):
		notice = "invoice_paid" if row.status == "Paid" else "invoice_closed"
		_redirect_to_dashboard(tenant.name, notice)


def get_context(context):
	base_context(context)
	require_login(context)

	tenant_arg = _request_arg("tenant")
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
		frappe.local.flags.redirect_location = localized_url("/plans")
		raise frappe.Redirect

	# Never render the payment form for an invoice that is already settled.
	_check_requested_invoice(tenant, _request_arg("invoice"))

	if not get_tenant_subscription(tenant):
		frappe.local.flags.redirect_location = localized_url("/plans")
		raise frappe.Redirect

	context.tenant = tenant
	try:
		context.data = api.get_payment_context(tenant.name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS payment context")
		_redirect_to_dashboard(tenant.name, "payment_unavailable")

	if not context.data:
		_redirect_to_dashboard(tenant.name, "payment_unavailable")

	from frappe import _

	brand = context.brand_name_ar if context.lang == "ar" else context.brand_name
	context.title = f"{_('Manual payment')} — {brand}"
	context.metatags = {
		"description": _("Complete your {0} subscription payment by bank transfer.").format(brand),
		"robots": "noindex, nofollow",
	}
