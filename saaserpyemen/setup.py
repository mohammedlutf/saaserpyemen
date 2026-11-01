# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt

from saaserpyemen.utils import (
	get_enabled_currencies,
	get_settings,
	is_central_site,
	round_price,
)


PLAN_SEED = [
	{
		"plan_name": "Starter",
		"slug": "starter",
		"sort_order": 10,
		"is_featured": 0,
		"color": "#0ea5e9",
		"icon": "rocket",
		"tagline_en": "For new businesses finding their feet.",
		"tagline_ar": "للشركات الناشئة التي تبدأ رحلتها.",
		"description_en": "Everything you need to start selling, invoicing and organising your team.",
		"description_ar": "كل ما تحتاجه لبدء البيع والفوترة وتنظيم فريقك.",
		"monthly": 19,
		"yearly": 190,
		"max_users": 3,
		"max_branches": 1,
		"max_companies": 1,
		"storage_gb": 5,
		"features": [
			("Up to 3 users", "حتى 3 مستخدمين", 1, "users"),
			("1 branch", "فرع واحد", 1, "building"),
			("5 GB secure storage", "5 جيجابايت مساحة آمنة", 1, "database"),
			("Full ERPNext suite", "حزمة ERPNext الكاملة", 1, "grid"),
			("Arabic & English interface", "واجهة عربية وإنجليزية", 1, "globe"),
			("Email support", "دعم بالبريد الإلكتروني", 1, "headphones"),
		],
	},
	{
		"plan_name": "Growth",
		"slug": "growth",
		"sort_order": 20,
		"is_featured": 1,
		"color": "#0d9488",
		"icon": "trending-up",
		"tagline_en": "The sweet spot for growing teams.",
		"tagline_ar": "الخيار الأمثل للفرق النامية.",
		"description_en": "More users, more branches and the tools to scale without friction.",
		"description_ar": "مستخدمون وفروع أكثر وأدوات للتوسع بسهولة.",
		"monthly": 49,
		"yearly": 490,
		"max_users": 10,
		"max_branches": 3,
		"max_companies": 2,
		"storage_gb": 25,
		"features": [
			("Up to 10 users", "حتى 10 مستخدمين", 1, "users"),
			("3 branches", "3 فروع", 1, "building"),
			("25 GB secure storage", "25 جيجابايت مساحة آمنة", 1, "database"),
			("Everything in Starter", "كل ما في Starter", 1, "check"),
			("Priority support", "دعم ذو أولوية", 1, "headphones"),
			("Daily automatic backups", "نسخ احتياطي يومي تلقائي", 1, "shield"),
			("Advanced reports", "تقارير متقدمة", 1, "chart"),
		],
	},
	{
		"plan_name": "Business",
		"slug": "business",
		"sort_order": 30,
		"is_featured": 0,
		"color": "#ec4899",
		"icon": "briefcase",
		"tagline_en": "For established operations with real complexity.",
		"tagline_ar": "للعمليات المتقدمة والاحتياجات المعقدة.",
		"description_en": "Granular permissions, more storage and room for every department.",
		"description_ar": "صلاحيات دقيقة ومساحة أكبر لكل الأقسام.",
		"monthly": 99,
		"yearly": 990,
		"max_users": 25,
		"max_branches": 10,
		"max_companies": 5,
		"storage_gb": 100,
		"features": [
			("Up to 25 users", "حتى 25 مستخدمًا", 1, "users"),
			("10 branches", "10 فروع", 1, "building"),
			("100 GB secure storage", "100 جيجابايت مساحة آمنة", 1, "database"),
			("Everything in Growth", "كل ما في Growth", 1, "check"),
			("Advanced roles & permissions", "أدوار وصلاحيات متقدمة", 1, "lock"),
			("Multi-company accounting", "محاسبة متعددة الشركات", 1, "layers"),
			("Phone & chat support", "دعم هاتفي ومحادثة", 1, "phone"),
			("Onboarding session", "جلسة تهيئة", 1, "graduation"),
		],
	},
	{
		"plan_name": "Enterprise",
		"slug": "enterprise",
		"sort_order": 40,
		"is_featured": 0,
		"color": "#f59e0b",
		"icon": "crown",
		"tagline_en": "Unlimited scale with a dedicated team.",
		"tagline_ar": "توسع بلا حدود مع فريق مخصص.",
		"description_en": "Unlimited users and branches, a dedicated environment and SLA support.",
		"description_ar": "مستخدمون وفروع بلا حدود وبيئة مخصصة ودعم باتفاقية مستوى خدمة.",
		"monthly": 199,
		"yearly": 1990,
		"max_users": 0,
		"max_branches": 0,
		"max_companies": 0,
		"storage_gb": 500,
		"features": [
			("Unlimited users", "مستخدمون بلا حدود", 1, "users"),
			("Unlimited branches", "فروع بلا حدود", 1, "building"),
			("500 GB secure storage", "500 جيجابايت مساحة آمنة", 1, "database"),
			("Everything in Business", "كل ما في Business", 1, "check"),
			("Dedicated onboarding", "تهيئة مخصصة", 1, "graduation"),
			("SLA & account manager", "اتفاقية خدمة ومدير حساب", 1, "award"),
			("Custom integrations", "تكاملات مخصصة", 1, "plug"),
			("Priority infrastructure", "بنية تحتية ذات أولوية", 1, "server"),
		],
	},
]

