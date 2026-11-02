from __future__ import annotations

from frappe.utils import nowdate

from saaserpyemen.website import base_context


def get_context(context):
	from frappe import _

	base_context(context)
	context.updated_on = nowdate()
	context.title = f"{_('Terms of Service')} — {context.brand_name}"
	context.metatags = {
		"description": _("The terms that govern your use of the {0} cloud ERP platform.").format(context.brand_name),
	}
