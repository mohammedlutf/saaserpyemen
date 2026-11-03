from __future__ import annotations

from frappe.utils import nowdate

from saaserpyemen import seo
from saaserpyemen.website import base_context

sitemap = 1


def get_context(context):
	from frappe import _

	base_context(context)
	context.updated_on = nowdate()
	brand = context.brand_name_ar if context.lang == "ar" else context.brand_name
	context.title = f"{_('Terms of Service')} — {brand}"
	description = _("The terms that govern your use of the {0} cloud ERP platform.").format(brand)
	context.metatags = {"description": description}
	context.seo_og_type = "article"
	seo.add_structured_data(
		context,
		{
			"@context": "https://schema.org",
			"@type": "WebPage",
			"name": context.title,
			"description": description,
			"url": seo.canonical_url(lang=context.lang),
			"inLanguage": context.lang,
			"isPartOf": {"@id": seo.absolute_url(seo.WEBSITE_ID)},
		},
		seo.breadcrumbs_for("/terms", _("Terms of Service"), context.lang),
	)
