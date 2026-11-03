# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt
"""Central SEO helpers for the Sahbix public website.

Everything the templates need for canonical URLs, hreflang alternates,
Open Graph/Twitter cards, JSON-LD structured data and the bilingual
sitemap lives here so individual pages only describe their own content.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import frappe
from frappe.utils import get_url, nowdate

from saaserpyemen.i18n import DEFAULT_LANGUAGE, _extract_lang_from_path, localized_url
from saaserpyemen.utils import get_settings

SEO_LANGUAGES = ("en", "ar")
DEFAULT_ROBOTS = "index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1"
PRIVATE_ROBOTS = "noindex, nofollow"
ORGANIZATION_ID = "/#organization"
WEBSITE_ID = "/#website"

# Intrinsic logo sizes (px) so social crawlers can reserve the right aspect ratio.
LOGO_DIMENSIONS = {"en": (993, 251), "ar": (994, 251)}

# Public, indexable marketing pages. `path` is language-neutral.
PUBLIC_PAGES = (
	{"path": "/", "changefreq": "weekly", "priority": "1.0"},
	{"path": "/plans", "changefreq": "weekly", "priority": "0.9"},
	{"path": "/about", "changefreq": "monthly", "priority": "0.8"},
	{"path": "/signup", "changefreq": "monthly", "priority": "0.7"},
	{"path": "/terms", "changefreq": "yearly", "priority": "0.4"},
	{"path": "/privacy", "changefreq": "yearly", "priority": "0.4"},
)

# Duplicate routes configured in hooks.py should canonicalise to the real page.
PATH_ALIASES = {"/pricing": "/plans", "/register": "/signup"}


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
def absolute_url(path: str = "/") -> str:
	"""Return an absolute URL on the current (production) host."""
	path = "" if path is None else str(path)
	if path.startswith(("http://", "https://")):
		return path.rstrip("/")
	base = (get_url() or "").rstrip("/")
	if not path:
		path = "/"
	if not path.startswith("/"):
		path = "/" + path
	return f"{base}{path}"


def _request_path() -> str:
	try:
		request = getattr(frappe.local, "request", None)
		if request is None:
			return "/"
		path = getattr(request, "full_path", None) or getattr(request, "path", "/") or "/"
	except Exception:
		path = "/"
	path = str(path).split("?", 1)[0].split("#", 1)[0]
	if not path.startswith("/"):
		path = "/" + path
	return path


def current_language() -> str:
	lang = getattr(frappe.local, "lang", None) or getattr(frappe.local.flags, "saas_lang", None)
	return "ar" if str(lang or "").lower().startswith("ar") else DEFAULT_LANGUAGE


def current_path() -> str:
	"""Language-neutral path of the current request (no /ar prefix, no query)."""
	path = getattr(frappe.local.flags, "saas_path", None)
	if path:
		path = str(path).split("?", 1)[0].split("#", 1)[0]
		if not path.startswith("/"):
			path = "/" + path
	else:
		_, path = _extract_lang_from_path(_request_path())
	path = path or "/"
	if path in ("/index", "/index.html"):
		path = "/"
	path = PATH_ALIASES.get(path, path)
	if path != "/":
		path = path.rstrip("/") or "/"
	return path


def canonical_url(path: str | None = None, lang: str | None = None) -> str:
	path = current_path() if path is None else path
	lang = lang or current_language()
	return absolute_url(localized_url(path, lang))


def alternate_urls(path: str | None = None) -> dict[str, str]:
	path = current_path() if path is None else path
	urls = {lang: absolute_url(localized_url(path, lang)) for lang in SEO_LANGUAGES}
	urls["x-default"] = urls[DEFAULT_LANGUAGE]
	return urls


def localized_absolute(path: str, lang: str | None = None) -> str:
	return absolute_url(localized_url(path, lang or current_language()))


# ---------------------------------------------------------------------------
# Structured data
# ---------------------------------------------------------------------------
def _clean(data):
	"""Drop empty values recursively so JSON-LD stays tidy."""
	if isinstance(data, dict):
		cleaned = {}
		for key, value in data.items():
			value = _clean(value)
			if value not in (None, "", [], {}):
				cleaned[key] = value
		return cleaned
	if isinstance(data, list):
		return [_clean(item) for item in data if _clean(item) not in (None, "", [], {})]
	return data


def _brand(lang: str | None = None) -> str:
	settings = get_settings()
	if (lang or current_language()) == "ar":
		return settings.brand_name_ar or "سحبيكس"
	return settings.brand_name or "Sahbix"


def _logo_url(lang: str | None = None) -> str:
	if (lang or current_language()) == "ar":
		return absolute_url("/assets/saaserpyemen/images/rtlhorizontallogo.png")
	return absolute_url("/assets/saaserpyemen/images/ltlhorizontallogo.png")


def _social_urls() -> list[str]:
	settings = get_settings()
	values = [
		settings.get("twitter_url"),
		settings.get("linkedin_url"),
		settings.get("instagram_url"),
		settings.get("facebook_url"),
	]
	return [value.strip() for value in values if value and str(value).strip()]


def organization_schema() -> dict:
	settings = get_settings()
	data = {
		"@context": "https://schema.org",
		"@type": "Organization",
		"@id": absolute_url(ORGANIZATION_ID),
		"name": settings.brand_name or "Sahbix",
		"alternateName": settings.brand_name_ar or "سحبيكس",
		"url": absolute_url("/"),
		"logo": absolute_url("/assets/saaserpyemen/images/favicon-square.png"),
		"image": _logo_url("en"),
		"email": settings.support_email,
		"telephone": settings.support_phone,
		"sameAs": _social_urls(),
	}
	if settings.support_email or settings.support_phone:
		data["contactPoint"] = {
			"@type": "ContactPoint",
			"contactType": "customer support",
			"email": settings.support_email,
			"telephone": settings.support_phone,
			"availableLanguage": ["English", "Arabic"],
		}
	if settings.get("address"):
		data["address"] = settings.get("address")
	return _clean(data)


def website_schema(lang: str | None = None) -> dict:
	lang = lang or current_language()
	return _clean(
		{
			"@context": "https://schema.org",
			"@type": "WebSite",
			"@id": absolute_url(WEBSITE_ID),
			"url": absolute_url(localized_url("/", lang)),
			"name": _brand(lang),
			"inLanguage": lang,
			"publisher": {"@id": absolute_url(ORGANIZATION_ID)},
		}
	)


def breadcrumb_schema(items: list[dict]) -> dict:
	elements = []
	for index, item in enumerate(items, start=1):
		elements.append(
			_clean(
				{
					"@type": "ListItem",
					"position": index,
					"name": item.get("name"),
					"item": item.get("url"),
				}
			)
		)
	return _clean(
		{
			"@context": "https://schema.org",
			"@type": "BreadcrumbList",
			"itemListElement": elements,
		}
	)


def _breadcrumb_items(lang: str, page_name: str, page_path: str) -> list[dict]:
	from frappe import _

	items = [{"name": _("Home"), "url": localized_absolute("/", lang)}]
	if page_path not in ("", "/"):
		items.append({"name": page_name, "url": localized_absolute(page_path, lang)})
	return items


def breadcrumbs_for(page_path: str, page_name: str, lang: str | None = None) -> dict | None:
	lang = lang or current_language()
	items = _breadcrumb_items(lang, page_name, page_path)
	if len(items) < 2:
		return None
	return breadcrumb_schema(items)


def faq_schema(items: list[dict]) -> dict:
	entities = []
	for item in items:
		question = (item.get("question") or "").strip()
		answer = (item.get("answer") or "").strip()
		if not question or not answer:
			continue
		entities.append(
			_clean(
				{
					"@type": "Question",
					"name": question,
					"acceptedAnswer": {"@type": "Answer", "text": answer},
				}
			)
		)
	return _clean(
		{
			"@context": "https://schema.org",
			"@type": "FAQPage",
			"mainEntity": entities,
		}
	)


def software_application_schema(
	context,
	description: str,
	offers: list[dict] | None = None,
) -> dict:
	lang = getattr(context, "lang", None) or current_language()
	data = {
		"@context": "https://schema.org",
		"@type": "SoftwareApplication",
		"name": _brand(lang),
		"applicationCategory": "BusinessApplication",
		"applicationSubCategory": "ERP",
		"operatingSystem": "Web",
		"url": canonical_url(lang=lang),
		"description": description,
		"inLanguage": lang,
		"publisher": {"@id": absolute_url(ORGANIZATION_ID)},
	}
	if offers:
		data["offers"] = offers
	return _clean(data)


def product_schema(
	context,
	name: str,
	description: str,
	offers: list[dict],
	brand_name: str | None = None,
) -> dict:
	lang = getattr(context, "lang", None) or current_language()
	return _clean(
		{
			"@context": "https://schema.org",
			"@type": "Product",
			"name": name,
			"description": description,
			"brand": {"@type": "Brand", "name": brand_name or _brand(lang)},
			"url": canonical_url(lang=lang),
			"inLanguage": lang,
			"offers": offers,
		}
	)


def aggregate_offer(currency: str, prices: list[float], url: str | None = None) -> dict:
	prices = [float(price) for price in prices if price is not None]
	if not prices:
		return {}
	return _clean(
		{
			"@type": "AggregateOffer",
			"priceCurrency": currency,
			"lowPrice": min(prices),
			"highPrice": max(prices),
			"offerCount": len(prices),
			"url": url,
			"availability": "https://schema.org/InStock",
		}
	)


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
def base_seo_context(context) -> None:
	"""Populate SEO defaults. Page controllers may append/override values."""
	lang = getattr(context, "lang", None) or current_language()
	path = current_path()
	context.seo_language = lang
	context.seo_path = path
	context.seo_canonical = canonical_url(path, lang)
	context.seo_alternates = alternate_urls(path)
	context.seo_robots = DEFAULT_ROBOTS
	context.seo_og_type = "website"
	context.seo_image = _logo_url(lang)
	context.seo_image_alt = _brand(lang)
	context.seo_image_width, context.seo_image_height = LOGO_DIMENSIONS.get(lang, LOGO_DIMENSIONS["en"])
	context.seo_structured_data = [organization_schema(), website_schema(lang)]


def add_structured_data(context, *items) -> None:
	data = list(getattr(context, "seo_structured_data", None) or [])
	for item in items:
		if item:
			data.append(item)
	context.seo_structured_data = data


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------
def sitemap_entries(lastmod: str | None = None) -> list[dict]:
	lastmod = lastmod or nowdate()
	entries = []
	for page in PUBLIC_PAGES:
		path = page["path"]
		alternates = [
			{"hreflang": lang, "href": absolute_url(localized_url(path, lang))}
			for lang in SEO_LANGUAGES
		]
		alternates.append(
			{"hreflang": "x-default", "href": absolute_url(localized_url(path, DEFAULT_LANGUAGE))}
		)
		for lang in SEO_LANGUAGES:
			entries.append(
				{
					"loc": absolute_url(localized_url(path, lang)),
					"lastmod": lastmod,
					"changefreq": page["changefreq"],
					"priority": page["priority"],
					"alternates": alternates,
				}
			)
	return entries


def sitemap_paths() -> set[str]:
	"""URL paths that the custom sitemap owns (for de-duplication)."""
	paths = set()
	for page in PUBLIC_PAGES:
		for lang in SEO_LANGUAGES:
			url = localized_url(page["path"], lang)
			paths.add(url.split("?", 1)[0])
	return paths


def url_path(url: str) -> str:
	try:
		return urlsplit(url).path or "/"
	except Exception:
		return url
