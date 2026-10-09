"""M08-01 Research API: whether a Funding Scheme can be used by a college, budget head accounts, Research Settings
and the D9 interest treatment. Other modules call research only through these functions."""

import frappe
from frappe import _

DEFAULT_INTEREST_TREATMENT = "Grant Liability"


def unmapped_heads(scheme, company):
	"""Budget heads of `scheme` with no account mapped for `company`, in template order."""
	heads = frappe.get_all(
		"Funding Scheme Head", {"parent": scheme, "parenttype": "Funding Scheme"}, pluck="budget_head", order_by="idx"
	)
	mapped = set(
		frappe.get_all(
			"Grant Budget Head Account",
			{"parent": ["in", heads or [""]], "parenttype": "Grant Budget Head", "company": company},
			pluck="parent",
		)
	)
	return [head for head in heads if head not in mapped]


def validate_scheme_usable(scheme, company):
	"""Throw unless every budget head of `scheme` maps to an account of `company`."""
	if not frappe.db.exists("Funding Scheme Head", {"parent": scheme, "parenttype": "Funding Scheme"}):
		frappe.throw(_("Funding Scheme {0} has no budget heads.").format(scheme))
	missing = unmapped_heads(scheme, company)
	if missing:
		frappe.throw(
			_("Funding Scheme {0} can't be used by {1}: budget heads {2} have no account mapped for it.").format(
				scheme, company, ", ".join(missing)
			)
		)


def head_accounts(head, company):
	"""Accounts the budget `head` maps to for `company`."""
	return frappe.get_all(
		"Grant Budget Head Account",
		{"parent": head, "parenttype": "Grant Budget Head", "company": company},
		pluck="account",
	)


def get_research_settings(company):
	"""The company's Research Settings; throws when the college has none."""
	if not frappe.db.exists("Research Settings", company):
		frappe.throw(_("Set up Research Settings for {0} first.").format(company))
	return frappe.get_cached_doc("Research Settings", company)


def interest_treatment(company, agency):
	"""Where interest on `agency`'s grant funds goes for `company`: the agency's choice, else the college's setting
	(Grant Liability by default, blueprint D9)."""
	return (
		frappe.db.get_value("Funding Agency", agency, "interest_treatment")
		or frappe.db.get_value("Research Settings", company, "interest_treatment")
		or DEFAULT_INTEREST_TREATMENT
	)
