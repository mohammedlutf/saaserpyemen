from __future__ import annotations

from frappe.utils import nowdate

from saaserpyemen.website import base_context


def get_context(context):
	base_context(context)
	context.updated_on = nowdate()
	context.title = f"Privacy Policy — {context.brand_name}"
	context.metatags = {
		"description": f"How {context.brand_name} collects, uses and protects your data.",
	}
