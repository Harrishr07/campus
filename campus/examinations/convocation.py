"""M06-07, M05-09, M05-15 Convocation List: the eligible graduates of a company (and programme) and their export for
the university.

Eligible: a published final-year result, a Complete credit completion check (campus.examinations.completion, run
on every fill and linked on the row), and not already on another Convocation List. Listing moves an Active graduate
to Study Completed and, unless completion.award_refusal holds them (dues, the degree-awarding authority on the
convocation date; the reason is kept on the row), to Award Eligible (lifecycle, effective the convocation date once
it has passed, else the day listed); a refill that drops a student undoes those steps, and one that now holds an
Award Eligible graduate undoes that step. Mark Graduated, on or after the convocation date, checks award eligibility
again on that date, re-runs the completion check and moves the graduates to Graduated from it (COE; a cleared hold
becomes Award Eligible first), then to Alumni when the Completion Settings say "On Convocation"; it reports the ones
refused with the current reason. The export follows the list's column table (heading -> source). Filling and Mark
Graduated run each graduate's checks in the request: fine for a college's convocation (hundreds), not for a whole
university (ledger: move to the Bulk Run if lists grow). The university's format is not known yet, so
DEFAULT_COLUMNS is a placeholder the COE edits to match it. Cells that a spreadsheet would run as a formula are
neutralised.
"""

import frappe
from frappe import _
from frappe.utils import getdate, strip_html, today
from frappe.utils.csvutils import build_csv_response

from campus.examinations import completion, graduation_rules
from campus.examinations.access import COE_ROLE
from campus.examinations.graduation import final_year_students, graduate_record
from campus.student_services.api import (
	ACTIVE,
	AWARD_ELIGIBLE,
	GRADUATED,
	STUDY_COMPLETED,
	last_change_date,
	lifecycle_status,
	revert_transition,
	transition,
)

DOCTYPE = "Convocation List"
ROW = "Convocation List Graduate"
SAVEPOINT = "campus_graduate"
# Placeholder export format (heading, source); see the module docstring.
DEFAULT_COLUMNS = [
	("Register Number", "Register Number"), ("Student Name", "Student Name"), ("Date of Birth", "Date of Birth"),
	("Programme", "Program"), ("Regulation", "Regulation"), ("CGPA", "CGPA"), ("Percentage", "Percentage"),
	("Classification", "Classification"), ("Completion Term", "Completion Term"),
]  # fmt: skip
SOURCES = {
	"Register Number": "register_no", "Student": "student", "Student Name": "student_name", "Date of Birth": "date_of_birth",
	"Program": "program", "Regulation": "regulation", "CGPA": "cgpa", "Percentage": "percentage",
	"Classification": "classification", "Variant": "variant", "Completion Term": "completion_term",
}  # fmt: skip


def fill_graduates(convocation_list):
	"""Replace the list's graduates with the eligible ones; returns their number. A student no longer listed goes
	back from Award Eligible / Study Completed, while that is still their latest change."""
	doc = frappe.get_doc(DOCTYPE, convocation_list)
	doc.check_permission("write")
	listed = set(frappe.get_all(ROW, {"parenttype": DOCTYPE, "parent": ["!=", doc.name]}, pluck="student"))
	before = {row.student for row in doc.graduates}
	doc.graduates = []
	award_on = doc.convocation_date or today()
	for student in final_year_students(doc.company, doc.program):
		if student in listed:
			continue
		check = completion.run_check(student)
		if check.result == completion.rules.COMPLETE:
			row = graduate_row(graduate_record(student))
			hold = completion.award_refusal(student, award_on, doc.program or row["program"])
			doc.append("graduates", {**row, "completion_check": check.name, "award_hold": hold})
	doc.save()
	for row in doc.graduates:
		record_award_eligible(row, doc)
	for student in sorted(before - {row.student for row in doc.graduates}):
		undo_award_eligible(student, doc)
	return len(doc.graduates)


def record_award_eligible(row, doc):
	"""Active -> Study Completed -> Award Eligible (unless held), dated by listing_date; a graduate already past
	either step is left as they are, except that a hold undoes this list's Award Eligible."""
	if lifecycle_status(row.student) == ACTIVE:
		reason = _("Credit completion check {0} passed").format(row.completion_check)
		if row.completion_term:
			reason = _("Programme completed in {0}; credit completion check {1} passed").format(row.completion_term, row.completion_check)
		transition(row.student, STUDY_COMPLETED, listing_date(doc, row.student), reason, doc)
	if row.award_hold:
		revert_transition(doc, _("Held: {0}").format(row.award_hold), student=row.student, statuses=(AWARD_ELIGIBLE,))
		return
	if lifecycle_status(row.student) == STUDY_COMPLETED:
		transition(row.student, AWARD_ELIGIBLE, listing_date(doc, row.student), _("Listed for convocation on {0}").format(doc.name), doc)


