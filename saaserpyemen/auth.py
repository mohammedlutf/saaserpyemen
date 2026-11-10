# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.utils import cint

from saaserpyemen.utils import is_central_site, log_activity


def _social_provider(doc) -> str | None:
	"""Return the external provider used to sign up, if any.

	``User.validate()`` always adds a ``frappe`` social login for password
	logins, so that entry cannot be used to tell social signups apart.
	"""
	for row in doc.get("social_logins") or []:
		provider = (row.get("provider") or "").strip().lower()
		if provider and provider != "frappe":
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
		# Select fields default to their first option ("Email"), so treat the
		# default as "not set" and let the social provider win.
		if (doc.get("saas_signup_source") or "").strip() in ("", "Email"):
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
			current_roles = {row.role for row in (doc.get("roles") or [])}
			# Avoid an extra save inside after_insert (it can desync the
			# in-memory modified timestamp for callers that save afterwards).
			if "SaaS Customer" not in current_roles:
				doc.add_roles("SaaS Customer")

		log_activity(
			None,
			"Signup",
			f"New account created via {source}: {doc.email}",
			user=doc.name,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS User After Insert")


# ---------------------------------------------------------------------------
# Webshop compatibility
# ---------------------------------------------------------------------------
_webshop_patched_sites: set[str] = set()


def apply_webshop_saas_guard():
	"""Stop the webshop cart from treating SaaS users as store customers.

	On the central site the webshop hooks run on every login. For a user whose
	email already exists as an ERPNext Contact linked to a Customer (for
	example a person who once bought something), ``get_party`` saves that
	Customer and ERPNext then re-saves the Contact, which can raise
	``TimestampMismatchError`` during the OAuth callback. SaaS users are not
	store customers, so skip the cart path for them while leaving the webshop
	untouched for real customers.
	"""
	site = getattr(frappe.local, "site", None)
	if not site or site in _webshop_patched_sites:
		return

	if not is_central_site():
		return

	try:
		from webshop.webshop.shopping_cart import utils as cart_utils
	except Exception:
		return

	original = getattr(cart_utils, "is_customer", None)
	if not original or getattr(original, "_saas_guard", False):
		_webshop_patched_sites.add(site)
		return

	_webshop_patched_sites.add(site)

	def is_customer():
		try:
			if (
				is_central_site()
				and frappe.session.user
				and frappe.session.user != "Guest"
				and "SaaS Customer" in frappe.get_roles()
			):
				return False
		except Exception:
			pass
		return original()

	is_customer._saas_guard = True
	cart_utils.is_customer = is_customer
