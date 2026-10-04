"""M17-01 Campus Platform service API. Other modules call these, never the controllers (D7)."""

import frappe
from frappe.utils import today

from campus.campus_platform.approval_access import pending_approvals  # noqa: F401  (public API)
from campus.campus_platform.approvals import ApprovableDocument, request_approval  # noqa: F401  (public API)
from campus.campus_platform.pack_rules import effective_status, status_allows_pack
from campus.campus_platform.positions import resolve_position  # noqa: F401  (public API)
from campus.campus_platform.regulation_rules import (  # noqa: F401  (public API)
	get_regulation,
	get_rule,
	latest_enrollment,
)

PACK_CACHE = "campus_pack_enabled"


def pack_enabled(company, code):
	"""True if module pack `code` is available to `company`. Cached per day; see `clear_pack_cache`."""
	return frappe.cache.hget(PACK_CACHE, f"{company}|{code}|{today()}", lambda: _compute_pack_enabled(company, code))


def clear_pack_cache():
	frappe.cache.delete_value(PACK_CACHE)


def _compute_pack_enabled(company, code):
	profile = frappe.db.get_value(
		"Institution Profile", company, ["institution_status", "status_effective_from"], as_dict=True
	)
	if not profile or not frappe.db.get_value("Module Pack", code, "enabled"):
		return False
	switched_off = frappe.db.get_value("Institution Pack", {"parent": company, "pack": code}, "enabled")
	if switched_off is not None and not switched_off:
		return False
	allowed = frappe.get_all("Module Pack Status", filters={"parent": code}, pluck="status")
	status = effective_status(profile.institution_status, profile.status_effective_from, today())
	return status_allows_pack(allowed, status)


def get_institution(company):
	"""Institution Profile document of `company`, or None."""
	if frappe.db.exists("Institution Profile", company):
		return frappe.get_doc("Institution Profile", company)


def service_provider(service, company):
	"""Provider company of `service` for member `company` under the agreement in force today, or None."""
	agreements = frappe.get_all(
		"Shared Service Agreement",
		filters={
			"service": service,
			"from_date": ["<=", today()],
			"name": ["in", _agreements_with_member(company)],
		},
		or_filters=[["to_date", "is", "not set"], ["to_date", ">=", today()]],
		fields=["provider_company"],
		order_by="from_date desc",
		limit=1,
	)
	return agreements[0].provider_company if agreements else None


def _agreements_with_member(company):
	return frappe.get_all("Shared Service Member", filters={"company": company}, pluck="parent") or [""]