FALLBACK_RATES = {
	"USD": 1.0,
	"SAR": 3.75,
	"AED": 3.67,
	"EGP": 48.5,
	"EUR": 0.92,
	"GBP": 0.79,
	"YER": 250.0,
	"KWD": 0.31,
	"QAR": 3.64,
	"OMR": 0.385,
	"JOD": 0.71,
	"TRY": 34.0,
	"INR": 83.5,
}


def after_install():
	setup_saas()


def setup_saas():
	create_roles()
	create_custom_fields_for_saas()
	if is_central_site():
		ensure_settings()
		seed_default_plans()
		set_portal_defaults()
		sync_google_login()
	frappe.clear_cache()


def create_roles():
	roles = [
		{"role_name": "SaaS Manager", "desk_access": 1, "description": "Manages tenants, plans and billing."},
		{"role_name": "SaaS Customer", "desk_access": 0, "description": "Customer portal access only."},
	]
	for role in roles:
		if frappe.db.exists("Role", role["role_name"]):
			continue
		frappe.get_doc({"doctype": "Role", **role}).insert(ignore_permissions=True)


def create_custom_fields_for_saas():
	custom_fields = {
		"User": [
			{
				"fieldname": "saas_section",
				"fieldtype": "Section Break",
				"label": "SaaS",
				"insert_after": "email",
				"collapsible": 1,
			},
			{
				"fieldname": "saas_company_name",
				"fieldtype": "Data",
				"label": "Company Name (SaaS)",
				"insert_after": "saas_section",
				"no_copy": 1,
			},
			{
				"fieldname": "saas_phone",
				"fieldtype": "Data",
				"label": "Phone (SaaS)",
				"insert_after": "saas_company_name",
				"no_copy": 1,
			},
			{
				"fieldname": "saas_country",
				"fieldtype": "Link",
				"label": "Country (SaaS)",
				"options": "Country",
				"insert_after": "saas_phone",
				"no_copy": 1,
			},
			{
				"fieldname": "saas_preferred_language",
				"fieldtype": "Select",
				"label": "Preferred Language",
				"options": "en\nar",
				"insert_after": "saas_country",
				"no_copy": 1,
			},
			{
				"fieldname": "saas_signup_source",
				"fieldtype": "Select",
				"label": "Signup Source",
				"options": "Email\nGoogle\nDesk\nAPI",
				"insert_after": "saas_preferred_language",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "saas_tenant",
				"fieldtype": "Link",
				"label": "SaaS Tenant",
				"options": "SaaS Tenant",
				"insert_after": "saas_signup_source",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "saas_is_tenant_admin",
				"fieldtype": "Check",
				"label": "Tenant Admin",
				"insert_after": "saas_tenant",
				"read_only": 1,
				"no_copy": 1,
			},
		],
		"Item": [
			{
				"fieldname": "saas_service_item",
				"fieldtype": "Check",
				"label": "SaaS Service Item",
				"insert_after": "is_sales_item",
				"read_only": 1,
				"hidden": 1,
				"no_copy": 1,
			}
		],
		"Company": [
			{
				"fieldname": "saas_tenant",
				"fieldtype": "Link",
				"label": "SaaS Tenant",
				"options": "SaaS Tenant",
				"insert_after": "company_name",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "saas_plan",
				"fieldtype": "Link",
				"label": "SaaS Plan",
				"options": "SaaS Plan",
				"insert_after": "saas_tenant",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "saas_subscription_end",
				"fieldtype": "Date",
				"label": "Subscription Ends On",
				"insert_after": "saas_plan",
				"read_only": 1,
				"no_copy": 1,
			},
		],
		"Branch": [
			{
				"fieldname": "saas_tenant",
				"fieldtype": "Link",
				"label": "SaaS Tenant",
				"options": "SaaS Tenant",
				"insert_after": "branch",
				"read_only": 1,
				"no_copy": 1,
			}
		],
		"Customer": [
			{
				"fieldname": "saas_tenant",
				"fieldtype": "Link",
				"label": "SaaS Tenant",
				"options": "SaaS Tenant",
				"insert_after": "customer_name",
				"read_only": 1,
				"no_copy": 1,
			}
		],
		"Sales Invoice": [
			{
				"fieldname": "saas_section",
				"fieldtype": "Section Break",
				"label": "SaaS Billing",
				"insert_after": "customer",
				"collapsible": 1,
			},
			{
				"fieldname": "saas_tenant",
				"fieldtype": "Link",
				"label": "SaaS Tenant",
				"options": "SaaS Tenant",
				"insert_after": "saas_section",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "saas_subscription",
				"fieldtype": "Link",
				"label": "SaaS Subscription",
				"options": "SaaS Subscription",
				"insert_after": "saas_tenant",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "saas_payment",
				"fieldtype": "Link",
				"label": "SaaS Payment",
				"options": "SaaS Payment",
				"insert_after": "saas_subscription",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "saas_period_start",
				"fieldtype": "Date",
				"label": "SaaS Period Start",
				"insert_after": "saas_payment",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "saas_period_end",
				"fieldtype": "Date",
				"label": "SaaS Period End",
				"insert_after": "saas_period_start",
				"read_only": 1,
				"no_copy": 1,
			},
		],
	}
	create_custom_fields(custom_fields, ignore_validate=True)


