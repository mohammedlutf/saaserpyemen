app_name = "saaserpyemen"
app_title = "Sahbix SaaS"
app_publisher = "mohammedlutf"
app_description = "Turn ERPNext into a complete multi-tenant SaaS platform."
app_email = "infosahbix@gmail.com"
app_license = "mit"

# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
app_include_css = "/assets/saaserpyemen/css/saas_desk.css"
app_include_js = "/assets/saaserpyemen/js/saas_desk.js"

web_include_css = "/assets/saaserpyemen/css/saas.css?v=20261106"
web_include_js = "/assets/saaserpyemen/js/saas.js?v=20261101"

# ---------------------------------------------------------------------------
# Website
# ---------------------------------------------------------------------------
home_page = "index"

# Do not map logged-in customers to /dashboard here: Frappe uses
# role_home_page for the "/" route too, which would prevent signed-in users
# from browsing the public marketing pages. The sign-in flow redirects to the
# dashboard explicitly instead.
website_route_rules = [
	{"from_route": "/pricing", "to_route": "plans"},
	{"from_route": "/register", "to_route": "signup"},
]

# ---------------------------------------------------------------------------
# Installation / migrations
# ---------------------------------------------------------------------------
after_install = "saaserpyemen.setup.after_install"
after_migrate = "saaserpyemen.setup.setup_saas"

# ---------------------------------------------------------------------------
# Legacy tenant hooks
# ---------------------------------------------------------------------------
# New tenants run the lightweight `saas_client` app, which owns the request
# guard and the limit hooks.  These entries only act as a fallback for older
# tenant sites that still have the full platform app installed.
before_request = ["saaserpyemen.tenant_ops.before_request"]

# ---------------------------------------------------------------------------
# Limits enforced inside each tenant site (legacy fallback)
# ---------------------------------------------------------------------------
doc_events = {
	"User": {
		"validate": "saaserpyemen.tenant_ops.check_user_limit",
	},
	"Branch": {
		"validate": "saaserpyemen.tenant_ops.check_branch_limit",
	},
	"Company": {
		"validate": "saaserpyemen.tenant_ops.check_company_limit",
	},
	"File": {
		"before_insert": "saaserpyemen.tenant_ops.check_storage_limit",
	},
}

# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------
scheduler_events = {
	"daily": [
		"saaserpyemen.tasks.daily",
	],
	"weekly": [
		"saaserpyemen.tasks.weekly",
	],
	"monthly": [
		"saaserpyemen.tasks.monthly",
	],
}

# ---------------------------------------------------------------------------
# Website routing
# ---------------------------------------------------------------------------
website_path_resolver = ["saaserpyemen.i18n.resolve_website_path"]

# ---------------------------------------------------------------------------
# Jinja helpers
# ---------------------------------------------------------------------------
jinja = {
	"methods": [
		"saaserpyemen.utils.get_settings",
		"saaserpyemen.utils.get_enabled_currencies",
		"saaserpyemen.utils.get_public_plans",
		"saaserpyemen.utils.format_money",
		"saaserpyemen.utils.get_domain",
		"saaserpyemen.utils.get_central_url",
		"saaserpyemen.utils.get_site_url",
		"saaserpyemen.i18n.localized_url",
		"saaserpyemen.i18n.saas_url",
		"saaserpyemen.i18n.switch_language_url",
		"saaserpyemen.i18n.localized_text",
		"saaserpyemen.i18n.status_label",
	]
}

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
# Tenant sites should never be indexed as marketing websites.
website_redirects = []

# Show the app on the apps screen
add_to_apps_screen = [
	{
		"name": "saaserpyemen",
		"logo": "/assets/saaserpyemen/images/logo.svg",
		"title": "Sahbix SaaS",
		"route": "/app/saas-control-center",
		"has_permission": "saaserpyemen.api.has_app_permission",
	}
]
