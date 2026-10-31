# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt
"""Tenant operations: usage sync, limits, suspension and cleanup."""

from __future__ import annotations

import json
import os

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, today
from werkzeug.exceptions import HTTPException
from werkzeug.utils import redirect
from saaserpyemen.provisioning import (
	_bench,
	_bench_command,
	_check,
	_drop_site,
	_site_dir,
	_site_exists,
	get_site_config,
	update_site_config,
)
from saaserpyemen.utils import (
	create_provisioning_log,
	get_central_url,
	get_full_site_name,
	get_plan_by_identifier,
	get_plan_limits,
	get_settings,
	get_site_url,
	is_tenant_site,
	log_activity,
)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def _connect(tenant_doc):
	import pymysql

	config = get_site_config(tenant_doc.site_name)
	db_name = config.get("db_name") or tenant_doc.db_name
	db_password = config.get("db_password")
	if not db_password:
		try:
			db_password = tenant_doc.get_password("db_password", raise_exception=False)
		except Exception:
			db_password = None
	if not db_name or not db_password:
		raise RuntimeError(_("Database credentials for this workspace are not available."))

	host = config.get("db_host") or frappe.conf.get("db_host") or "localhost"
	port = cint(config.get("db_port") or frappe.conf.get("db_port") or 3306)
	kwargs = {
		"user": db_name,
		"password": db_password,
		"database": db_name,
		"charset": "utf8mb4",
		"connect_timeout": 10,
	}
	if host in ("localhost", "127.0.0.1", "::1"):
		socket = (
			config.get("db_socket")
			or frappe.conf.get("db_socket")
			or "/run/mysqld/mysqld.sock"
		)
		if os.path.exists(socket):
			kwargs["unix_socket"] = socket
		else:
			kwargs.update({"host": "127.0.0.1", "port": port})
	else:
		kwargs.update({"host": host, "port": port})

	return pymysql.connect(**kwargs)


def _scalar(connection, query: str, params=None, default: int = 0) -> int:
	try:
		with connection.cursor() as cursor:
			cursor.execute(query, params or ())
			row = cursor.fetchone()
			return int(row[0] or 0) if row else default
	except Exception:
		return default


def _site_storage_mb(site: str) -> float:
	total = 0
	for relative in ("public/files", "private/files", "public", "private"):
		path = os.path.join(_site_dir(site), relative)
		if not os.path.isdir(path):
			continue
		for root, _dirs, files in os.walk(path):
			for name in files:
				try:
					total += os.path.getsize(os.path.join(root, name))
				except OSError:
					pass
	return round(total / (1024 * 1024), 2)


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
def collect_usage(tenant_doc) -> dict:
	"""Read live usage from the tenant database."""
	if not tenant_doc.site_name or not _site_exists(tenant_doc.site_name):
		raise RuntimeError(_("The workspace site does not exist yet."))

	connection = _connect(tenant_doc)
	try:
		users = _scalar(
			connection,
			"""
			select count(*) from `tabUser`
			where enabled = 1
				and name not in ('Administrator', 'Guest')
				and ifnull(user_type, 'System User') != 'Website User'
			""",
		)
		branches = _scalar(connection, "select count(*) from `tabBranch`")
		companies = _scalar(connection, "select count(*) from `tabCompany`")
		db_size = _scalar(
			connection,
			"""
			select round(sum(data_length + index_length) / 1024 / 1024, 2)
			from information_schema.tables where table_schema = %s
			""",
			(tenant_doc.db_name or get_site_config(tenant_doc.site_name).get("db_name"),),
		)
	finally:
		connection.close()

	file_size = _site_storage_mb(tenant_doc.site_name)
	return {
		"users_count": users,
		"branches_count": branches,
		"companies_count": companies,
		"storage_used_mb": round(flt(db_size) + flt(file_size), 2),
	}


def sync_usage(tenant: str) -> dict:
	tenant_doc = frappe.get_doc("SaaS Tenant", tenant)
	try:
		usage = collect_usage(tenant_doc)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), f"SaaS usage sync: {tenant}")
		return {"ok": False, "error": str(exc)}

	for field, value in usage.items():
		tenant_doc.db_set(field, value, update_modified=False)
	tenant_doc.db_set("last_usage_sync", now_datetime(), update_modified=False)

	_save_snapshot(tenant_doc, usage)
	frappe.db.commit()

	# Warn once a day when a limit is crossed.
	_check_limits_notification(tenant_doc)
	return {"ok": True, **usage}


