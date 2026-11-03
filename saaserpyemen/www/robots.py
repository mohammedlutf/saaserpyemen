from __future__ import annotations

import frappe
from frappe.utils import get_url

no_cache = 1
base_template_path = "www/robots.txt"

# Routes that should never be crawled. Public marketing pages are not listed.
PRIVATE_PATHS = (
	"/app",
	"/api",
	"/private",
	"/login",
	"/subscribe",
	"/provisioning",
	"/dashboard",
	"/payment",
	"/suspended",
	"/update-password",
)


def _existing_robots() -> str:
	try:
		return (frappe.db.get_single_value("Website Settings", "robots_txt") or "").strip()
	except Exception:
		return ""


def build_robots_txt() -> str:
	lines: list[str] = []
	seen: set[str] = set()

	def add(line: str) -> None:
		line = line.strip()
		if not line:
			return
		key = line.lower()
		if key in seen:
			return
		seen.add(key)
		lines.append(line)

	existing = _existing_robots()
	for line in existing.splitlines():
		stripped = line.strip()
		if not stripped:
			continue
		if stripped.lower().startswith("sitemap:"):
			continue
		add(stripped)

	if "user-agent: *" not in seen:
		lines.insert(0, "User-agent: *")

	if "allow: /" not in seen:
		add("Allow: /")

	# Keep the shop's existing disallow rules and make sure the private SaaS
	# routes are covered in both language variants.
	for path in PRIVATE_PATHS:
		add(f"Disallow: {path}")
		add(f"Disallow: /ar{path}")

	lines.append("")
	lines.append(f"Sitemap: {(get_url() or '').rstrip('/')}/sitemap.xml")
	return "\n".join(lines) + "\n"


def get_context(context):
	return {"robots_txt": build_robots_txt()}