def _existing_link(doctype, name):
	"""Return ``name`` only when the linked record actually exists."""
	if not name:
		return None
	try:
		return name if frappe.db.exists(doctype, name) else None
	except Exception:
		return None


def ensure_settings():
	settings = frappe.get_single("SaaS Settings")
	changed = False

	customer_group = (
		settings.default_customer_group
		or frappe.db.get_single_value("Selling Settings", "customer_group")
		or "All Customer Groups"
	)
	territory = (
		settings.default_territory
		or frappe.db.get_single_value("Selling Settings", "territory")
		or "All Territories"
	)

	defaults = {
		"central_site": frappe.local.site,
		"website_domain": settings.website_domain or "shopzadmarket.com",
		"support_email": settings.support_email or "infosahbix@gmail.com",
		"support_phone": settings.support_phone or "+957770785816",
		"template_site": settings.template_site or "saas-default.com",
		"sites_path": settings.sites_path or (frappe.utils.get_bench_path() + "/sites"),
		"bench_path": settings.bench_path or frappe.utils.get_bench_path(),
		"bench_command": settings.bench_command or "bench",
		"site_scheme": settings.site_scheme or "http",
		"db_root_user": settings.db_root_user or "root",
		"run_scheduler": 1,
		"send_credentials_email": 1,
		"install_app_on_tenant": 1,
		"create_sales_invoice": 1,
		"auto_suspend_on_expiry": 1,
		"send_expiry_reminders": 1,
		"invoice_due_days": settings.invoice_due_days or 7,
		"signup_rate_limit": settings.signup_rate_limit or 20,
		"min_password_length": settings.min_password_length or 8,
		"max_tenants_per_user": cint(settings.max_tenants_per_user),
		"company": settings.company or frappe.defaults.get_default_value("company"),
		"default_customer_group": _existing_link("Customer Group", customer_group),
		"default_territory": _existing_link("Territory", territory),
		"hero_subtitle_en": settings.hero_subtitle_en
		or "Sahbix gives you a complete, secure ERPNext workspace for accounting, sales, purchasing, inventory, HR and more — live in minutes.",
		"hero_subtitle_ar": settings.hero_subtitle_ar
		or "سحبيكس يمنحك مساحة عمل ERPNext كاملة وآمنة للمحاسبة والمبيعات والمشتريات والمخزون والموارد البشرية والمزيد — جاهزة في دقائق.",
		"footer_about_en": settings.footer_about_en
		or "The all-in-one cloud ERP platform for ambitious businesses in the Middle East and beyond.",
		"footer_about_ar": settings.footer_about_ar
		or "منصة ERP السحابية الشاملة للشركات الطموحة في الشرق الأوسط وخارجه.",
		"bank_details": settings.bank_details
		or "<p><strong>Bank transfer</strong><br>Bank: Your Bank Name<br>Account name: Sahbix<br>IBAN: YOUR-IBAN-HERE<br>Reference: your subdomain</p>",
		"bank_details_ar": settings.bank_details_ar
		or "<p><strong>تحويل بنكي</strong><br>البنك: اسم البنك<br>اسم الحساب: سحبيكس<br>IBAN: YOUR-IBAN-HERE<br>المرجع: النطاق الفرعي الخاص بك</p>",
		"payment_note_en": settings.payment_note_en
		or "After transferring, upload your receipt. Our team reviews manual payments within one business day.",
		"payment_note_ar": settings.payment_note_ar
		or "بعد التحويل، ارفع إيصال الدفع. يراجع فريقنا المدفوعات اليدوية خلال يوم عمل واحد.",
	}

	for key, value in defaults.items():
		if not settings.get(key) and value:
			settings.set(key, value)
			changed = True

	if not settings.get_password("db_root_password", raise_exception=False):
		settings.db_root_password = "123"
		changed = True

	if changed or settings.is_new():
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)


