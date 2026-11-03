from __future__ import annotations

from frappe import _

from saaserpyemen.website import base_context


def get_context(context):
	base_context(context)
	brand = context.brand_name_ar if context.lang == "ar" else context.brand_name
	context.title = f"{_('About')} {brand} — {_('Technology & Digital Transformation')}"
	context.metatags = {
		"description": _(
			"Learn about {0} — a technology and digital transformation company specializing in ERPNext, Frappe, custom applications, websites and cloud hosting."
		).format(brand),
	}
