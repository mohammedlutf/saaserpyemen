from __future__ import annotations

from frappe.utils import nowdate

from saaserpyemen.website import base_context


def get_context(context):
	base_context(context)
	context.updated_on = nowdate()
	context.title = f"Terms of Service — {context.brand_name}"
	context.metatags = {
		"description": f"The terms that govern your use of the {context.brand_name} cloud ERP platform.",
	}
