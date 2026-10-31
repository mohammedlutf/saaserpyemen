from __future__ import annotations

from frappe.utils import nowdate

from saaserpyemen.website import base_context


def get_context(context):
	base_context(context)
	context.updated_on = nowdate()
	context.title = "Terms of Service — Shopzad"
	context.metatags = {
		"description": "The terms that govern your use of the Shopzad cloud ERP platform.",
	}
