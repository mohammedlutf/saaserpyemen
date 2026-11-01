# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, cint, flt, getdate, today

from saaserpyemen.utils import (
	get_billing_period,
	get_plan_by_identifier,
	get_plan_price,
	get_settings,
	get_trial_end,
	log_activity,
)


class SaaSSubscription(Document):
	def validate(self):
		self.billing_cycle = "Yearly" if str(self.billing_cycle or "").lower().startswith("y") else "Monthly"
		settings = get_settings()

		if not self.start_date:
			self.start_date = today()
		if not self.currency:
			self.currency = settings.default_currency or "USD"
		if not self.status:
			self.status = "Trial"

		tenant = None
		if self.tenant and frappe.db.exists("SaaS Tenant", self.tenant):
			tenant = frappe.get_doc("SaaS Tenant", self.tenant)
			self.tenant_name = tenant.tenant_name
			self.subdomain = tenant.subdomain
			if not self.currency:
				self.currency = tenant.currency

		plan = get_plan_by_identifier(self.plan) if self.plan else None
		if plan:
			if not flt(self.amount):
				self.amount = get_plan_price(plan, self.currency, self.billing_cycle)
			if self.status == "Trial" and not self.trial_end_date:
				self.trial_end_date = get_trial_end(plan, self.start_date)

		# Only trials carry a trial end date.  Additional (paid) workspaces start
		# as Pending and must never inherit a free-trial period.
		if self.status == "Trial" and not self.trial_end_date:
			self.trial_end_date = self.start_date
		if self.status == "Pending":
			self.trial_end_date = None

		if not self.end_date:
			self.end_date = self.trial_end_date or self.start_date
		if not self.next_billing_date and self.status != "Pending":
			self.next_billing_date = add_days(getdate(self.end_date), 1)

		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End date cannot be before the start date."))

	def on_update(self):
		self._sync_tenant()
		self._push_limits()

	def _sync_tenant(self):
		if not self.tenant or not frappe.db.exists("SaaS Tenant", self.tenant):
			return
		status_map = {
			"Trial": "Trial",
			"Pending": "Pending Payment",
			"Active": "Active",
			"Past Due": "Past Due",
			"Expired": "Expired",
			"Cancelled": "Cancelled",
		}
		values = {
			"subscription": self.name,
			"plan": self.plan,
			"currency": self.currency,
			"trial_ends_on": self.trial_end_date,
			"subscription_ends_on": self.end_date,
		}
		status = status_map.get(self.status)
		if status:
			values["status"] = status
			if status in ("Active", "Trial"):
				values["suspended"] = 0
				values["is_paid"] = 1 if status == "Active" else 0
		for field, value in values.items():
			frappe.db.set_value("SaaS Tenant", self.tenant, field, value, update_modified=False)

	def _push_limits(self):
		if not self.tenant:
			return
		try:
			from saaserpyemen import tenant_ops

			tenant_ops.push_limits(self.tenant)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "SaaS push limits (subscription)")

	def extend(
		self,
		cycle: str | None = None,
		note: str | None = None,
		period_start=None,
		period_end=None,
		payment: str | None = None,
	) -> None:
		"""Extend the paid period and activate the subscription."""
		cycle = "Yearly" if str(cycle or self.billing_cycle or "Monthly").lower().startswith("y") else "Monthly"
		months = 12 if cycle == "Yearly" else 1

		if period_start:
			start = getdate(period_start)
		else:
			start = getdate(today())
			if self.end_date and getdate(self.end_date) >= start:
				start = add_days(getdate(self.end_date), 1)

		if period_end:
			end = getdate(period_end)
		else:
			end = add_days(add_months(start, months), -1)

		if self.end_date and getdate(self.end_date) > end:
			end = getdate(self.end_date)

		self.billing_cycle = cycle
		self.end_date = end
		self.next_billing_date = add_days(end, 1)
		self.status = "Active"
		self.payment_status = "Paid"
		self.auto_renew = 1
		self.cancelled_on = None
		self.cancel_reason = None
		if payment:
			self.last_payment = payment
		if note:
			self.notes = ((self.notes or "") + "\n" + note).strip()
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)
		log_activity(
			self.tenant,
			"Subscription extended",
			f"Cycle: {cycle}, period: {start} → {end}",
		)

	def mark_past_due(self, note: str | None = None) -> None:
		self.status = "Past Due"
		if note:
			self.notes = ((self.notes or "") + "\n" + note).strip()
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)

	def expire(self, note: str | None = None) -> None:
		self.status = "Expired"
		if note:
			self.notes = ((self.notes or "") + "\n" + note).strip()
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)

	def get_next_period(self) -> tuple:
		return get_billing_period(self)
