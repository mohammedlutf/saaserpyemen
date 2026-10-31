# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt

from __future__ import annotations

import os

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from saaserpyemen.utils import (
	get_full_site_name,
	get_plan_by_identifier,
	get_plan_limits,
	normalize_subdomain,
	validate_subdomain,
)


class SaaSTenant(Document):
	def validate(self):
		if self.subdomain:
			self.subdomain = normalize_subdomain(self.subdomain)
			validate_subdomain(self.subdomain, check_availability=self.is_new())

		if not self.subdomain:
			frappe.throw(_("Subdomain is required."))

		if not self.site_name:
			self.site_name = get_full_site_name(self.subdomain)
		self.site_name = self.site_name.strip().lower()

		if not self.owner_user:
			self.owner_user = frappe.session.user
		if not self.admin_email and self.owner_user and frappe.db.exists("User", self.owner_user):
			self.admin_email = frappe.db.get_value("User", self.owner_user, "email")
		if not self.admin_full_name and self.owner_user and frappe.db.exists("User", self.owner_user):
			self.admin_full_name = frappe.db.get_value("User", self.owner_user, "full_name")
		if not self.currency:
			self.currency = (
				frappe.db.get_single_value("SaaS Settings", "default_currency") or "USD"
			)

		if not self.status:
			self.status = "Draft"

		self._validate_plan_limits()

	def _validate_plan_limits(self):
		plan = get_plan_by_identifier(self.plan) if self.plan else None
		if not plan:
			return
		limits = get_plan_limits(plan)
		for used_field, limit_field, label in (
			("users_count", "max_users", _("users")),
			("branches_count", "max_branches", _("branches")),
			("companies_count", "max_companies", _("companies")),
		):
			limit = limits.get(limit_field) or 0
			used = cint(self.get(used_field))
			if limit and used > limit:
				frappe.throw(
					_("This workspace uses {0} {1}, which exceeds the {2} plan limit of {3}.").format(
						used, label, plan.plan_name, limit
					)
				)

	def on_update(self):
		if self.has_value_changed("plan") or self.has_value_changed("suspended"):
			if self.site_name and os.path.isdir(
				os.path.join(frappe.utils.get_bench_path(), "sites", self.site_name)
			):
				try:
					from saaserpyemen import tenant_ops

					tenant_ops.push_limits(self)
				except Exception:
					frappe.log_error(frappe.get_traceback(), "SaaS push limits")

	def on_trash(self):
		if self.flags.force_delete:
			return
		site_path = os.path.join(frappe.utils.get_bench_path(), "sites", self.site_name or "")
		if self.site_name and os.path.isdir(site_path):
			frappe.throw(
				_(
					"This workspace still has a live site. Use the “Delete workspace” action in the SaaS Control Center instead."
				),
				title=_("Site exists"),
			)
