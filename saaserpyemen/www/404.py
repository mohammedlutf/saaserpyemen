from __future__ import annotations

from frappe import _

from saaserpyemen.website import base_context


def get_context(context):
	base_context(context)
	brand = context.brand_name_ar if context.lang == "ar" else context.brand_name
	context.title = f"{_('Page not found')} — {brand}"
	context.metatags = {
		"description": _("The page you are looking for does not exist or has been moved."),
		"robots": "noindex, nofollow",
	}
	# A 404 must never claim a canonical URL or emit structured data.
	context.seo_canonical = ""
	context.seo_alternates = {}
	context.seo_structured_data = []
