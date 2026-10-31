from __future__ import annotations

from frappe.utils import nowdate

from saaserpyemen.website import base_context


def get_context(context):
	base_context(context)
	context.updated_on = nowdate()
	context.title = "Privacy Policy — Shopzad"
	context.metatags = {
		"description": "How Shopzad collects, uses and protects your data.",
	}
