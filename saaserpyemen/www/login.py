from __future__ import annotations

import frappe
from frappe.utils.oauth import get_oauth2_authorize_url, get_oauth_keys
from frappe.utils.password import get_decrypted_password

from saaserpyemen.utils import sanitize_redirect
from saaserpyemen.website import base_context
from saaserpyemen.i18n import saas_url

def get_context(context):
	base_context(context)
	if frappe.session.user != "Guest":
		frappe.local.flags.redirect_location = saas_url('/dashboard')
		raise frappe.Redirect

	context.redirect_to = sanitize_redirect(
		frappe.local.request.args.get("redirect"), saas_url('/dashboard')
	)
	context.provider_logins = []
	if frappe.db.exists("DocType", "Social Login Key"):
		providers = frappe.get_all(
			"Social Login Key",
			filters={"enable_social_login": 1},
			fields=["name", "provider_name", "client_id", "base_url"],
			order_by="name",
		)
		for provider in providers:
			secret = get_decrypted_password(
				"Social Login Key", provider.name, "client_secret", raise_exception=False
			)
			if not secret or not get_oauth_keys(provider.name):
				continue
			try:
				url = get_oauth2_authorize_url(provider.name, context.redirect_to)
			except Exception:
				continue
			context.provider_logins.append(
				{
					"name": provider.name,
					"provider_name": provider.provider_name,
					"auth_url": url,
					"is_google": (provider.provider_name or "").lower() == "google",
				}
			)

	context.disable_signup = frappe.utils.cint(
		frappe.db.get_single_value("Website Settings", "disable_signup")
	)
	from frappe import _

	context.title = f"{_('Sign in')} — {context.brand_name}"
	context.metatags = {"description": _("Sign in to your {0} workspace.").format(context.brand_name)}
