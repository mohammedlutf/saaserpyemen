from __future__ import annotations

from saaserpyemen.utils import get_settings
from saaserpyemen.website import base_context, plans_context


def get_context(context):
	from frappe import _

	base_context(context)
	plans_context(context)
	context.show_pricing = bool(get_settings().show_pricing)
	context.title = f"{context.brand_name} — { _('Cloud ERP for growing businesses') }"
	context.metatags = {
		"description": f"{context.brand_name} { _('is a complete cloud ERP platform for growing businesses') } — { _('accounting, sales, inventory, HR and more.') }",
		"keywords": _("ERP, ERPNext, SaaS, accounting, inventory, Saudi Arabia, Yemen, Arabic ERP"),
	}
