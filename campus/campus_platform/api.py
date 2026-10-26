"""M17-01 Campus Platform service API. Other modules call these, never the controllers (D7)."""

import frappe
from frappe.utils import today

from campus.campus_platform.approval_access import pending_approvals  # noqa: F401  (public API)
from campus.campus_platform.approval_engine import (  # noqa: F401  (public API)
	find_policy,
	latest_request,
	start_request,
)
from campus.campus_platform.approvals import ApprovableDocument, request_approval  # noqa: F401  (public API)
from campus.campus_platform.bulk import live_run, run_bulk  # noqa: F401  (public API)
from campus.campus_platform.company_scope import permitted_companies  # noqa: F401  (public API)
from campus.campus_platform.pack_rules import effective_status, status_allows_pack
from campus.campus_platform.positions import resolve_position  # noqa: F401  (public API)
from campus.campus_platform.regulation_rules import (  # noqa: F401  (public API)
	apply_regulation_change,
	get_regulation,
	get_rule,
	latest_enrollment,
	resolve_regulation,
)
from campus.campus_platform.regulation_setup import DEAN_ROLE  # noqa: F401  (public API)

PACK_CACHE = "campus_pack_enabled"


def pack_enabled(company, code):
	"""True if module pack `code` is available to `company`. Cached per day; see `clear_pack_cache`."""
	return frappe.cache.hget(
		PACK_CACHE, f"{company}|{code}|{today()}", lambda: _compute_pack_enabled(company, code)
	)


def clear_pack_cache():
	from campus.campus_platform.pack_visibility import hidden_workspaces  # lazy: it imports this module

	frappe.cache.delete_value(PACK_CACHE)
	getattr(frappe.local, "request_cache", {}).pop(hidden_workspaces.__wrapped__, None)


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
	agreements = _agreements_in_force(
		service,
		name=["in", _agreements_with_member(company)],
		fields=["provider_company"],
		order_by="from_date desc",
		limit=1,
	)
	return agreements[0].provider_company if agreements else None


def _agreements_in_force(service, pluck=None, fields=None, order_by=None, limit=None, **filters):
	"""Shared Service Agreements of `service` whose dates cover today, narrowed by `filters`."""
	return frappe.get_all(
		"Shared Service Agreement",
		filters={"service": service, "from_date": ["<=", today()], **filters},
		or_filters=[["to_date", "is", "not set"], ["to_date", ">=", today()]],
		pluck=pluck,
		fields=fields,
		order_by=order_by,
		limit=limit,
	)


def served_companies(service, provider_company):
	"""Member companies served with `service` by `provider_company` under the agreements in force today."""
	agreements = _agreements_in_force(service, provider_company=provider_company, pluck="name")
	if not agreements:
		return []
	members = frappe.get_all("Shared Service Member", filters={"parent": ["in", agreements]}, pluck="company")
	return sorted(set(members))


def _agreements_with_member(company):
	return frappe.get_all("Shared Service Member", filters={"company": company}, pluck="parent") or [""]


def is_approved(doc):
	"""True when the latest approval request of `doc` ended Approved."""
	latest = latest_request(doc)
	return bool(latest and latest.status == "Approved")
