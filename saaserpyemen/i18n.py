# Copyright (c) 2026, mohammedlutf and contributors
# For license information, please see license.txt
"""URL-based language routing and helpers for the Sahbix website."""

from __future__ import annotations

import frappe


SUPPORTED_LANGUAGES = ("en", "ar")
DEFAULT_LANGUAGE = "en"


def _normalize_lang(lang: str | None) -> str:
	if not lang:
		return DEFAULT_LANGUAGE
	lang = str(lang).strip().lower()
	if lang.startswith("ar"):
		return "ar"
	if lang.startswith("en"):
		return "en"
	return DEFAULT_LANGUAGE


def _extract_lang_from_path(path: str) -> tuple[str, str]:
	"""Return (language, stripped_path). Unprefixed paths default to English."""
	if not path:
		return DEFAULT_LANGUAGE, "/"
	# Remove query string for path resolution
	path = path.split("?", 1)[0]
	path = path.split("#", 1)[0]
	if not path.startswith("/"):
		path = "/" + path

	parts = [p for p in path.strip("/").split("/") if p != ""]
	if parts and parts[0] in SUPPORTED_LANGUAGES:
		lang = parts[0]
		remaining = parts[1:]
		stripped = "/" + "/".join(remaining) if remaining else "/"
		return _normalize_lang(lang), stripped
	return DEFAULT_LANGUAGE, path


def resolve_website_path(path: str):
	"""Website path resolver hook to support /en/ and /ar/ prefixes."""
	try:
		lang, stripped = _extract_lang_from_path(path)
		# Set language before resolving/rendering
		frappe.local.lang = lang
		try:
			frappe.form_dict._lang = lang
		except Exception:
			pass
		# Store for downstream use
		try:
			frappe.local.flags.saas_lang = lang
			frappe.local.flags.saas_path = stripped
		except Exception:
			pass

		# Delegate to the default resolver. Frappe's path resolver expects a
		# path without a leading slash (e.g. "plans"), and "" for the home page.
		from frappe.website import path_resolver

		internal = stripped.lstrip("/")
		if internal in ("index", "index.html"):
			internal = ""
		# Honour website redirects for localized URLs too, since Frappe runs
		# redirect matching before this hook using the still-prefixed path.
		try:
			path_resolver.resolve_redirect(internal)
		except frappe.Redirect:
			raise
		except Exception:
			pass

		resolved = path_resolver.resolve_path(internal)
		return resolved
	except Exception:
		# Fallback to default behavior
		from frappe.website import path_resolver

		return path_resolver.resolve_path(path)


def localized_url(path: str, lang: str | None = None) -> str:
	"""Return a localized URL for the given path."""
	if not path:
		path = "/"
	if path.startswith("http://") or path.startswith("https://") or path.startswith("mailto:") or path.startswith("tel:"):
		return path
	if path.startswith("#"):
		return path

	# Determine target language
	if lang is None:
		lang = getattr(frappe.local, "lang", None) or getattr(frappe.local.flags, "saas_lang", None) or DEFAULT_LANGUAGE
	lang = _normalize_lang(lang)

	# Split path and query
	query = ""
	fragment = ""
	if "?" in path:
		path, query = path.split("?", 1)
	if "#" in path:
		path, fragment = path.split("#", 1)

	if not path.startswith("/"):
		path = "/" + path

	# If already prefixed, strip and re-apply
	parts = [p for p in path.strip("/").split("/") if p != ""]
	if parts and parts[0] in SUPPORTED_LANGUAGES:
		parts = parts[1:]
		path = "/" + "/".join(parts) if parts else "/"

	# English at root (unprefixed), Arabic under /ar
	if lang == DEFAULT_LANGUAGE:
		localized = path if path != "" else "/"
	else:
		if path == "/":
			localized = f"/{lang}"
		else:
			localized = f"/{lang}{path}"

	if query:
		localized = f"{localized}?{query}"
	if fragment:
		localized = f"{localized}#{fragment}"
	return localized


def saas_url(path: str, lang: str | None = None) -> str:
	"""Jinja helper alias for localized_url."""
	return localized_url(path, lang)


def switch_language_url(current_lang: str | None = None) -> str:
	"""Return URL to switch to the other language."""
	if current_lang is None:
		current_lang = getattr(frappe.local, "lang", None) or getattr(frappe.local.flags, "saas_lang", None) or DEFAULT_LANGUAGE
	current_lang = _normalize_lang(current_lang)
	other = "ar" if current_lang == "en" else "en"

	# Get current path
	try:
		req = getattr(frappe.local, "request", None)
		if req:
			current_path = getattr(req, "full_path", None) or getattr(req, "path", "/") or "/"
		else:
			current_path = "/"
	except Exception:
		current_path = "/"

	# If full_path includes query string, preserve it
	query = ""
	if "?" in current_path:
		path_only, query = current_path.split("?", 1)
	else:
		path_only = current_path

	# Strip existing lang prefix
	lang, stripped = _extract_lang_from_path(path_only)
	if other == DEFAULT_LANGUAGE:
		target = stripped if stripped != "" else "/"
	else:
		if stripped == "/":
			target = f"/{other}"
		else:
			target = f"/{other}{stripped}"

	if query:
		target = f"{target}?{query}"
	return target


def localized_text(en_text: str, ar_text: str, lang: str | None = None) -> str:
	if lang is None:
		lang = getattr(frappe.local, "lang", None) or getattr(frappe.local.flags, "saas_lang", None) or DEFAULT_LANGUAGE
	lang = _normalize_lang(lang)
	if lang == "ar":
		return ar_text if ar_text is not None else en_text
	return en_text if en_text is not None else ar_text


def status_label(status: str, lang: str | None = None) -> str:
	"""Map common status values to localized labels."""
	if lang is None:
		lang = getattr(frappe.local, "lang", None) or getattr(frappe.local.flags, "saas_lang", None) or DEFAULT_LANGUAGE
	lang = _normalize_lang(lang)

	mapping_en = {
		"Trial": "Trial",
		"Pending": "Pending",
		"Pending Payment": "Pending Payment",
		"Active": "Active",
		"Past Due": "Past Due",
		"Suspended": "Suspended",
		"Expired": "Expired",
		"Provisioning": "Provisioning",
		"Failed": "Failed",
		"Draft": "Draft",
		"Cancelled": "Cancelled",
		"Pending Review": "Pending Review",
		"Paid": "Paid",
		"Rejected": "Rejected",
		"Refunded": "Refunded",
		"Unpaid": "Unpaid",
	}
	mapping_ar = {
		"Trial": "تجربة",
		"Pending": "قيد الانتظار",
		"Pending Payment": "بانتظار الدفع",
		"Active": "نشط",
		"Past Due": "متأخر السداد",
		"Suspended": "موقوف",
		"Expired": "منتهي",
		"Provisioning": "قيد الإعداد",
		"Failed": "فشل",
		"Draft": "مسودة",
		"Cancelled": "ملغي",
		"Pending Review": "بانتظار المراجعة",
		"Paid": "مدفوع",
		"Rejected": "مرفوض",
		"Refunded": "مسترد",
		"Unpaid": "غير مدفوع",
	}
	if lang == "ar":
		return mapping_ar.get(status, status)
	return mapping_en.get(status, status)