def seed_default_plans():
	if frappe.db.count("SaaS Plan"):
		return

	currencies = {row["name"] for row in get_enabled_currencies()}
	if "USD" not in currencies:
		currencies.add("USD")

	for spec in PLAN_SEED:
		plan = frappe.new_doc("SaaS Plan")
		plan.update(
			{
				"enabled": 1,
				"plan_name": spec["plan_name"],
				"slug": spec["slug"],
				"sort_order": spec["sort_order"],
				"is_featured": spec["is_featured"],
				"color": spec["color"],
				"icon": spec["icon"],
				"tagline_en": spec["tagline_en"],
				"tagline_ar": spec["tagline_ar"],
				"description_en": spec["description_en"],
				"description_ar": spec["description_ar"],
				"currency": "USD",
				"monthly_price": spec["monthly"],
				"yearly_price": spec["yearly"],
				"trial_days": 30,
				"max_users": spec["max_users"],
				"max_branches": spec["max_branches"],
				"max_companies": spec["max_companies"],
				"storage_gb": spec["storage_gb"],
			}
		)

		for index, (en, ar, included, icon) in enumerate(spec["features"]):
			plan.append(
				"features",
				{
					"feature_en": en,
					"feature_ar": ar,
					"included": included,
					"icon": icon,
					"sort_order": index,
				},
			)

		for currency in sorted(currencies):
			if currency == "USD":
				monthly = spec["monthly"]
				yearly = spec["yearly"]
			else:
				rate = FALLBACK_RATES.get(currency)
				if not rate:
					rate = 1.0
				monthly = round_price(spec["monthly"] * rate, currency)
				yearly = round_price(spec["yearly"] * rate, currency)
			plan.append(
				"prices",
				{
					"currency": currency,
					"monthly_price": monthly,
					"yearly_price": yearly,
				},
			)

		plan.flags.ignore_permissions = True
		plan.insert(ignore_permissions=True)


def set_portal_defaults():
	try:
		portal = frappe.get_single("Portal Settings")
		if not portal.default_role:
			portal.default_role = "SaaS Customer"
			portal.flags.ignore_permissions = True
			portal.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS Portal Settings")

	try:
		system = frappe.get_single("System Settings")
		if not cint(system.allow_login_using_user_name):
			system.allow_login_using_user_name = 1
			system.flags.ignore_permissions = True
			system.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS System Settings")

	try:
		website = frappe.get_single("Website Settings")
		if cint(website.disable_signup):
			website.disable_signup = 0
		if not website.app_name:
			website.app_name = "Sahbix"
		website.flags.ignore_permissions = True
		website.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SaaS Website Settings")


def sync_google_login():
	"""Create or update the Google Social Login Key from SaaS Settings."""
	settings = get_settings()
	exists = frappe.db.exists("Social Login Key", "google")

	if not cint(settings.enable_google_login):
		if exists:
			doc = frappe.get_doc("Social Login Key", "google")
			doc.enable_social_login = 0
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
		return

	client_id = (settings.google_client_id or "").strip()
	client_secret = settings.get_password("google_client_secret", raise_exception=False)
	if not client_id or not client_secret:
		return

	doc = frappe.get_doc("Social Login Key", "google") if exists else frappe.new_doc("Social Login Key")
	if not exists:
		doc.name = "google"
	doc.provider_name = "Google"
	doc.social_login_provider = "Google"
	doc.enable_social_login = 1
	doc.client_id = client_id
	doc.client_secret = client_secret
	doc.base_url = "https://www.googleapis.com"
	doc.custom_base_url = 0
	doc.authorize_url = "https://accounts.google.com/o/oauth2/auth"
	doc.access_token_url = "https://accounts.google.com/o/oauth2/token"
	doc.redirect_url = (
		settings.google_redirect_uri or "/api/method/frappe.integrations.oauth2_logins.login_via_google"
	)
	doc.api_endpoint = "oauth2/v2/userinfo"
	doc.api_endpoint_args = None
	doc.auth_url_data = json.dumps(
		{
			"scope": "https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/userinfo.email",
			"response_type": "code",
		}
	)
	doc.sign_ups = "Allow" if cint(settings.allow_google_signup) else "Deny"
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
