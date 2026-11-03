from __future__ import annotations

import frappe
from frappe.utils import nowdate

from saaserpyemen import seo

no_cache = 1


def get_context(context):
	"""Merge Frappe's sitemap (ecommerce, CMS pages) with bilingual SaaS URLs."""
	from frappe.www.sitemap import get_context as get_default_sitemap

	default = get_default_sitemap(context) or {}
	links = list(default.get("links") or [])

	owned_paths = seo.sitemap_paths() | {"/index", "/index.html"}
	cleaned = []
	seen = set()
	for link in links:
		loc = link.get("loc")
		if not loc:
			continue
		path = seo.url_path(loc)
		if path in owned_paths or loc in seen:
			continue
		seen.add(loc)
		cleaned.append(
			{
				"loc": loc,
				"lastmod": link.get("lastmod"),
				"changefreq": link.get("changefreq"),
				"priority": link.get("priority"),
				"alternates": link.get("alternates") or [],
			}
		)

	cleaned.extend(seo.sitemap_entries(nowdate()))
	return {"links": cleaned}
