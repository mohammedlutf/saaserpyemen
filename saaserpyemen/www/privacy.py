from __future__ import annotations

from frappe.utils import nowdate

from saaserpyemen.website import base_context


def get_context(context):
	from frappe import _

	base_context(context)
	context.updated_on = nowdate()
	context.title = f"{_('Privacy Policy')} — {context.brand_name}"
	context.metatags = {
		"description": _("How {0} collects, uses and protects your data.").format(context.brand_name),
	}
