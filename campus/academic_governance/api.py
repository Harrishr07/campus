"""M02-01 Academic Governance API: the entry points other modules use (meetings, proposals) for who is in office."""

import frappe
from frappe.utils import today

from campus.academic_governance import composition


def members_in_office(body, on_date=None):
	"""The Body's members whose term covers on_date (default today), as dicts. Expired and not-yet-started members are left out."""
	rows = frappe.get_doc("Body", body).members
	return [m.as_dict() for m in composition.members_in_office(rows, on_date or today())]


def composition_shortfalls(body, on_date=None):
	"""Composition rules the Body's members in office on on_date do not meet (see composition.composition_shortfalls)."""
	doc = frappe.get_doc("Body", body)
	rules = frappe.get_cached_doc("Body Type", doc.body_type).composition
	return composition.composition_shortfalls(rules, doc.members, on_date or today())


def quorum_mandatory_categories(body_type):
	"""Member categories that must be represented among the attendees for a meeting to be quorate."""
	return composition.mandatory_quorum_categories(frappe.get_cached_doc("Body Type", body_type).composition)


def quorum_rule(body_type):
	"""(quorum percentage, mandatory categories) of a Body Type."""
	percent = frappe.get_cached_value("Body Type", body_type, "quorum_percent")
	return percent or 0, quorum_mandatory_categories(body_type)


def proposal_courses(company, academic_year, aqar_category, department=None):
	"""Courses named on Approved Academic Proposals of the AQAR category (Proposal Type) approved within the academic year."""
	year = frappe.db.get_value("Academic Year", academic_year, ["year_start_date", "year_end_date"], as_dict=True)
	if not year:
		return []
	proposal, kind, course = (frappe.qb.DocType(d) for d in ("Academic Proposal", "Proposal Type", "Academic Proposal Course"))
	query = (
		frappe.qb.from_(proposal)
		.join(kind).on(kind.name == proposal.proposal_type)
		.join(course).on((course.parent == proposal.name) & (course.parenttype == "Academic Proposal"))
		.select(course.course)
		.distinct()
		.where((proposal.company == company) & (proposal.status == "Approved") & (kind.aqar_category == aqar_category))
		.where(proposal.approved_on.between(year.year_start_date, year.year_end_date))
		.orderby(course.course)
	)  # fmt: skip
	if department:
		query = query.where(proposal.department == department)
	return [row[0] for row in query.run()]
