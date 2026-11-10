# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt
"""Automatic tenant site provisioning.

The central site owns the customer records.  A tenant is a fully isolated
ERPNext site (its own database and files) created by cloning the template site
configured in *SaaS Settings* (``saas-default.com`` by default).

Every step is executed through the bench CLI so that it behaves exactly like a
manual ``bench new-site``.  The heavy work runs in a background job.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import time

import frappe
from frappe import _
from frappe.utils import cint, get_bench_path, now_datetime

from saaserpyemen.utils import (
	create_provisioning_log,
	generate_password,
	get_central_url,
	get_full_site_name,
	get_plan_by_identifier,
	get_plan_limits,
	get_settings,
	get_site_url,
	log_activity,
)

DEFAULT_TEMPLATE_SITE = "saas-default.com"
CLIENT_APP = "saas_client"
LEGACY_TENANT_APP = "saaserpyemen"


# ---------------------------------------------------------------------------
# Low level helpers
# ---------------------------------------------------------------------------
def _bench_path() -> str:
	settings = get_settings()
	path = (settings.bench_path or "").strip() or get_bench_path()
	return os.path.abspath(path)


def _sites_path() -> str:
	settings = get_settings()
	path = (settings.sites_path or "").strip() or os.path.join(_bench_path(), "sites")
	return os.path.abspath(path)


def _bench_command() -> str:
	settings = get_settings()
	command = (settings.bench_command or "").strip() or "bench"
	if os.path.sep in command:
		return command
	found = shutil.which(command)
	return found or command


def _template_site() -> str:
	settings = get_settings()
	return (settings.template_site or DEFAULT_TEMPLATE_SITE).strip()


def _site_dir(site: str) -> str:
	return os.path.join(_sites_path(), site)


def _site_exists(site: str) -> bool:
	return os.path.isdir(_site_dir(site))


def _read_json(path: str) -> dict:
	try:
		with open(path) as fh:
			return json.load(fh)
	except Exception:
		return {}


def _write_json(path: str, data: dict) -> None:
	tmp = path + ".tmp"
	with open(tmp, "w") as fh:
		json.dump(data, fh, indent=1, sort_keys=True)
		fh.write("\n")
	os.replace(tmp, path)


def get_site_config(site: str) -> dict:
	return _read_json(os.path.join(_site_dir(site), "site_config.json"))


def update_site_config(site: str, updates: dict, remove_keys=None) -> dict:
	path = os.path.join(_site_dir(site), "site_config.json")
	config = _read_json(path)
	config.update({key: value for key, value in (updates or {}).items() if value is not None})
	for key in remove_keys or ():
		config.pop(key, None)
	_write_json(path, config)
	return config


def _run(command, *, timeout: int = 1800, cwd: str | None = None) -> subprocess.CompletedProcess:
	env = os.environ.copy()
	env.setdefault("LC_ALL", "C.UTF-8")
	env.setdefault("LANG", "C.UTF-8")
	env.setdefault("HOME", os.path.expanduser("~"))
	result = subprocess.run(
		command,
		cwd=cwd or _bench_path(),
		capture_output=True,
		text=True,
		timeout=timeout,
		env=env,
	)
	return result


def _bench(*args, timeout: int = 1800) -> subprocess.CompletedProcess:
	command = [_bench_command(), *[str(arg) for arg in args]]
	return _run(command, timeout=timeout)


def _check(result: subprocess.CompletedProcess, step: str) -> str:
	output = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
	if result.returncode != 0:
		raise RuntimeError(f"{step} failed (exit {result.returncode}).\n{output[-8000:]}")
	return output


def _append_log(tenant: str, message: str) -> None:
	"""Append a timestamped line to the tenant provisioning log."""
	try:
		current = frappe.db.get_value("SaaS Tenant", tenant, "provisioning_log") or ""
		line = f"[{now_datetime().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
		text = (current + "\n" + line).strip()[-60000:]
		frappe.db.set_value("SaaS Tenant", tenant, "provisioning_log", text, update_modified=False)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS Provisioning Log")


def _finish_log(log, status: str, message: str = "", output: str = "", started: float | None = None):
	if not log:
		return
	try:
		log.status = status
		log.completed_on = now_datetime()
		if started:
			log.duration_seconds = round(time.time() - started, 2)
		if message:
			log.message = message[:1000]
		if output:
			log.output = output[-20000:]
		log.flags.ignore_permissions = True
		log.save(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS Provisioning Log Finish")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def enqueue_provisioning(tenant: str) -> None:
	"""Queue provisioning for a tenant (safe to call multiple times)."""
	settings = get_settings()
	tenant_doc = frappe.get_doc("SaaS Tenant", tenant)
	tenant_doc.db_set("status", "Provisioning", update_modified=False)
	tenant_doc.db_set("provisioning_status", "Pending", update_modified=False)
	tenant_doc.db_set("suspended", 0, update_modified=False)
	frappe.db.commit()

	timeout = cint(settings.provisioning_timeout) or 1800
	frappe.enqueue(
		"saaserpyemen.provisioning.provision_tenant",
		queue="long",
		timeout=timeout,
		tenant=tenant,
		job_name=f"saas-provision-{tenant}",
		enqueue_after_commit=True,
	)


def enqueue_ssl(tenant: str) -> None:
	settings = get_settings()
	timeout = max(300, cint(settings.provisioning_timeout) or 900)
	frappe.enqueue(
		"saaserpyemen.provisioning.issue_ssl",
		queue="long",
		timeout=timeout,
		tenant=tenant,
		job_name=f"saas-ssl-{tenant}",
		enqueue_after_commit=True,
	)


def provision_tenant(tenant: str) -> dict:
	"""Create and configure the tenant site.  Runs as a background job."""
	started = time.time()
	settings = get_settings()
	tenant_doc = frappe.get_doc("SaaS Tenant", tenant)
	subdomain = tenant_doc.subdomain
	site = tenant_doc.site_name or get_full_site_name(subdomain)
	template = _template_site()
	bench_path = _bench_path()
	timeout = cint(settings.provisioning_timeout) or 1800

	log = create_provisioning_log(tenant, site, "Provision")
	_append_log(tenant, f"Provisioning started for {site} from template {template}.")

	try:
		# -- validation ---------------------------------------------------
		if not subdomain:
			frappe.throw(_("Tenant has no subdomain."))
		if not _site_exists(template):
			frappe.throw(
				_("Template site {0} was not found in {1}.").format(template, _sites_path())
			)
		if _site_exists(site):
			_append_log(tenant, f"Site folder {site} already exists, removing it first.")
			_drop_site(site, timeout=timeout)

		tenant_doc.db_set("status", "Provisioning", update_modified=False)
		tenant_doc.db_set("provisioning_status", "Running", update_modified=False)
		tenant_doc.db_set("site_name", site, update_modified=False)
		tenant_doc.db_set("site_path", _site_dir(site), update_modified=False)
		frappe.db.commit()

		# -- admin password ----------------------------------------------
		password = tenant_doc.get_password("admin_temp_password", raise_exception=False)
		if not password:
			password = generate_password(20)
			tenant_doc.admin_temp_password = password
			tenant_doc.flags.ignore_permissions = True
			tenant_doc.save(ignore_permissions=True)
			frappe.db.commit()

		# -- backup template database ------------------------------------
		_append_log(tenant, "Creating a fresh backup of the template database.")
		dump_file = _backup_template(template, timeout=timeout)
		_append_log(tenant, f"Template backup ready: {os.path.basename(dump_file)}")

		# -- create the site and restore the template DB -----------------
		_append_log(tenant, f"Creating site {site}.")
		result = _bench(
			"new-site",
			site,
			"--source-sql",
			dump_file,
			"--db-root-username",
			settings.db_root_user or "root",
			"--db-root-password",
			settings.get_password("db_root_password", raise_exception=False) or "",
			"--admin-password",
			password,
			"--force",
			timeout=timeout,
		)
		output = _check(result, "bench new-site")
		_append_log(tenant, f"Site {site} created and database restored.")

		# -- copy uploaded files -----------------------------------------
		_copied = _copy_site_files(template, site)
		if _copied:
			_append_log(tenant, "Public and private files copied from the template site.")

		# -- site configuration ------------------------------------------
		plan = get_plan_by_identifier(tenant_doc.plan)
		limits = get_plan_limits(plan) if plan else {}
		template_config = get_site_config(template)
		updates = {
			"saas_tenant": tenant_doc.name,
			"saas_tenant_name": tenant_doc.tenant_name,
			"saas_tenant_admin": tenant_doc.admin_email,
			"saas_plan": tenant_doc.plan,
			"saas_subdomain": subdomain,
			"saas_central_url": get_central_url(),
			"saas_site_url": get_site_url(subdomain),
			"saas_suspended": 0,
			"saas_max_users": limits.get("max_users", 0),
			"saas_max_branches": limits.get("max_branches", 0),
			"saas_max_companies": limits.get("max_companies", 0),
			"saas_storage_gb": limits.get("storage_gb", 0),
			"host_name": get_site_url(subdomain),
			"pause_scheduler": 0 if cint(settings.run_scheduler) else 1,
		}
		# Passwords inside the template database were encrypted with the
		# template encryption key.  Preserve it when it exists.
		if template_config.get("encryption_key"):
			updates["encryption_key"] = template_config["encryption_key"]
		config = update_site_config(site, updates)
		tenant_doc.db_set("db_name", config.get("db_name"), update_modified=False)
		if config.get("db_password"):
			tenant_doc.db_password = config.get("db_password")
			tenant_doc.flags.ignore_permissions = True
			tenant_doc.save(ignore_permissions=True)
		frappe.db.commit()
		_append_log(tenant, "Site configuration written (tenant isolation enabled).")

		# -- install the tenant-side client app --------------------------
		output += "\n" + _ensure_client_app(site, tenant, timeout=timeout)

		# -- run the tenant-side setup -----------------------------------
		_append_log(tenant, "Configuring language, branding and admin user.")
		args = json.dumps(
			[
				tenant_doc.name,
				tenant_doc.tenant_name,
				tenant_doc.admin_email,
				tenant_doc.admin_full_name or tenant_doc.tenant_name,
				tenant_doc.currency or "USD",
				tenant_doc.language or "en",
				tenant_doc.country or "",
				password,
				tenant_doc.plan or "",
			]
		)
		result = _bench(
			"--site",
			site,
			"execute",
			"saas_client.setup.setup_tenant_site",
			"--args",
			args,
			timeout=timeout,
		)
		output += "\n" + _check(result, "setup_tenant_site")
		_append_log(tenant, "Tenant defaults configured.")

		# -- administrator password --------------------------------------
		try:
			result = _bench("--site", site, "set-admin-password", password, timeout=300)
			_check(result, "set-admin-password")
		except Exception:
			frappe.log_error(frappe.get_traceback(), "SaaS set-admin-password")

		# -- nginx / hosts / scheduler -----------------------------------
		if cint(settings.setup_nginx):
			_setup_nginx(site, tenant)
		if cint(settings.add_to_hosts):
			_add_to_hosts(site, tenant)
		if cint(settings.run_scheduler):
			try:
				_bench("--site", site, "enable-scheduler", timeout=120)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "SaaS enable-scheduler")

		# -- finish -------------------------------------------------------
		tenant_doc.reload()
		# A paid workspace is active even if it started as a trial; only an
		# unpaid trial keeps the Trial status.
		tenant_doc.status = (
			"Trial" if tenant_doc.trial_ends_on and not cint(tenant_doc.is_paid) else "Active"
		)
		tenant_doc.provisioning_status = "Completed"
		tenant_doc.last_provisioned_on = now_datetime()
		tenant_doc.ssl_status = "Pending" if cint(settings.enable_ssl) else "Not Requested"
		tenant_doc.flags.ignore_permissions = True
		tenant_doc.save(ignore_permissions=True)
		frappe.db.commit()

		_append_log(tenant, f"Provisioning completed. Site URL: {get_site_url(subdomain)}")
		_finish_log(log, "Success", "Provisioning completed.", output, started)
		log_activity(tenant, "Provisioned", f"Site {site} provisioned successfully.")

		if cint(settings.send_credentials_email):
			_send_credentials(tenant_doc, password)

		if cint(settings.enable_ssl):
			enqueue_ssl(tenant)

		return {"ok": True, "site": site, "url": get_site_url(subdomain)}

	except Exception as exc:
		message = str(exc)
		frappe.log_error(frappe.get_traceback(), f"SaaS Provisioning failed: {site}")
		_append_log(tenant, f"Provisioning FAILED: {message}")
		_finish_log(log, "Failed", message, "", started)
		try:
			tenant_doc.reload()
			tenant_doc.status = "Failed"
			tenant_doc.provisioning_status = "Failed"
			tenant_doc.flags.ignore_permissions = True
			tenant_doc.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
		_notify_failure(tenant_doc, message)
		return {"ok": False, "error": message}


# ---------------------------------------------------------------------------
# Provisioning steps
# ---------------------------------------------------------------------------
def _backup_template(template: str, timeout: int = 1800) -> str:
	"""Create and return the path of a fresh template database backup."""
	backup_dir = os.path.join(_site_dir(template), "private", "backups")
	os.makedirs(backup_dir, exist_ok=True)
	before = set(glob.glob(os.path.join(backup_dir, "*-database.sql*")))
	result = _bench("--site", template, "backup", timeout=timeout)
	_check(result, "bench backup")
	candidates = [
		path
		for path in glob.glob(os.path.join(backup_dir, "*-database.sql*"))
		if path not in before and not path.endswith(".tar")
	]
	if not candidates:
		candidates = [
			path
			for path in glob.glob(os.path.join(backup_dir, "*-database.sql*"))
			if not path.endswith(".tar")
		]
	if not candidates:
		raise RuntimeError(f"No database backup found for template site {template}.")
	return max(candidates, key=os.path.getmtime)


def _copy_site_files(template: str, site: str) -> bool:
	"""Copy uploaded files (public and private) from the template site."""
	copied = False
	for relative in ("public/files", "private/files"):
		source = os.path.join(_site_dir(template), relative)
		if not os.path.isdir(source):
			continue
		target = os.path.join(_site_dir(site), relative)
		os.makedirs(os.path.dirname(target), exist_ok=True)
		shutil.copytree(source, target, dirs_exist_ok=True)
		copied = True
	return copied


def _installed_apps(site: str, timeout: int = 300) -> list[str]:
	try:
		result = _bench("--site", site, "list-apps", timeout=timeout)
		if result.returncode != 0:
			return []
		apps = []
		for line in (result.stdout or "").splitlines():
			line = line.strip()
			if not line or line.lower().startswith("apps in"):
				continue
			apps.append(line.split()[0])
		return apps
	except Exception:
		return []


def _ensure_client_app(site: str, tenant: str, timeout: int = 1800) -> str:
	"""Install the lightweight tenant app and drop the legacy platform app.

	Tenant sites only need :mod:`saas_client` (limits, suspension guard and
	first-run setup).  The full SaaS platform app stays on the central site.
	"""
	output = []
	installed = _installed_apps(site, timeout=timeout)

	if LEGACY_TENANT_APP in installed:
		_append_log(tenant, f"Removing legacy {LEGACY_TENANT_APP} app from the tenant site.")
		result = _bench(
			"--site",
			site,
			"uninstall-app",
			LEGACY_TENANT_APP,
			"--yes",
			"--no-backup",
			timeout=timeout,
		)
		if result.returncode == 0:
			output.append(result.stdout or "")
			_append_log(tenant, f"Legacy {LEGACY_TENANT_APP} app removed.")
		else:
			_append_log(
				tenant,
				f"Could not remove legacy {LEGACY_TENANT_APP} app; continuing with {CLIENT_APP}. "
				+ ((result.stderr or result.stdout or "")[-2000:]),
			)
		installed = _installed_apps(site, timeout=timeout)

	if CLIENT_APP not in installed:
		_append_log(tenant, f"Installing {CLIENT_APP} on the tenant site.")
		result = _bench("--site", site, "install-app", CLIENT_APP, timeout=timeout)
		output.append(_check(result, "bench install-app"))
	else:
		_append_log(tenant, f"{CLIENT_APP} is already installed on the tenant site.")

	return "\n".join(part for part in output if part)


def _drop_site(site: str, timeout: int = 900) -> None:
	settings = get_settings()
	_bench(
		"drop-site",
		site,
		"--db-root-username",
		settings.db_root_user or "root",
		"--db-root-password",
		settings.get_password("db_root_password", raise_exception=False) or "",
		"--force",
		"--no-backup",
		timeout=timeout,
	)


def _setup_nginx(site: str, tenant: str) -> None:
	try:
		result = _bench("setup", "nginx", timeout=300)
		if result.returncode != 0:
			_append_log(tenant, "nginx configuration could not be generated automatically; run `bench setup nginx` as root.")
			return
		reload = _run(["systemctl", "reload", "nginx"], timeout=120)
		if reload.returncode != 0:
			_append_log(tenant, "nginx was configured. Reload it with `systemctl reload nginx`.")
		else:
			_append_log(tenant, "nginx configuration generated and reloaded.")
	except Exception:
		_append_log(tenant, "nginx setup skipped (requires root). Add the site to your nginx config and reload.")
		frappe.log_error(frappe.get_traceback(), "SaaS nginx setup")


def _add_to_hosts(site: str, tenant: str) -> None:
	try:
		if os.geteuid() != 0:
			_append_log(tenant, f"Add `127.0.0.1 {site}` to /etc/hosts (or configure wildcard DNS).")
			return
		with open("/etc/hosts") as fh:
			content = fh.read()
		if site in content.split():
			return
		with open("/etc/hosts", "a") as fh:
			fh.write(f"\n127.0.0.1 {site}\n")
		_append_log(tenant, f"Added {site} to /etc/hosts.")
	except Exception:
		_append_log(tenant, f"Could not update /etc/hosts automatically. Add `127.0.0.1 {site}` manually.")
		frappe.log_error(frappe.get_traceback(), "SaaS hosts setup")


def _send_credentials(tenant_doc, password: str) -> None:
	try:
		if not tenant_doc.admin_email:
			return
		url = get_site_url(tenant_doc.subdomain)
		message = f"""
			<div style="font-family:Inter,Arial,sans-serif;line-height:1.6">
				<h2>Your Sahbix workspace is ready</h2>
				<p>Hello {frappe.utils.escape_html(tenant_doc.admin_full_name or tenant_doc.tenant_name)},</p>
				<p>Your workspace <b>{frappe.utils.escape_html(tenant_doc.tenant_name)}</b> is live.</p>
				<ul>
					<li><b>Login URL:</b> <a href="{url}/login">{url}/login</a></li>
					<li><b>Email:</b> {frappe.utils.escape_html(tenant_doc.admin_email)}</li>
					<li><b>Temporary password:</b> {frappe.utils.escape_html(password)}</li>
				</ul>
				<p>Please sign in and change your password from your profile.</p>
			</div>
		"""
		frappe.sendmail(
			recipients=[tenant_doc.admin_email],
			subject=_("Your workspace is ready — {0}").format(tenant_doc.tenant_name),
			message=message,
			now=False,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS credentials email")


def _notify_failure(tenant_doc, message: str) -> None:
	try:
		settings = get_settings()
		recipients = [settings.support_email] if settings.support_email else []
		if tenant_doc.admin_email:
			recipients.append(tenant_doc.admin_email)
		if recipients:
			frappe.sendmail(
				recipients=list(dict.fromkeys(recipients)),
				subject=_("Workspace provisioning failed: {0}").format(tenant_doc.tenant_name),
				message=f"<p>Provisioning for <b>{frappe.utils.escape_html(tenant_doc.name)}</b> failed.</p><pre>{frappe.utils.escape_html(message[:4000])}</pre>",
				now=False,
			)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS provisioning failure email")


# ---------------------------------------------------------------------------
# Tenant side setup (executed on the tenant site)
# ---------------------------------------------------------------------------
def setup_tenant_site(
	tenant_name: str,
	company_name: str | None = None,
	admin_email: str | None = None,
	admin_full_name: str | None = None,
	currency: str | None = None,
	language: str = "en",
	country: str | None = None,
	admin_password: str | None = None,
	plan: str | None = None,
):
	"""Configure a freshly cloned tenant site.

	This function is executed *on the tenant site* via ``bench execute``.
	"""
	company_name = (company_name or tenant_name or "").strip()
	language = language if language in ("en", "ar") else "en"
	currency = (currency or "USD").upper()

	# System settings -------------------------------------------------------
	_set_single("System Settings", "language", language)
	if country and frappe.db.exists("Country", country):
		_set_single("System Settings", "country", country)
		_set_single("Global Defaults", "country", country)
	_set_single("System Settings", "app_name", company_name)
	_set_single("System Settings", "allow_login_using_user_name", 1)
	_set_single("System Settings", "disable_signup", 1)

	# Website settings ------------------------------------------------------
	_set_single("Website Settings", "app_name", company_name)
	_set_single("Website Settings", "disable_signup", 1)
	_set_single("Website Settings", "hide_footer", 1)

	# Currency --------------------------------------------------------------
	if frappe.db.exists("Currency", currency):
		if not frappe.db.get_value("Currency", currency, "enabled"):
			frappe.db.set_value("Currency", currency, "enabled", 1)
		_set_single("Global Defaults", "default_currency", currency)

	# Company ---------------------------------------------------------------
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not company:
		company = _create_company(company_name or tenant_name, currency, country, tenant_name)
	if company:
		_ensure_transit_warehouse(company)
		updates = {"company_name": company_name or company}
		if frappe.db.exists("Currency", currency):
			updates["default_currency"] = currency
		if country and frappe.db.exists("Country", country):
			updates["country"] = country
		try:
			frappe.db.set_value("Company", company, updates, update_modified=False)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "SaaS tenant company update")
		_set_single("Global Defaults", "default_company", company)

		# SaaS custom fields on Company
		for fieldname, value in (("saas_tenant", tenant_name), ("saas_plan", plan)):
			try:
				frappe.db.set_value("Company", company, fieldname, value, update_modified=False)
			except Exception:
				pass

	# Administrator ---------------------------------------------------------
	if admin_email:
		_setup_admin_user(admin_email, admin_full_name or company_name, admin_password, language)

	# Mark this site as a tenant in its own config -------------------------
	update_site_config(
		frappe.local.site,
		{
			"saas_tenant": tenant_name,
			"saas_tenant_name": company_name,
			"saas_plan": plan,
			"saas_suspended": 0,
		},
	)

	frappe.db.commit()
	frappe.clear_cache()
	return {"ok": True, "site": frappe.local.site, "company": company}


def _ensure_warehouse_type() -> None:
	"""Make sure the Transit warehouse type exists (needed by Company)."""
	if frappe.db.exists("Warehouse Type", "Transit"):
		return
	try:
		frappe.get_doc(
			{
				"doctype": "Warehouse Type",
				"__newname": "Transit",
				"description": "Goods in transit",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS tenant warehouse type")


def _ensure_transit_warehouse(company: str) -> None:
	"""Create the standard 'Goods In Transit' warehouse when it is missing."""
	if frappe.db.exists("Warehouse", {"company": company, "warehouse_type": "Transit"}):
		return
	_ensure_warehouse_type()
	parent = frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 1}, "name", order_by="lft asc"
	)
	try:
		warehouse = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": _("Goods In Transit"),
				"company": company,
				"warehouse_type": "Transit",
				"parent_warehouse": parent,
			}
		)
		warehouse.flags.ignore_permissions = True
		warehouse.flags.ignore_mandatory = True
		warehouse.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS tenant transit warehouse")


def _create_company(
	company_name: str,
	currency: str,
	country: str | None = None,
	tenant_name: str | None = None,
) -> str | None:
	"""Create the first company with a standard chart of accounts.

	The template site may have no company at all (a fresh ERPNext install).
	Without a company most ERPNext features are unusable, so tenants always get
	one that matches their currency and country.
	"""
	company_name = (company_name or tenant_name or "Company").strip() or "Company"

	resolved_country = None
	if country and frappe.db.exists("Country", country):
		resolved_country = country
	if not resolved_country:
		for candidate in ("Saudi Arabia", "United Arab Emirates", "Yemen", "United States"):
			if frappe.db.exists("Country", candidate):
				resolved_country = candidate
				break
	if not resolved_country:
		resolved_country = frappe.db.get_value("Country", {}, "name")

	ascii_part = "".join(
		ch for ch in (tenant_name or company_name) if ch.isascii() and ch.isalnum()
	)
	abbr = (ascii_part[:5] or "CO").upper()

	# A fresh ERPNext install has no Warehouse Type records, but company
	# creation always creates a "Transit" warehouse.
	_ensure_warehouse_type()

	try:
		company = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": company_name,
				"abbr": abbr,
				"default_currency": currency,
				"country": resolved_country,
				"chart_of_accounts": "Standard",
				"create_chart_of_accounts_based_on": "Standard Template",
			}
		)
		company.flags.ignore_permissions = True
		company.insert(ignore_permissions=True)
		frappe.db.commit()
		return company.name
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS tenant company creation")
		return None


def _set_single(doctype: str, field: str, value) -> None:
	try:
		frappe.db.set_single_value(doctype, field, value, update_modified=False)
	except Exception:
		pass


def _setup_admin_user(email: str, full_name: str, password: str | None, language: str) -> None:
	email = email.strip().lower()
	if not email:
		return
	parts = (full_name or email).split(" ", 1)
	first_name = parts[0]
	last_name = parts[1] if len(parts) > 1 else ""

	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.new_doc("User")
		user.email = email
		user.send_welcome_email = 0

	user.first_name = first_name
	user.last_name = last_name
	user.enabled = 1
	user.user_type = "System User"
	user.language = language
	if password:
		user.new_password = password
	user.flags.ignore_permissions = True
	user.flags.no_welcome_mail = True
	user.save(ignore_permissions=True)
	roles = ["Academics User", "Accounts Manager", "Accounts User", "Agriculture Manager", "Agriculture User", "Auditor", "Blogger", "Customer", "Dashboard Manager", "Delivery Manager", "Delivery User", "Fleet Manager", "Fulfillment User", "HR Manager", "HR User", "Inbox User", "Item Manager", "Knowledge Base Contributor", "Knowledge Base Editor", "Maintenance Manager", "Maintenance User", "Manufacturing Manager", "Manufacturing User", "Newsletter Manager", "Prepared Report User", "Projects Manager", "Projects User", "Purchase Manager", "Purchase Master Manager", "Purchase User", "Quality Manager", "Report Manager", "Sales Manager", "Sales Master Manager", "Sales User", "Script Manager", "Stock Manager", "Stock User", "Supplier", "Support Team", "System Manager", "Translator", "Website Manager", "Workspace Manager"]

	for role in roles:
		if frappe.db.exists("Role", role):
			user.add_roles(role)

	# Administrator keeps its own per-tenant password (set by `bench new-site
	# --admin-password` and `bench set-admin-password`).  Keep it enabled so
	# support can always recover a workspace; customers use their own user.
	try:
		frappe.db.set_value("User", "Administrator", "enabled", 1, update_modified=False)
	except Exception:
		pass


# ---------------------------------------------------------------------------
# SSL
# ---------------------------------------------------------------------------
def issue_ssl(tenant: str) -> dict:
	"""Best-effort Let's Encrypt certificate using certbot + nginx."""
	started = time.time()
	tenant_doc = frappe.get_doc("SaaS Tenant", tenant)
	site = tenant_doc.site_name or get_full_site_name(tenant_doc.subdomain)
	log = create_provisioning_log(tenant, site, "SSL")
	settings = get_settings()
	try:
		tenant_doc.db_set("ssl_status", "Pending", update_modified=False)
		frappe.db.commit()
		if not cint(settings.enable_ssl):
			tenant_doc.db_set("ssl_status", "Not Requested", update_modified=False)
			frappe.db.commit()
			_finish_log(log, "Success", "SSL disabled in settings.", started=started)
			return {"ok": True, "message": "SSL disabled."}

		if not shutil.which("certbot"):
			raise RuntimeError(
				"certbot is not installed. Install certbot and run: "
				f"certbot --nginx -d {site} --redirect"
			)
		if os.geteuid() != 0:
			raise RuntimeError(
				"SSL certificates must be issued as root. Run: "
				f"sudo certbot --nginx -d {site} --redirect"
			)

		email = settings.support_email or f"admin@{settings.website_domain or site}"
		result = _run(
			[
				"certbot",
				"--nginx",
				"-d",
				site,
				"--non-interactive",
				"--agree-tos",
				"--email",
				email,
				"--redirect",
			],
			timeout=600,
		)
		output = _check(result, "certbot")
		tenant_doc.db_set("ssl_status", "Issued", update_modified=False)
		frappe.db.commit()
		_finish_log(log, "Success", "Certificate issued.", output, started)
		log_activity(tenant, "SSL issued", site)
		return {"ok": True, "message": "Certificate issued."}
	except Exception as exc:
		message = str(exc)
		tenant_doc.db_set("ssl_status", "Failed", update_modified=False)
		frappe.db.commit()
		_finish_log(log, "Failed", message, "", started)
		return {"ok": False, "error": message}
