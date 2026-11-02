from __future__ import annotations

import frappe
from frappe import _

from saaserpyemen.website import base_context

no_cache = 1


def get_context(context):
	base_context(context)
	context.no_breadcrumbs = True

	args = frappe.local.request.args if frappe.local.request else {}
	context.reset_key = (args.get("key") or "").strip()
	context.password_expired = args.get("password_expired")
	context.is_guest = frappe.session.user == "Guest"
	# Guests without a reset key cannot set a password (no session, no link).
	context.invalid_link = bool(not context.reset_key and context.is_guest)

	brand = context.brand_name_ar if context.lang == "ar" else context.brand_name
	context.title = f"{_('Set a new password')} — {brand}"
	context.metatags = {
		"description": _("Choose a new password for your {0} workspace.").format(brand),
		"robots": "noindex, nofollow",
	}