def listing_date(doc, student):
	"""The list's convocation date when it has passed, else today; never before the student's last change."""
	day = min(getdate(doc.convocation_date or today()), getdate(today()))
	last = last_change_date(student)
	return max(day, getdate(last)) if last else day


def undo_award_eligible(student, doc):
	reason = _("No longer on Convocation List {0}").format(doc.name)
	while revert_transition(doc, reason, student=student, statuses=(AWARD_ELIGIBLE, STUDY_COMPLETED)):
		pass


def graduate(convocation_list):
	"""Record the list's graduates as Graduated from the convocation date (and Alumni, per the Completion Settings).
	Each one is checked again first (graduation_refusal); a Study Completed graduate whose hold has cleared becomes
	Award Eligible on the way. Returns {graduated, refused: [{student, reason}]} (plain text, the current reason): a
	graduate refused there or by the lifecycle (e.g. a later change) writes nothing (savepoint) and does not stop the
	rest."""
	frappe.only_for((COE_ROLE, "System Manager"))
	doc = frappe.get_doc(DOCTYPE, convocation_list)
	doc.check_permission("write")
	if not doc.convocation_date or getdate(doc.convocation_date) > getdate(today()):
		frappe.throw(_("Set the convocation date; graduates are recorded on or after it."))
	graduated, refused = 0, []
	for row in doc.graduates:
		status = lifecycle_status(row.student)
		if status not in (STUDY_COMPLETED, AWARD_ELIGIBLE):
			continue
		reason = graduation_refusal(row, doc)
		if reason:
			refused.append({"student": row.student, "reason": reason})
			continue
		messages = len(frappe.local.message_log)
		frappe.db.savepoint(SAVEPOINT)
		try:
			if status == STUDY_COMPLETED:  # a hold that has cleared since listing
				transition(row.student, AWARD_ELIGIBLE, listing_date(doc, row.student), _("Listed for convocation on {0}").format(doc.name), doc)
			transition(row.student, GRADUATED, doc.convocation_date, _("Degree conferred at convocation {0}").format(doc.name), doc)
			completion.alumni_on_convocation(row.student, doc.convocation_date, doc)
			graduated += 1
		except frappe.ValidationError as error:  # the refused student writes nothing
			frappe.db.rollback(save_point=SAVEPOINT)
			del frappe.local.message_log[messages:]
			refused.append({"student": row.student, "reason": strip_html(str(error))})  # plain text: the form escapes it
	return {"graduated": graduated, "refused": refused}


def graduation_refusal(row, doc):
	"""Why the listed graduate cannot graduate at this convocation now (plain text), or None: the completion check is
	run again (a result back to pending ratification, a cancelled recognition) and award eligibility is checked on
	the convocation date."""
	check = completion.run_check(row.student)
	if check.result != completion.rules.COMPLETE:
		return _("Completion check {0} is Incomplete: {1}").format(check.name, "; ".join((check.reasons or "").splitlines()))
	hold = completion.award_refusal(row.student, doc.convocation_date, doc.program or row.program)
	return _("Not award eligible: {0}").format(hold) if hold else None


def graduate_row(record):
	return {
		"student": record.student, "student_name": record.student_name, "register_no": record.register_no,
		"date_of_birth": record.date_of_birth, "program": record.program, "regulation": record.regulation,
		"cgpa": record.cgpa, "percentage": record.percentage, "classification": record.classification,
		"variant": record.class_variant or record.variant, "completion_term": record.completion_term,
	}  # fmt: skip


def export_rows(convocation_list):
	"""[headings, *graduate rows] of the list in its column format."""
	doc = frappe.get_doc(DOCTYPE, convocation_list)
	doc.check_permission("read")
	columns = [(c.heading, SOURCES[c.source]) for c in doc.columns]
	if not columns:
		frappe.throw(_("Set the export columns of {0} first.").format(doc.name))
	rows = [[graduation_rules.csv_cell(heading) for heading, _field in columns]]
	for graduate in doc.graduates:
		rows.append([graduation_rules.csv_cell(graduate.get(field)) for _heading, field in columns])
	return rows


def download(convocation_list):
	build_csv_response(export_rows(convocation_list), convocation_list)