def sync_all_tenants() -> dict:
	tenants = frappe.get_all(
		"SaaS Tenant",
		filters={"status": ["in", ["Trial", "Active", "Past Due", "Suspended"]]},
		pluck="name",
	)
	results = {"total": len(tenants), "ok": 0, "failed": 0}
	for tenant in tenants:
		result = sync_usage(tenant)
		if result.get("ok"):
			results["ok"] += 1
		else:
			results["failed"] += 1
	return results


def _save_snapshot(tenant_doc, usage: dict) -> None:
	existing = frappe.db.get_value(
		"SaaS Usage Snapshot", {"tenant": tenant_doc.name, "date": today()}, "name"
	)
	if existing:
		doc = frappe.get_doc("SaaS Usage Snapshot", existing)
	else:
		doc = frappe.new_doc("SaaS Usage Snapshot")
		doc.tenant = tenant_doc.name
		doc.date = today()
	doc.update(usage)
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)


def _check_limits_notification(tenant_doc) -> None:
	plan = get_plan_by_identifier(tenant_doc.plan)
	if not plan:
		return
	limits = get_plan_limits(plan)
	alerts = []
	for field, limit_field, label in (
		("users_count", "max_users", _("users")),
		("branches_count", "max_branches", _("branches")),
		("companies_count", "max_companies", _("companies")),
	):
		limit = limits.get(limit_field) or 0
		if limit and cint(tenant_doc.get(field)) >= limit:
			alerts.append(f"{tenant_doc.get(field)}/{limit} {label}")
	storage = limits.get("storage_gb") or 0
	if storage and flt(tenant_doc.storage_used_mb) >= storage * 1024:
		alerts.append(f"{tenant_doc.storage_used_mb} MB / {storage} GB")

	if not alerts or not tenant_doc.admin_email:
		return
	cache_key = f"saas_limit_alert:{tenant_doc.name}:{today()}"
	if frappe.cache.get_value(cache_key):
		return
	frappe.cache.set_value(cache_key, 1, expires_in_sec=86400)
	try:
		frappe.sendmail(
			recipients=[tenant_doc.admin_email],
			subject=_("You are approaching your plan limits — {0}").format(tenant_doc.tenant_name),
			message=(
				f"<p>{_('Your workspace has reached the following plan limits:')}</p>"
				f"<ul>{''.join(f'<li>{frappe.utils.escape_html(x)}</li>' for x in alerts)}</ul>"
				f"<p><a href='{get_central_url()}/plans?change=1&tenant={tenant_doc.name}'>{_('Upgrade your plan')}</a></p>"
			),
			now=False,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS limit notification")


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
def push_limits(tenant_doc) -> None:
	"""Write plan limits to the tenant site config (used by tenant hooks)."""
	if isinstance(tenant_doc, str):
		tenant_doc = frappe.get_doc("SaaS Tenant", tenant_doc)
	if not tenant_doc.site_name or not _site_exists(tenant_doc.site_name):
		return
	plan = get_plan_by_identifier(tenant_doc.plan)
	limits = get_plan_limits(plan) if plan else {}
	settings = get_settings()
	update_site_config(
		tenant_doc.site_name,
		{
			"saas_plan": tenant_doc.plan,
			"saas_max_users": limits.get("max_users", 0),
			"saas_max_branches": limits.get("max_branches", 0),
			"saas_max_companies": limits.get("max_companies", 0),
			"saas_storage_gb": limits.get("storage_gb", 0),
			"saas_suspended": cint(tenant_doc.suspended),
			"pause_scheduler": 0 if cint(settings.run_scheduler) and not cint(tenant_doc.suspended) else 1,
		},
	)


def get_local_limits() -> dict:
	return {
		"max_users": cint(frappe.conf.get("saas_max_users")),
		"max_branches": cint(frappe.conf.get("saas_max_branches")),
		"max_companies": cint(frappe.conf.get("saas_max_companies")),
		"storage_gb": cint(frappe.conf.get("saas_storage_gb")),
		"suspended": cint(frappe.conf.get("saas_suspended")),
		"plan": frappe.conf.get("saas_plan"),
	}


def _count_system_users() -> int:
	return cint(
		frappe.db.sql(
			"""
			select count(*) from `tabUser`
			where enabled = 1
				and name not in ('Administrator', 'Guest')
				and ifnull(user_type, 'System User') != 'Website User'
			"""
		)[0][0]
	)


def check_user_limit(doc, method=None) -> None:
	if not is_tenant_site():
		return
	if doc.user_type == "Website User":
		return
	limit = get_local_limits()["max_users"]
	if not limit:
		return
	current = _count_system_users()
	if doc.is_new() and current >= limit:
		frappe.throw(
			_("Your plan allows a maximum of {0} users. Please upgrade your plan to add more users.").format(limit),
			title=_("User limit reached"),
		)


def check_branch_limit(doc, method=None) -> None:
	if not is_tenant_site():
		return
	limit = get_local_limits()["max_branches"]
	if not limit:
		return
	if doc.is_new() and frappe.db.count("Branch") >= limit:
		frappe.throw(
			_("Your plan allows a maximum of {0} branches. Please upgrade your plan to add more branches.").format(limit),
			title=_("Branch limit reached"),
		)


def check_company_limit(doc, method=None) -> None:
	if not is_tenant_site():
		return
	limit = get_local_limits()["max_companies"]
	if not limit:
		return
	if doc.is_new() and frappe.db.count("Company") >= limit:
		frappe.throw(
			_("Your plan allows a maximum of {0} companies. Please upgrade your plan to add more companies.").format(limit),
			title=_("Company limit reached"),
		)


def check_storage_limit(doc, method=None) -> None:
	if not is_tenant_site():
		return
	limit_gb = get_local_limits()["storage_gb"]
	if not limit_gb:
		return
	used = _site_storage_mb(frappe.local.site)
	if used >= limit_gb * 1024:
		frappe.throw(
			_("Your workspace storage is full ({0} GB). Please upgrade your plan or remove old files.").format(limit_gb),
			title=_("Storage limit reached"),
		)


# ---------------------------------------------------------------------------
# Request guard (tenant sites only)
# ---------------------------------------------------------------------------
ALLOWED_PREFIXES = (
	"/app",
	"/assets",
	"/api",
	"/files",
	"/private",
	"/login",
	"/logout",
	"/update-password",
	"/reset-password",
	"/favicon",
	"/robots.txt",
	"/website_script",
	"/desk",
	"/.well-known",
)


def before_request() -> None:
	
	if not is_tenant_site():
		return

	path = (frappe.local.request.path or "/").split("?")[0]
	
	# Suspended tenants are sent to the central site.
	if cint(frappe.conf.get("saas_suspended")):
		if not path.startswith("/assets") and not path.startswith("/api"):
			central = (frappe.conf.get("saas_central_url") or "").rstrip("/")
			if central:
				response = redirect(
					f"{central}/suspended?site={frappe.conf.get('saas_subdomain') or ''}"
				)
				raise HTTPException(response=response)

	# Tenant sites are ERP workspaces, not marketing websites.
	if path in ("", "/", "/index"):
	   
		
		# 1. Create the redirection response object
		response = redirect("/app")
		
		# 2. Wrap it in a clean HTTP exception and throw it to interrupt Frappe
		raise HTTPException(response=response)

	if any(path == prefix or path.startswith(prefix + "/") for prefix in ALLOWED_PREFIXES):
		return

	if path.startswith("/api/method/") or path.startswith("/api/resource/"):
		return

	frappe.local.flags.redirect_location = "/app"
	raise frappe.Redirect


# ---------------------------------------------------------------------------
# Suspension
# ---------------------------------------------------------------------------
def suspend_tenant(tenant: str, reason: str | None = None) -> None:
	tenant_doc = frappe.get_doc("SaaS Tenant", tenant)
	tenant_doc.status = "Suspended"
	tenant_doc.suspended = 1
	tenant_doc.notes = (tenant_doc.notes or "") + f"\n[{now_datetime()}] Suspended: {reason or '-'}"
	tenant_doc.flags.ignore_permissions = True
	tenant_doc.save(ignore_permissions=True)
	frappe.db.commit()

	if tenant_doc.site_name and _site_exists(tenant_doc.site_name):
		push_limits(tenant_doc)
	log_activity(tenant, "Suspended", reason or "Suspended by administrator")
	_notify_suspension(tenant_doc, suspended=True, reason=reason)


def unsuspend_tenant(tenant: str) -> None:
	tenant_doc = frappe.get_doc("SaaS Tenant", tenant)
	subscription_status = frappe.db.get_value(
		"SaaS Subscription", tenant_doc.subscription, "status"
	) if tenant_doc.subscription else None
	if subscription_status == "Trial":
		tenant_doc.status = "Trial"
	elif subscription_status in ("Active", "Past Due"):
		tenant_doc.status = subscription_status
	else:
		tenant_doc.status = "Active"
	tenant_doc.suspended = 0
	tenant_doc.flags.ignore_permissions = True
	tenant_doc.save(ignore_permissions=True)
	frappe.db.commit()

	if tenant_doc.site_name and _site_exists(tenant_doc.site_name):
		push_limits(tenant_doc)
	log_activity(tenant, "Unsuspended", "Reactivated by administrator")
	_notify_suspension(tenant_doc, suspended=False)


def _notify_suspension(tenant_doc, suspended: bool, reason: str | None = None) -> None:
	if not tenant_doc.admin_email:
		return
	try:
		if suspended:
			subject = _("Your workspace has been suspended — {0}").format(tenant_doc.tenant_name)
			body = (
				f"<p>{_('Your workspace has been suspended.')}</p>"
				f"<p><b>{_('Reason')}:</b> {frappe.utils.escape_html(reason or '-')}</p>"
				f"<p>{_('Please contact support or complete your payment to reactivate it.')}</p>"
			)
		else:
			subject = _("Your workspace is active again — {0}").format(tenant_doc.tenant_name)
			body = f"<p>{_('Your workspace has been reactivated.')}</p>"
		frappe.sendmail(recipients=[tenant_doc.admin_email], subject=subject, message=body, now=False)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS suspension notification")


# ---------------------------------------------------------------------------
# Company / profile sync
# ---------------------------------------------------------------------------
def update_site_company(tenant: str, company_name: str) -> dict:
	tenant_doc = frappe.get_doc("SaaS Tenant", tenant)
	if not tenant_doc.site_name or not _site_exists(tenant_doc.site_name):
		return {"ok": False, "error": "Site not found"}
	args = json.dumps([company_name])
	result = _bench(
		"--site",
		tenant_doc.site_name,
		"execute",
		"saaserpyemen.tenant_ops.rename_company",
		"--args",
		args,
		timeout=300,
	)
	try:
		_check(result, "rename_company")
	except Exception as exc:
		frappe.log_error(str(exc), "SaaS rename company")
		return {"ok": False, "error": str(exc)}
	return {"ok": True}


def rename_company(company_name: str) -> dict:
	"""Executed on the tenant site."""
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not company:
		return {"ok": False}
	frappe.db.set_value("Company", company, "company_name", company_name, update_modified=False)
	frappe.db.set_value("System Settings", "System Settings", "app_name", company_name, update_modified=False)
	frappe.db.set_value("Website Settings", "Website Settings", "app_name", company_name, update_modified=False)
	frappe.db.commit()
	frappe.clear_cache()
	return {"ok": True, "company": company}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------
def delete_tenant(tenant: str, confirm: str | None = None) -> None:
	tenant_doc = frappe.get_doc("SaaS Tenant", tenant)
	expected = tenant_doc.subdomain or tenant_doc.name
	if (confirm or "").strip().lower() not in {expected.lower(), "delete"}:
		frappe.throw(
			_("Please type the subdomain ({0}) to confirm deletion.").format(expected),
			title=_("Confirmation required"),
		)

	site = tenant_doc.site_name or get_full_site_name(tenant_doc.subdomain)
	log = create_provisioning_log(tenant, site, "Delete")
	try:
		if site and _site_exists(site):
			_drop_site(site)
		tenant_doc.reload()
		tenant_doc.status = "Cancelled"
		tenant_doc.suspended = 1
		tenant_doc.notes = (tenant_doc.notes or "") + f"\n[{now_datetime()}] Site deleted by administrator."
		tenant_doc.flags.ignore_permissions = True
		tenant_doc.save(ignore_permissions=True)

		if tenant_doc.subscription and frappe.db.exists("SaaS Subscription", tenant_doc.subscription):
			subscription = frappe.get_doc("SaaS Subscription", tenant_doc.subscription)
			subscription.status = "Cancelled"
			subscription.cancelled_on = today()
			subscription.cancel_reason = _("Workspace deleted by administrator")
			subscription.flags.ignore_permissions = True
			subscription.save(ignore_permissions=True)

		frappe.db.commit()
		if log:
			log.status = "Success"
			log.completed_on = now_datetime()
			log.message = "Site deleted."
			log.flags.ignore_permissions = True
			log.save(ignore_permissions=True)
		log_activity(tenant, "Deleted", f"Site {site} deleted.")
	except Exception as exc:
		if log:
			log.status = "Failed"
			log.completed_on = now_datetime()
			log.message = str(exc)[:1000]
			log.flags.ignore_permissions = True
			log.save(ignore_permissions=True)
		frappe.db.commit()
		raise
