# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class SaaSSettings(Document):
	def validate(self):
		self.website_domain = (self.website_domain or "").strip().lower()
		self.website_domain = (
			self.website_domain.replace("https://", "").replace("http://", "").strip("/")
		)
		self.site_scheme = (self.site_scheme or "http").lower()
		if not self.website_domain:
			frappe.throw(_("Website Domain is required."))
		if not self.template_site:
			self.template_site = "saas-default.com"
		if not self.sites_path:
			self.sites_path = frappe.utils.get_bench_path() + "/sites"
		if not self.bench_path:
			self.bench_path = frappe.utils.get_bench_path()
		if not self.default_currency:
			self.default_currency = "USD"

	def on_update(self):
		try:
			from saaserpyemen.setup import sync_google_login

			sync_google_login()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "SaaS Google login sync")
		frappe.clear_cache()
