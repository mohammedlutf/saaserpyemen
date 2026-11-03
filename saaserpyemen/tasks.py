# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt
"""Scheduled jobs for subscriptions, reminders and usage sync."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate, today

from saaserpyemen import tenant_ops
from saaserpyemen.utils import (
	format_money,
	get_billing_period,
	get_days_left,
	get_months_amount,
	get_plan_by_identifier,
	get_settings,
	get_site_url,
	log_activity,
)


def daily() -> None:
	print("Running SaaS daily jobs...")
	for job in (
		issue_upcoming_invoices,
		mark_past_due,
		expire_subscriptions,
		send_expiry_reminders,
		sync_usage,
		cleanup_old_logs,
	):
		try:
			job()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"SaaS daily job failed: {job.__name__}")
	frappe.db.commit()


# Expiry reminders look this many days ahead. Invoices must be issued no later
# than the first reminder so customers always receive a payable invoice.
REMINDER_LEAD_DAYS = 7


def hourly() -> None:
	# Reserved for future use (retries, webhooks).  Kept intentionally light.
	return None


def weekly() -> None:
	try:
		tenant_ops.sync_all_tenants()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS weekly usage sync")
	frappe.db.commit()


def monthly() -> None:
	try:
		cleanup_old_logs(days=730)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS monthly cleanup")
	frappe.db.commit()


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Invoicing
# ---------------------------------------------------------------------------
def issue_upcoming_invoices() -> None:
	"""Issue an invoice before a subscription expires or a reminder is sent.

	Invoices are idempotent: a subscription that already has an open invoice
	(Unpaid) or a payment under review is skipped, and the deterministic
	`invoice_key` protects against a concurrent scheduler run.
	"""
	settings = get_settings()
	if not cint(settings.auto_issue_invoices):
		return

	lead_days = max(cint(settings.invoice_lead_days) or 0, REMINDER_LEAD_DAYS)
	horizon = add_days(today(), lead_days)
	rows = frappe.get_all(
		"SaaS Subscription",
		filters={
			"status": ["in", ["Trial", "Active", "Past Due"]],
			"end_date": ["<=", horizon],
		},
		fields=["name", "tenant", "plan", "billing_cycle", "currency"],
		order_by="end_date asc",
	)

	for row in rows:
		if not row.tenant or not frappe.db.exists("SaaS Tenant", row.tenant):
			continue
		if frappe.db.exists(
			"SaaS Payment",
			{
				"subscription": row.name,
				"status": ["in", ["Unpaid", "Pending Review"]],
			},
		):
			continue

		subscription = frappe.get_doc("SaaS Subscription", row.name)
		if subscription.status in ("Cancelled", "Expired"):
			continue

		months = 12 if str(subscription.billing_cycle or "").lower().startswith("y") else 1
		period_start, period_end = get_billing_period(subscription, months=months)
		invoice_key = f"{row.tenant}|{subscription.name}|{period_start}|{period_end}"
		if frappe.db.exists("SaaS Payment", {"invoice_key": invoice_key}):
			continue

		tenant = frappe.db.get_value(
			"SaaS Tenant", row.tenant, ["currency"], as_dict=True
		) or frappe._dict()
		currency = subscription.currency or tenant.currency or settings.default_currency or "USD"

		plan = get_plan_by_identifier(subscription.plan)
		fallback = flt(subscription.amount)
		if str(subscription.billing_cycle or "").lower().startswith("y") and fallback:
			fallback = fallback / 12
		amount = get_months_amount(plan, currency, months, fallback_monthly=fallback)
		if not flt(amount):
			continue

		end_date = getdate(subscription.end_date) if subscription.end_date else None
		due_date = end_date if end_date and end_date >= getdate(today()) else getdate(today())

		invoice = frappe.new_doc("SaaS Payment")
		invoice.update(
			{
				"tenant": row.tenant,
				"subscription": subscription.name,
				"plan": subscription.plan,
				"status": "Unpaid",
				"is_invoice": 1,
				"months": months,
				"amount": amount,
				"currency": currency,
				"billing_cycle": subscription.billing_cycle,
				"period_start": period_start,
				"period_end": period_end,
				"due_date": due_date,
				"invoice_key": invoice_key,
				"notes": _("Invoice issued automatically before the subscription period ended."),
			}
		)
		invoice.flags.ignore_permissions = True
		try:
			invoice.insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			# A concurrent scheduler run issued the same invoice first.
			continue
		log_activity(
			row.tenant,
			"Invoice issued",
			f"Invoice {invoice.name}: {amount} {currency}, due {due_date}.",
			user="Administrator",
		)


def mark_past_due() -> None:
	"""Move subscriptions whose paid period ended into Past Due."""
	settings = get_settings()
	grace = cint(settings.grace_days) or 0
	cutoff = add_days(today(), -grace)

	subscriptions = frappe.get_all(
		"SaaS Subscription",
		filters={
			"status": ["in", ["Active", "Trial"]],
			"end_date": ["<", cutoff],
		},
		fields=["name", "tenant", "tenant_name", "end_date", "billing_cycle"],
	)
	for row in subscriptions:
		subscription = frappe.get_doc("SaaS Subscription", row.name)
		subscription.status = "Past Due"
		subscription.flags.ignore_permissions = True
		subscription.save(ignore_permissions=True)
		if subscription.tenant:
			frappe.db.set_value(
				"SaaS Tenant",
				subscription.tenant,
				{"status": "Past Due"},
				update_modified=False,
			)
		log_activity(
			subscription.tenant,
			"Past due",
			f"Billing period ended on {row.end_date}.",
			user="Administrator",
		)


def expire_subscriptions() -> None:
	settings = get_settings()
	grace = cint(settings.grace_days) or 0
	cutoff = add_days(today(), -grace)
	
	subscriptions = frappe.get_all(
		"SaaS Subscription",
		filters={
			"status": ["in", ["Past Due", "Trial", "Active"]],
			"end_date": ["<", cutoff],
		},
		fields=["name", "tenant", "tenant_name", "end_date"],
	)
	
	for row in subscriptions:
		subscription = frappe.get_doc("SaaS Subscription", row.name)
		subscription.status = "Expired"
		subscription.flags.ignore_permissions = True
		subscription.save(ignore_permissions=True)
		if not subscription.tenant:
			continue

		tenant = frappe.get_doc("SaaS Tenant", subscription.tenant)
		tenant.status = "Expired"
		tenant.flags.ignore_permissions = True
		tenant.save(ignore_permissions=True)
		log_activity(tenant.name, "Expired", f"Subscription ended on {row.end_date}.")

		if cint(settings.auto_suspend_on_expiry) and not tenant.suspended:
			try:
				tenant_ops.suspend_tenant(tenant.name, _("Subscription expired"))
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"SaaS auto suspend {tenant.name}")


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------
def send_expiry_reminders() -> None:
	settings = get_settings()
	if not cint(settings.send_expiry_reminders):
		return

	rows = frappe.get_all(
		"SaaS Subscription",
		filters={
			"status": ["in", ["Trial", "Active", "Past Due"]],
			"end_date": ["between", [today(), add_days(today(), REMINDER_LEAD_DAYS)]],
		},
		fields=[
			"name",
			"tenant",
			"tenant_name",
			"end_date",
			"amount",
			"currency",
			"billing_cycle",
			"last_reminder_on",
			"status",
		],
	)
	for row in rows:
		if row.last_reminder_on and getdate(row.last_reminder_on) == getdate(today()):
			continue
		tenant = frappe.db.get_value(
			"SaaS Tenant", row.tenant, ["admin_email", "subdomain", "tenant_name"], as_dict=True
		)
		if not tenant or not tenant.admin_email:
			continue

		days = get_days_left(row.end_date)
		label = _("trial") if row.status == "Trial" else _("subscription")
		subject = _("Your {0} ends in {1} day(s) — {2}").format(label, days, row.tenant_name)
		invoices = frappe.get_all(
			"SaaS Payment",
			filters={"subscription": row.name, "status": "Unpaid"},
			fields=["name", "amount", "currency", "due_date"],
			order_by="creation desc",
			limit=1,
		)
		invoice = invoices[0] if invoices else None
		payment_url = f"{frappe.utils.get_url()}/payment?tenant={row.tenant}"
		invoice_html = ""
		if invoice:
			payment_url += f"&invoice={invoice.name}"
			invoice_html = (
				"<p>"
				+ _("Invoice <b>{0}</b> for <b>{1}</b> is ready. Due date: <b>{2}</b>.").format(
					frappe.utils.escape_html(invoice.name),
					format_money(invoice.amount, invoice.currency),
					frappe.utils.escape_html(str(invoice.due_date or row.end_date)),
				)
				+ "</p>"
			)
		message = f"""
			<div style="font-family:Inter,Arial,sans-serif;line-height:1.6">
				<p>{_('Hello')} {frappe.utils.escape_html(tenant.tenant_name)},</p>
				<p>{_('Your {0} for <b>{1}</b> ends on <b>{2}</b> ({3} day(s) left).').format(
					label, frappe.utils.escape_html(tenant.tenant_name), row.end_date, days
				)}</p>
				{invoice_html}
				<p>{_('To keep your workspace active, please complete your payment before the end date.')}</p>
				<p><a href="{payment_url}" style="display:inline-block;padding:12px 22px;border-radius:10px;background:#0d9488;color:#fff;text-decoration:none">
					{_('Pay now')}
				</a></p>
			</div>
		"""
		try:
			frappe.sendmail(recipients=[tenant.admin_email], subject=subject, message=message, now=False)
			frappe.db.set_value(
				"SaaS Subscription", row.name, "last_reminder_on", today(), update_modified=False
			)
			log_activity(row.tenant, "Reminder sent", f"Expiry reminder ({days} days).", user="Administrator")
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"SaaS reminder {row.name}")


def sync_usage() -> None:
	try:
		tenant_ops.sync_all_tenants()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS daily usage sync")


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
def cleanup_old_logs(days: int = 365) -> None:
	cutoff = add_days(today(), -cint(days))
	for doctype in ("SaaS Activity", "SaaS Usage Snapshot"):
		try:
			frappe.db.delete(doctype, {"creation": ["<", cutoff]})
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"SaaS cleanup {doctype}")

	provisioning_cutoff = add_days(today(), -90)
	try:
		frappe.db.delete("SaaS Provisioning Log", {"creation": ["<", provisioning_cutoff]})
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS cleanup provisioning logs")
