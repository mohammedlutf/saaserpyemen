# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.utils import cint

from saaserpyemen.utils import is_central_site, log_activity


def _social_provider(doc) -> str | None:
	for row in doc.get("social_logins") or []:
		provider = (row.get("provider") or "").strip().lower()
		if provider:
			return provider
	return None


def on_user_after_insert(doc, method=None):
	"""Record signup metadata for users created through a social provider.

	Frappe's OAuth flow creates the User (and its ``social_logins`` child rows)
	before the session is established, so ``after_insert`` is the earliest point
	where we can tell a Google signup apart from an email signup.
	"""
	try:
		if not is_central_site():
			return

		provider = _social_provider(doc)
		if not provider:
			return

		source = "Google" if provider == "google" else provider.title()
		updates = {}
		if not doc.get("saas_signup_source"):
			updates["saas_signup_source"] = source
		if frappe.db.has_column("User", "saas_signup_verified") and not cint(
			doc.get("saas_signup_verified")
		):
			updates["saas_signup_verified"] = 1

		if updates:
			# Keep the in-memory document in sync: add_roles() saves the document
			# and would otherwise write the old (empty) values back to the database.
			for field, value in updates.items():
				doc.set(field, value)
			frappe.db.set_value("User", doc.name, updates, update_modified=False)

		if frappe.db.exists("Role", "SaaS Customer"):
			doc.add_roles("SaaS Customer")

		log_activity(
			None,
			"Signup",
			f"New account created via {source}: {doc.email}",
			user=doc.name,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS User After Insert")
