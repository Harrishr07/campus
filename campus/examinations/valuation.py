"""M06-04 Double valuation: examiner entries, the automatic third valuation and the final ESE mark.

When both valuations of a script are submitted the student's Exam Rule Set decides: a difference above
`third_valuation_diff_pct` % of the ESE maximum puts the script on the bundle's third-valuation allocation
(created Unassigned for the COE to give an examiner); otherwise, or once the third is in, the final mark
(`final_valuation_method`) is stored on the Dummy Number Map only. Nothing in an examiner's request touches a
mark sheet: Exam Confidential's write-back job (valuation_write_back) carries the marks over once the course's
allocations are Completed. The dummy-to-student join happens here on the server only; nothing it finds is
returned to, or named in a message to, the examiner. Once the student's result has been run (or the session
published) the script's marks are locked.
"""

import frappe
from frappe import _
from frappe.utils import flt

from campus.campus_platform.api import get_rule
from campus.examinations import dummy_numbers, valuation_rules
from campus.examinations.courses import offering_course, student_limits
from campus.examinations.valuation_access import DUMMY_NUMBER_MAP

ALLOCATION, ENTRY, BUNDLE = "Valuation Allocation", "Valuation Entry", "Answer Script Bundle"


# ---- examiner endpoints ---------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def submit_marks(allocation, dummy_number, **marks):
	"""Examiner: submit the question-wise marks (`q_1`, `q_2`, ... in the bundle's question order) of one script."""
	alloc = frappe.get_doc(ALLOCATION, allocation)
	if not alloc.examiner or alloc.examiner != frappe.session.user:
		raise frappe.PermissionError(_("This allocation is not yours."))
	rows = []
	for i, question in enumerate(bundle_questions(alloc.bundle), 1):
		if marks.get(f"q_{i}") in (None, ""):
			frappe.throw(_("Enter the marks of {0}.").format(question.question))
		rows.append({"question": question.question, "marks": flt(marks[f"q_{i}"])})
	entry = frappe.get_doc({"doctype": ENTRY, "allocation": alloc.name, "dummy_number": dummy_number, "marks": rows})
	entry.insert()
	entry.submit()
	return entry.name


def my_allocations():
	"""The session user's allocations with their scripts, by dummy number only (the examiner portal)."""
	allocations = frappe.get_all(
		ALLOCATION,
		{"examiner": frappe.session.user, "status": ["!=", "Unassigned"]},
		["name", "exam_session", "course", "bundle", "valuation_round", "deadline", "status"],
		order_by="deadline, name",
	)
	for alloc in allocations:
		alloc.packet_no = frappe.db.get_value(BUNDLE, alloc.bundle, "packet_no")
		alloc.questions = bundle_questions(alloc.bundle)
		valued = dict(
			frappe.get_all(ENTRY, {"allocation": alloc.name, "docstatus": 1}, ["dummy_number", "total"], as_list=True)
		)
		alloc.scripts = [
			frappe._dict(dummy_number=d, total=valued.get(d), valued=d in valued)
			for d in sorted(frappe.get_all("Valuation Allocation Script", {"parent": alloc.name, "parenttype": ALLOCATION}, pluck="dummy_number"))
		]  # fmt: skip
	return allocations


def bundle_rule_sets(bundle):
	"""The Exam Rule Sets of the regulations of the bundle's students (server-side join, no names returned)."""
	students = frappe.get_all(
		DUMMY_NUMBER_MAP,
		{"dummy_number": ["in", frappe.get_all("Answer Script Bundle Script", {"parent": bundle, "parenttype": BUNDLE}, pluck="dummy_number") or [""]]},
		pluck="student",
	)  # fmt: skip
	regulations = set(frappe.get_all("Student", {"name": ["in", students or [""]]}, pluck="oc_regulation"))
	return frappe.get_all("Exam Rule Set", {"regulation": ["in", list(regulations) or [""]]}, ["name", "allow_course_teacher_as_examiner"])


def bundle_questions(bundle):
	return frappe.get_all(
		"Answer Script Bundle Question", {"parent": bundle, "parenttype": BUNDLE}, ["question", "max_marks"], order_by="idx"
	)


# ---- checks on an entry (confidential join, anonymous messages) ------------------------------


