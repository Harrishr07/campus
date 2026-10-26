"""M01-05 / M07-04 Feedback Analysis: ratings per question, per course offering or per faculty, k-anonymous.

Only closed campaigns (window ended before today) the user may read (company User Permissions apply) are counted, so a
figure never moves while answers come in. Every (campaign, group) cell answered by fewer respondents than Campus
Settings > Feedback Minimum Group Size is dropped before cells are pooled into a row, so a small campaign never shows as
the difference between two filters; the report says how many cells were left out. Answers to a (campaign, question)
answered by fewer than that are left out first, for every grouping: an optional question answered by a few would
otherwise show as a Course or Faculty figure minus the question rows. Free-text answers are counted, never
listed.
"""

from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import flt, today

from campus.campus_platform.company_scope import permitted_companies
from campus.iqac.access import READERS
from campus.iqac.feedback import ANSWER, RESPONSE, large_question_answers, minimum_group_size

GROUPS = {
	"Question": ("campaign", "question_row"),
	"Course": ("course_offering",),
	"Faculty": ("instructor",),
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.only_for(READERS)
	permitted = permitted_companies(frappe.session.user)
	if not filters.company or (permitted is not None and filters.company not in permitted):
		frappe.throw(_("Choose a college you are permitted for."), frappe.PermissionError)
	group_by = filters.group_by or "Question"
	if group_by not in GROUPS:
		frappe.throw(_("Group By must be one of {0}.").format(", ".join(GROUPS)))
	least = minimum_group_size()
	answered, small_questions = large_question_answers(answers(filters), least)
	kept, small_groups = large_cells(answered, GROUPS[group_by], least)
	hidden = small_questions + small_groups
	rows = [row(group_by, items) for items in grouped(kept, GROUPS[group_by]).values()]
	message = (
		_("{0} group(s) with fewer than {1} responses (the minimum group size) are not shown.").format(
			hidden, least
		)
		if hidden
		else None
	)
	return columns(group_by), rows, message


def large_cells(items, keys, least):
	"""The answers of the (campaign, group) cells with at least `least` responses, and how many cells were dropped."""
	kept, hidden = [], 0
	for cell in grouped(items, tuple(dict.fromkeys(("campaign", *keys)))).values():
		if len({i.response for i in cell}) >= least:
			kept += cell
		else:
			hidden += 1
	return kept, hidden


def answers(filters):
	campaign_filters = {"company": filters.company, "end_date": ["<", today()]}
	for field in ("campaign", "academic_year", "course_offering", "instructor"):
		if filters.get(field):
			campaign_filters["name" if field == "campaign" else field] = filters.get(field)
	campaigns = frappe.get_list("Feedback Campaign", campaign_filters, pluck="name", limit_page_length=0)
	if not campaigns:
		return []
	response, answer = frappe.qb.DocType(RESPONSE), frappe.qb.DocType(ANSWER)
	return (
		frappe.qb.from_(response)
		.join(answer)
		.on((answer.parent == response.name) & (answer.parenttype == RESPONSE))
		.select(
			response.name.as_("response"), response.campaign, response.course_offering, response.instructor, answer.question_row,
			answer.question, answer.question_type, answer.course_outcome, answer.rating, answer.answer, answer.idx,
		)
		.where(response.campaign.isin(campaigns))
		.orderby(response.campaign, answer.idx)
		.run(as_dict=True)
	)  # fmt: skip


def grouped(rows, keys):
	groups = defaultdict(list)
	for item in rows:
		groups[tuple(item[k] for k in keys)].append(item)
	return groups


def row(group_by, items):
	first = items[0]
	ratings = [i.rating for i in items if i.question_type == "Likert" and i.rating]
	result = {
		"responses": len({i.response for i in items}),
		"average": flt(sum(ratings) / len(ratings), 2) if ratings else None,
	}
	if group_by == "Question":
		result.update({k: first[k] for k in ("campaign", "question", "question_type", "course_outcome")})
		result["distribution"] = distribution(first.question_type, items, ratings)
	elif group_by == "Course":
		result.update(
			{
				"course_offering": first.course_offering,
				"course": frappe.db.get_value("Student Group", first.course_offering, "course"),
			}
		)
	else:
		result.update(
			{
				"instructor": first.instructor,
				"instructor_name": frappe.db.get_value("Instructor", first.instructor, "instructor_name"),
			}
		)
	return result


def distribution(question_type, items, ratings):
	if question_type == "Likert":
		counts = Counter(ratings)
		return ", ".join(f"{n}: {counts.get(n, 0)}" for n in range(1, 6))
	if question_type == "Choice":
		return "; ".join(
			f"{option}: {count}" for option, count in Counter(i.answer for i in items).most_common()
		)
	return None  # free text is never listed


def columns(group_by):
	count = [
		{"fieldname": "responses", "label": _("Responses"), "fieldtype": "Int", "width": 100},
		{
			"fieldname": "average",
			"label": _("Average Rating (1-5)"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 140,
		},
	]
	if group_by == "Question":
		return [
			{"fieldname": "campaign", "label": _("Campaign"), "fieldtype": "Link", "options": "Feedback Campaign", "width": 150},
			{"fieldname": "question", "label": _("Question"), "fieldtype": "Data", "width": 320},
			{"fieldname": "question_type", "label": _("Type"), "fieldtype": "Data", "width": 80},
			{"fieldname": "course_outcome", "label": _("CO"), "fieldtype": "Data", "width": 60},
			*count,
			{"fieldname": "distribution", "label": _("Distribution"), "fieldtype": "Data", "width": 260},
		]  # fmt: skip
	if group_by == "Course":
		return [
			{"fieldname": "course_offering", "label": _("Course Offering"), "fieldtype": "Link", "options": "Student Group", "width": 220},
			{"fieldname": "course", "label": _("Course"), "fieldtype": "Link", "options": "Course", "width": 200},
			*count,
		]  # fmt: skip
	return [
		{
			"fieldname": "instructor",
			"label": _("Instructor"),
			"fieldtype": "Link",
			"options": "Instructor",
			"width": 180,
		},
		{"fieldname": "instructor_name", "label": _("Name"), "fieldtype": "Data", "width": 200},
		*count,
	]
