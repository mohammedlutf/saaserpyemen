# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class SaaSPlan(Document):
	def validate(self):
		self.slug = (self.slug or "").strip().lower()
		if not self.slug:
			self.slug = (
				frappe.scrub(self.plan_name or "").replace("_", "-").strip("-")
				or frappe.generate_hash(length=8)
			)
		self.slug = frappe.scrub(self.slug).replace("_", "-")

		if not self.currency:
			self.currency = frappe.db.get_single_value("SaaS Settings", "default_currency") or "USD"
		if not frappe.db.exists("Currency", self.currency):
			frappe.throw(_("Currency {0} does not exist.").format(self.currency))

		if flt(self.monthly_price) < 0 or flt(self.yearly_price) < 0:
			frappe.throw(_("Prices cannot be negative."))

		if flt(self.monthly_price) and flt(self.yearly_price):
			self.yearly_discount_percent = max(
				0, round((1 - (flt(self.yearly_price) / (flt(self.monthly_price) * 12))) * 100)
			)
		else:
			self.yearly_discount_percent = 0

		if not cint(self.trial_days):
			self.trial_days = cint(
				frappe.db.get_single_value("SaaS Settings", "trial_days")
			) or 30

		self._validate_slug()
		self._validate_prices()

	def _validate_slug(self):
		duplicate = frappe.db.get_value(
			"SaaS Plan", {"slug": self.slug, "name": ["!=", self.name or ""]}, "name"
		)
		if duplicate:
			frappe.throw(_("Another plan already uses the slug {0}.").format(self.slug))

	def _validate_prices(self):
		seen = set()
		for row in self.get("prices") or []:
			if not row.currency:
				continue
			if row.currency in seen:
				frappe.throw(_("Duplicate price row for currency {0}.").format(row.currency))
			seen.add(row.currency)
			if flt(row.monthly_price) < 0 or flt(row.yearly_price) < 0:
				frappe.throw(_("Prices cannot be negative."))

	def on_update(self):
		frappe.clear_cache()