def lock_script(entry):
	"""The entry's map row, locked: the rounds and the result lock of one script are checked one at a time."""
	row = dummy_numbers.script(entry.dummy_number, for_update=True)
	if not row or row.void or (row.exam_session, row.course) != (entry.exam_session, entry.course):
		frappe.throw(_("Script {0} is not a script of this course.").format(entry.dummy_number))
	return row


def check_script(entry, row):
	"""Refuse an entry over the ESE maximum or on a script whose result has been run (`row` locked)."""
	if result_locked(row):
		frappe.throw(_("The marks of script {0} are locked: its result has been run.").format(entry.dummy_number))
	ese_max = ese_max_of(row)
	if flt(entry.total) > ese_max:
		frappe.throw(_("The total {0} is above the ESE maximum {1}.").format(entry.total, ese_max))


def result_locked(row):
	return frappe.db.get_value("Exam Session", row.exam_session, "status") == "Published" or bool(
		frappe.db.exists("Student Result", {"student": row.student, "exam_session": row.exam_session})
	)


def ese_max_of(row):
	return anonymous(row, lambda: student_limits(row.student, offering_course(offering_of(row)))["ese_max"])


def anonymous(row, lookup):
	"""Run a lookup whose errors may name the student; the examiner sees the dummy number only."""
	try:
		return lookup()
	except (frappe.ValidationError, frappe.PermissionError):
		frappe.clear_messages()
		frappe.throw(_("Script {0} cannot be valued yet: its course rules are incomplete. Please contact the exam cell.").format(row.dummy_number))


def offering_of(row):
	"""The student's course offering of the script's course in the session's term."""
	term = frappe.db.get_value("Exam Session", row.exam_session, "academic_term")
	group, member = frappe.qb.DocType("Student Group"), frappe.qb.DocType("Student Group Student")
	found = (
		frappe.qb.from_(member)
		.join(group).on(group.name == member.parent)
		.select(group.name)
		.where(
			(member.parenttype == "Student Group") & (member.student == row.student) & (member.active == 1)
			& (group.course == row.course) & (group.academic_term == term) & (group.group_based_on == "Course")
		)
		.limit(1)
		.run(pluck=True)
	)  # fmt: skip
	if not found:
		frappe.throw(_("Script {0} has no course offering.").format(row.dummy_number))
	return found[0]


# ---- after a submitted entry ----------------------------------------------------------------


def after_valuation(entry):
	"""Third valuation or final mark once both valuations of the script are in; errors name the dummy number only."""
	row = dummy_numbers.script(entry.dummy_number, for_update=True)  # serialises the rounds of one script
	anonymous(row, lambda: settle(entry, row))


def settle(entry, row):
	marks = {
		int(r.valuation_round): flt(r.total)
		for r in frappe.qb.get_query(
			ENTRY, filters={"dummy_number": entry.dummy_number, "docstatus": 1}, fields=["valuation_round", "total"], for_update=True
		).run(as_dict=True)
	}
	refresh_allocation_status(entry.allocation)
	if not {1, 2} <= set(marks):
		return
	rule = get_rule(row.student, "Exam Rule Set")
	ese_max = student_limits(row.student, offering_course(offering_of(row)))["ese_max"]
	if 3 not in marks and valuation_rules.needs_third_valuation(marks[1], marks[2], ese_max, rule.third_valuation_diff_pct):
		allocate_third(entry.bundle, entry.dummy_number)
		return
	final = valuation_rules.final_mark(marks, rule.final_valuation_method)
	frappe.db.set_value(DUMMY_NUMBER_MAP, row.name, {"finalised": 1, "final_ese": final, "ese_written": 0, "write_back_issue": None})


def allocate_third(bundle, dummy_number):
	frappe.db.get_value(BUNDLE, bundle, "name", for_update=True)  # one third-valuation allocation per bundle
	name = frappe.db.get_value(ALLOCATION, {"bundle": bundle, "valuation_round": "3"}, for_update=True)
	alloc = frappe.get_doc(ALLOCATION, name) if name else frappe.get_doc({"doctype": ALLOCATION, "bundle": bundle, "valuation_round": "3"})
	if dummy_number not in {s.dummy_number for s in alloc.scripts}:
		alloc.append("scripts", {"dummy_number": dummy_number})
	alloc.flags.third_valuation = True
	alloc.save(ignore_permissions=True)


def refresh_allocation_status(allocation):
	alloc = frappe.get_doc(ALLOCATION, allocation)
	status = alloc.computed_status()
	if status != alloc.status:
		frappe.db.set_value(ALLOCATION, allocation, "status", status)
