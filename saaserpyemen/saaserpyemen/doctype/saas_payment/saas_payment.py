# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, now_datetime, today

from saaserpyemen.utils import (
	convert_amount,
	get_plan_by_identifier,
	get_settings,
	get_tenant_subscription,
	log_activity,
)


class SaaSPayment(Document):
	def validate(self):
		if not self.tenant or not frappe.db.exists("SaaS Tenant", self.tenant):
			frappe.throw(_("A valid workspace is required."))
		tenant = frappe.get_doc("SaaS Tenant", self.tenant)
		self.tenant_name = tenant.tenant_name
		if not self.plan:
			self.plan = tenant.plan
		if not self.subscription:
			self.subscription = tenant.subscription
		if not self.currency:
			self.currency = tenant.currency or get_settings().default_currency or "USD"
		if flt(self.amount) <= 0:
			frappe.throw(_("Payment amount must be greater than zero."))
		if not cint(self.months):
			yearly = str(self.billing_cycle or "").lower().startswith("y")
			self.months = 12 if yearly else 1
		self.months = min(12, max(1, cint(self.months)))
		self.billing_cycle = "Yearly" if self.months == 12 else "Monthly"

		settings = get_settings()
		base_currency = settings.default_currency or "USD"
		self.base_currency = base_currency
		self.base_amount = convert_amount(flt(self.amount), self.currency, base_currency)

		if not self.status:
			self.status = "Unpaid" if cint(self.is_invoice) else "Pending Review"
		if not self.due_date:
			self.due_date = self.period_start or today()

	def on_update(self):
		if self.status == "Paid" and self.subscription:
			subscription = frappe.db.get_value(
				"SaaS Subscription", self.subscription, ["status", "end_date"], as_dict=True
			)
			if subscription:
				frappe.db.set_value(
					"SaaS Tenant",
					self.tenant,
					{
						"status": "Active",
						"is_paid": 1,
						"suspended": 0,
						"subscription_ends_on": subscription.end_date,
					},
					update_modified=False,
				)

	def approve(self):
		if self.status == "Paid":
			frappe.throw(_("This payment is already approved."))
		if not self.subscription or not frappe.db.exists("SaaS Subscription", self.subscription):
			frappe.throw(_("This payment is not linked to a subscription."))

		subscription = frappe.get_doc("SaaS Subscription", self.subscription)
		if subscription.status == "Cancelled":
			frappe.throw(
				_("This subscription was cancelled and cannot be activated by a payment.")
			)
		subscription.extend(
			cycle=self.billing_cycle,
			note=_("Payment {0} approved.").format(self.name),
			period_start=self.period_start,
			period_end=self.period_end,
			payment=self.name,
		)

		self.status = "Paid"
		self.paid_on = self.paid_on or today()
		self.approved_by = frappe.session.user
		self.approved_on = now_datetime()
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)

		tenant = frappe.get_doc("SaaS Tenant", self.tenant)
		tenant.status = "Active"
		tenant.is_paid = 1
		tenant.suspended = 0
		tenant.subscription_ends_on = subscription.end_date
		tenant.flags.ignore_permissions = True
		tenant.save(ignore_permissions=True)

		if cint(get_settings().create_sales_invoice) and not self.sales_invoice:
			try:
				invoice = self.create_sales_invoice()
				if invoice:
					self.db_set("sales_invoice", invoice.name, update_modified=False)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"SaaS invoice for {self.name}")

		try:
			from saaserpyemen import tenant_ops

			tenant_ops.push_limits(tenant.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "SaaS push limits (payment)")

		# Additional workspaces are created without a site: they are provisioned
		# only once their first payment is approved.  Skip tenants that are
		# already being provisioned or whose site already exists.
		if tenant.provisioning_status in ("Pending", "Failed"):
			try:
				from saaserpyemen import provisioning

				if not provisioning._site_exists(tenant.site_name):
					provisioning.enqueue_provisioning(tenant.name)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "SaaS provision after payment")

		log_activity(
			self.tenant,
			"Payment approved",
			f"{self.name}: {self.amount} {self.currency}. Subscription ends {subscription.end_date}.",
		)
		return subscription

	def reject(self, reason: str | None = None):
		# Invoices stay open so the customer can submit a corrected receipt.
		# A cancelled subscription has nothing left to pay, so reject instead.
		if cint(self.is_invoice):
			cancelled = (
				self.subscription
				and frappe.db.get_value("SaaS Subscription", self.subscription, "status") == "Cancelled"
			)
			self.status = "Rejected" if cancelled else "Unpaid"
		else:
			self.status = "Rejected"
		self.notes = ((self.notes or "") + f"\n[{now_datetime()}] Rejected: {reason or '-'}").strip()
		self.approved_by = frappe.session.user
		self.approved_on = now_datetime()
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)

		if self.subscription and frappe.db.exists("SaaS Subscription", self.subscription):
			subscription = frappe.get_doc("SaaS Subscription", self.subscription)
			# Keep a currently valid paid period intact; only fall back to Unpaid
			# when this rejected payment was the one keeping the subscription alive.
			still_paid = (
				subscription.status == "Active"
				and subscription.end_date
				and getdate(subscription.end_date) >= getdate(today())
			)
			new_status = "Paid" if still_paid else "Unpaid"
			if subscription.payment_status != new_status:
				subscription.payment_status = new_status
				subscription.flags.ignore_permissions = True
				subscription.save(ignore_permissions=True)

		log_activity(self.tenant, "Payment rejected", f"{self.name}: {reason or '-'}")
		return self

	def create_sales_invoice(self):
		"""Create a Sales Invoice for this payment (optional ERPNext integration)."""
		settings = get_settings()
		company = settings.company or frappe.defaults.get_default_value("company")
		if not company:
			company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		if not company:
			return None

		customer = self._get_or_create_customer(settings)
		item = self._get_or_create_item(settings, company)

		invoice = frappe.new_doc("Sales Invoice")
		invoice.company = company
		invoice.customer = customer
		invoice.posting_date = self.paid_on or today()
		invoice.due_date = add_days(invoice.posting_date, cint(settings.invoice_due_days) or 7)
		invoice.currency = self.currency
		invoice.conversion_rate = self._conversion_rate(company, self.currency)
		invoice.saas_tenant = self.tenant
		invoice.saas_subscription = self.subscription
		invoice.saas_payment = self.name
		invoice.saas_period_start = self.period_start
		invoice.saas_period_end = self.period_end
		invoice.append(
			"items",
			{
				"item_code": item,
				"qty": 1,
				"rate": flt(self.amount),
				"description": _("SaaS subscription — {0} ({1}, {2} month(s)) {3} to {4}").format(
					self.tenant_name or self.tenant,
					self.billing_cycle,
					cint(self.months) or 1,
					self.period_start or "-",
					self.period_end or "-",
				),
			},
		)
		try:
			invoice.set_missing_values()
		except Exception:
			pass
		invoice.flags.ignore_permissions = True
		invoice.insert(ignore_permissions=True)
		try:
			invoice.submit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"SaaS invoice submit {invoice.name}")
		return invoice

	def _conversion_rate(self, company: str, currency: str) -> float:
		company_currency = frappe.db.get_value("Company", company, "default_currency") or currency
		if company_currency == currency:
			return 1.0
		from saaserpyemen.utils import get_exchange_rate

		rate = get_exchange_rate(currency, company_currency)
		return flt(rate) or 1.0

	def _get_or_create_customer(self, settings) -> str:
		existing = frappe.db.get_value("Customer", {"saas_tenant": self.tenant}, "name")
		if existing:
			return existing
		customer = frappe.new_doc("Customer")
		customer.customer_name = self.tenant_name or self.tenant
		customer.customer_type = "Company"
		customer_group = (
			settings.default_customer_group
			or frappe.db.get_single_value("Selling Settings", "customer_group")
			or frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="lft asc")
			or frappe.db.get_value("Customer Group", {}, "name", order_by="lft asc")
		)
		territory = (
			settings.default_territory
			or frappe.db.get_single_value("Selling Settings", "territory")
			or frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="lft asc")
			or frappe.db.get_value("Territory", {}, "name", order_by="lft asc")
		)
		customer.customer_group = customer_group
		customer.territory = territory
		customer.saas_tenant = self.tenant
		customer.flags.ignore_permissions = True
		customer.insert(ignore_permissions=True)
		return customer.name

	def _get_or_create_item(self, settings, company: str) -> str:
		item_code = "SAAS-SUBSCRIPTION"
		existing = frappe.db.get_value("Item", {"saas_service_item": 1}, "name")
		if existing:
			return existing
		if frappe.db.exists("Item", item_code):
			item = frappe.get_doc("Item", item_code)
			item.db_set("saas_service_item", 1, update_modified=False)
			return item.name
		item = frappe.new_doc("Item")
		item.item_code = item_code
		item.item_name = _("SaaS Subscription")
		item.saas_service_item = 1
		item.item_group = (
			frappe.db.get_value("Item Group", {"is_group": 0}, "name", order_by="lft asc")
			or frappe.db.get_value("Item Group", {}, "name", order_by="lft asc")
		)
		item.stock_uom = (
			frappe.db.get_value("UOM", {"name": "Nos"}, "name")
			or frappe.db.get_value("UOM", {}, "name")
		)
		item.is_stock_item = 0
		item.is_sales_item = 1
		item.include_item_in_manufacturing = 0
		income_account = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Income Account", "is_group": 0},
			"name",
		)
		item.append(
			"item_defaults",
			{"company": company, "income_account": income_account, "default_warehouse": None},
		)
		item.flags.ignore_permissions = True
		item.insert(ignore_permissions=True)
		return item.name
