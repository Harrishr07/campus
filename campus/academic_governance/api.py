"""M02-01 Academic Governance API: the entry points other modules use (meetings, proposals) for who is in office."""

from collections import Counter

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


def approved_proposals(company, academic_year, aqar_category, department=None):
	"""Names of the Approved Academic Proposals of the AQAR category (Proposal Type) approved within the academic year."""
	year = frappe.db.get_value(
		"Academic Year", academic_year, ["year_start_date", "year_end_date"], as_dict=True
	)
	if not year:
		return []
	proposal, kind = frappe.qb.DocType("Academic Proposal"), frappe.qb.DocType("Proposal Type")
	query = (
		frappe.qb.from_(proposal)
		.join(kind).on(kind.name == proposal.proposal_type)
		.select(proposal.name)
		.where((proposal.company == company) & (proposal.status == "Approved") & (kind.aqar_category == aqar_category))
		.where(proposal.approved_on.between(year.year_start_date, year.year_end_date))
	)  # fmt: skip
	if department:
		query = query.where(proposal.department == department)
	return [row[0] for row in query.run()]


def proposal_courses(company, academic_year, aqar_category, department=None):
	"""Distinct Courses named on the approved proposals of the category (AQAR 1.2.1 new courses)."""
	names = approved_proposals(company, academic_year, aqar_category, department)
	return sorted(
		set(
			frappe.get_all(
				"Academic Proposal Course",
				{"parenttype": "Academic Proposal", "parent": ["in", names or [""]]},
				pluck="course",
			)
		)
	)


def proposal_programmes(company, academic_year, aqar_category, department=None):
	"""Distinct Programmes whose curriculum an approved proposal of the category changed (AQAR 1.1.2 syllabus revision)."""
	names = approved_proposals(company, academic_year, aqar_category, department)
	curricula = frappe.get_all(
		"Academic Proposal", {"name": ["in", names or [""]], "curriculum": ["is", "set"]}, pluck="curriculum"
	)
	return sorted(set(frappe.get_all("Curriculum", {"name": ["in", curricula or [""]]}, pluck="program")))


def committee_bodies(company, body_type=None):
	"""Enabled Bodies of the company the user may read, with the minimum meetings a year of their Body Type."""
	filters = {"company": company, "enabled": 1, **({"body_type": body_type} if body_type else {})}
	bodies = frappe.get_list("Body", filters, ["name", "body_type"], order_by="name")
	for body in bodies:
		body.min_meetings_per_year = frappe.get_cached_value(
			"Body Type", body.body_type, "min_meetings_per_year"
		)
	return bodies


def meetings_held(bodies, from_date, to_date):
	"""{body: number of Held meetings dated within the period} for the given Bodies."""
	rows = frappe.get_all(
		"Body Meeting",
		{"body": ["in", bodies or [""]], "status": "Held", "meeting_date": ["between", [from_date, to_date]]},
		pluck="body",
	)
	return dict(Counter(rows))


def body_meetings(company, from_date, to_date, body_type):
	"""Meetings (not cancelled) of Bodies of the Body Type within the period that the user may read."""
	return meetings_of([b.name for b in committee_bodies(company, body_type)], from_date, to_date)


def meetings_of(bodies, from_date, to_date):
	return frappe.get_list(
		"Body Meeting",
		{
			"body": ["in", bodies or [""]],
			"status": ["!=", "Cancelled"],
			"meeting_date": ["between", [from_date, to_date]],
		},
		["name", "body", "meeting_date", "status"],
		order_by="meeting_date asc",
	)


def action_items(company, from_date, to_date, body_type=None):
	"""Action Items of the company's meetings within the period (the user's readable ones), with the meeting date."""
	meetings = {
		m.name: m.meeting_date
		for m in meetings_of([b.name for b in committee_bodies(company, body_type)], from_date, to_date)
	}
	items = frappe.get_list(
		"Meeting Action Item",
		{"body_meeting": ["in", list(meetings) or [""]]},
		[
			"name",
			"body_meeting",
			"body",
			"resolution_no",
			"action",
			"responsible",
			"due_date",
			"status",
			"action_taken",
		],
		order_by="due_date asc",
	)
	for item in items:
		item.meeting_date = meetings[item.body_meeting]
	return items
