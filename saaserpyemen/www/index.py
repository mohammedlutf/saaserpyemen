from __future__ import annotations

from saaserpyemen import seo
from saaserpyemen.utils import get_settings
from saaserpyemen.website import base_context, plans_context

sitemap = 1


def _home_faq(context) -> list[dict]:
	from frappe import _

	domain = context.domain or "sahbix.com"
	return [
		{
			"question": _("What exactly do I get?"),
			"answer": _(
				"Your own private ERPNext site at yourname.{0}, with a dedicated database, secure file storage, automatic backups, and the full ERPNext suite: accounting, sales, purchasing, inventory, HR, CRM, projects and more."
			).format(domain),
		},
		{
			"question": _("Is the free trial really free?"),
			"answer": _(
				"Yes. You get {0} days of full access with no credit card. At the end of the trial you can pay manually by bank transfer to keep your workspace active."
			).format(context.trial_days),
		},
		{
			"question": _("How does payment work?"),
			"answer": _(
				"We support manual bank transfers. After transferring, upload your receipt from your dashboard. Our team reviews it within one business day and extends your subscription."
			),
		},
		{
			"question": _("Can I upgrade or change my plan?"),
			"answer": _(
				"Absolutely. Change your plan at any time from your dashboard. If your current usage fits the new plan, the change is instant."
			),
		},
		{
			"question": _("Is my data isolated and secure?"),
			"answer": _(
				"Every workspace has its own database and file storage. Data is never shared between customers, and we take daily backups."
			),
		},
		{
			"question": _("Can I use my own domain?"),
			"answer": _(
				"Custom domains are available on Business and Enterprise plans. Contact support and we will help you connect it."
			),
		},
	]


def get_context(context):
	from frappe import _

	base_context(context)
	plans_context(context)
	settings = get_settings()
	context.show_pricing = bool(settings.show_pricing)
	context.trial_days = settings.trial_days or 14
	brand = context.brand_name_ar if context.lang == "ar" else context.brand_name
	context.title = f"{brand} — { _('Cloud ERP for growing businesses') }"
	description = _(
		"{0} is a cloud ERP platform for businesses in Yemen, the Middle East and around the world — accounting, sales, inventory, HR and more."
	).format(brand)
	context.metatags = {
		"description": description,
		"keywords": _(
			"ERP Yemen, ERPNext Yemen, cloud ERP Middle East, Arabic ERP, accounting software Yemen, inventory management, HR software, SaaS ERP"
		),
	}

	offers = []
	if context.show_pricing and context.plans:
		offer = seo.aggregate_offer(
			context.currency,
			[plan.get("monthly") for plan in context.plans],
			url=seo.localized_absolute("/plans", context.lang),
		)
		if offer:
			offers = [offer]

	seo.add_structured_data(
		context,
		seo.software_application_schema(context, description, offers),
		seo.faq_schema(_home_faq(context)) if settings.show_faq else None,
	)
