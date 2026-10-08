"""M06-03 Question Paper Print Log: copies of each paper set printed per hall, from the allowed Print rows of the
QP Access Log. Filtered by company; list access (Exam Confidential, User Permissions) applies."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), rows(filters)


def columns():
	return [
		{"fieldname": "question_paper", "label": _("Question Paper"), "fieldtype": "Link", "options": "Question Paper", "width": 140},
		{"fieldname": "paper_set", "label": _("Set"), "fieldtype": "Data", "width": 60},
		{"fieldname": "room", "label": _("Hall"), "fieldtype": "Link", "options": "Room", "width": 180},
		{"fieldname": "copies", "label": _("Copies"), "fieldtype": "Int", "width": 90},
		{"fieldname": "last_printed_at", "label": _("Last Printed At"), "fieldtype": "Datetime", "width": 170},
	]


def rows(filters):
	conditions = {"company": filters.company, "action": "Print", "result": "Allowed"}
	if filters.question_paper:
		conditions["question_paper"] = filters.question_paper
	if filters.exam_session:
		papers = frappe.get_list("Question Paper", {"exam_session": filters.exam_session}, pluck="name")
		conditions["question_paper"] = ["in", papers or [""]]
	return frappe.get_list(
		"QP Access Log", filters=conditions,
		fields=["question_paper", "paper_set", "room", {"SUM": "copies", "as": "copies"}, {"MAX": "accessed_at", "as": "last_printed_at"}],
		group_by="question_paper, paper_set, room", order_by="question_paper, paper_set, room",
	)  # fmt: skip
