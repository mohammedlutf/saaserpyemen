from __future__ import annotations

from frappe import _

from saaserpyemen import seo
from saaserpyemen.website import base_context

sitemap = 1


def get_context(context):
	base_context(context)
	brand = context.brand_name_ar if context.lang == "ar" else context.brand_name
	context.title = f"{_('About')} {brand} — {_('Technology & Digital Transformation')}"
	description = _(
		"Learn about {0} — a technology and digital transformation company specializing in ERPNext, Frappe, custom applications, websites and cloud hosting."
	).format(brand)
	context.metatags = {
		"description": description,
		"keywords": _(
			"ERPNext Yemen, Frappe development, digital transformation Yemen, custom software Middle East, cloud hosting Yemen, business automation"
		),
	}
	context.seo_og_type = "website"

	about_page = {
		"@context": "https://schema.org",
		"@type": "AboutPage",
		"name": context.title,
		"description": description,
		"url": seo.canonical_url(lang=context.lang),
		"inLanguage": context.lang,
		"isPartOf": {"@id": seo.absolute_url(seo.WEBSITE_ID)},
		"about": {"@id": seo.absolute_url(seo.ORGANIZATION_ID)},
	}
	seo.add_structured_data(
		context,
		about_page,
		seo.breadcrumbs_for("/about", _("About us"), context.lang),
	)
