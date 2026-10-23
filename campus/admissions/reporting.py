"""M04-10 Reporting deadlines, late joining and no-shows.

- Reporting deadline: Admission Settings holds the deadline of the current admission round (Reporting Deadline); a
  program may have its own (Program Reporting Deadlines). Admit stamps the deadline in force on the Student
  (`oc_reporting_deadline`), so the next round's deadline never moves an earlier round's students. A student admitted
  before deadlines existed uses the settings in force now.
- Late joining: a joining dated after the student's deadline needs an approved (submitted) Late Joining Request of
  the applicant, for that effective joining date (approval engine; seeded Principal approval).
- No-show: once the deadline plus the grace days (Admission Settings) has passed, an Admitted student who has not
  joined is a no-show, unless their approved Late Joining Request lets them join on or after that day. The daily job refers each one for cancellation with a draft Admission Cancellation (one bulk
  run). Nothing is cancelled automatically: an Admission Officer reviews the draft and submits it, which moves the
  student to Cancelled and drafts the refund of any advance they paid. A referred student who joins after all has
  their draft (enrollment-less) cancellation withdrawn, so it cannot later cancel the joined student.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, today

from campus.campus_platform.bulk import run_bulk
from campus.student_services.api import ADMITTED

LATE_REQUEST = "Late Joining Request"
CANCELLATION = "Admission Cancellation"
REFERRAL_RUN_TYPE = "Admission No-Show Referrals"
REFERRAL_HANDLER = "campus.admissions.reporting.refer_no_show"
REFERRAL_KEY = "campus.admissions.reporting.referral_key"


def deadline_in_force(program):
	"""The reporting deadline Admission Settings sets now for `program` (its own row, else the round's), or None."""
	settings = frappe.get_cached_doc("Admission Settings")
	row = next((row for row in settings.program_reporting_deadlines if row.program == program), None)
	return getdate(row.reporting_deadline) if row else (settings.reporting_deadline and getdate(settings.reporting_deadline))


def student_deadline(stamped, program):
	"""A student's reporting deadline: the one stamped at admission, else the one in force for the program."""
	return getdate(stamped) if stamped else deadline_in_force(program)


def check_late_joining(applicant, deadline, date):
	"""A joining dated after the deadline needs the applicant's approved Late Joining Request for that date."""
	if not deadline or getdate(date) <= getdate(deadline):
		return
	approved = frappe.db.get_value(LATE_REQUEST, {"applicant": applicant, "docstatus": 1}, "joining_date")
	if not approved:
		frappe.throw(
			_("The joining date {0} is after the reporting deadline {1}: a Late Joining Request for {2} must be approved first.").format(
				frappe.format(date, "Date"), frappe.format(deadline, "Date"), applicant
			),
			title=_("Late Joining"),
		)
	if getdate(approved) != getdate(date):
		frappe.throw(
			_("The approved Late Joining Request of {0} is for joining on {1}; confirm the joining with that date.").format(
				applicant, frappe.format(approved, "Date")
			),
			title=_("Late Joining"),
		)


# No-shows


def no_shows(as_of=None, company=None):
	"""Admitted (not joined) students whose deadline plus the grace days is before `as_of` (default today).

	[{student, student_name, applicant, company, program, reporting_deadline, referral_date}], oldest deadline first."""
	day = getdate(as_of or today())
	grace = cint(frappe.db.get_single_value("Admission Settings", "no_show_grace_days"))
	filters = {"oc_academic_status": ADMITTED, "enabled": 1, **({"oc_company": company} if company else {})}
	students = frappe.get_all(
		"Student", filters, ["name", "student_name", "student_applicant", "oc_company", "oc_reporting_deadline"], limit=0
	)
	applicants = [s.student_applicant for s in students if s.student_applicant]
	programs = dict(frappe.get_all("Student Applicant", {"name": ("in", applicants or [""])}, ["name", "program"], as_list=True))
	late = set(
		frappe.get_all(LATE_REQUEST, {"applicant": ("in", applicants or [""]), "docstatus": 1, "joining_date": (">=", day)}, pluck="applicant")
	)
	rows = []
	for student in students:
		if student.student_applicant in late:
			continue
		program = programs.get(student.student_applicant)
		deadline = student_deadline(student.oc_reporting_deadline, program)
		if deadline and day > add_days(deadline, grace):
			rows.append(
				frappe._dict(
					student=student.name, student_name=student.student_name, applicant=student.student_applicant,
					company=student.oc_company, program=program, reporting_deadline=deadline,
					referral_date=add_days(deadline, grace + 1),
				)
			)  # fmt: skip
	return sorted(rows, key=lambda row: (row.reporting_deadline, row.student))


def open_cancellation(student):
	"""The student's draft or submitted Admission Cancellation, or None."""
	return frappe.db.get_value(CANCELLATION, {"student": student, "docstatus": ("<", 2)}, "name")


def withdraw_referrals(student):
	"""A referred no-show joined after all: their draft cancellations without an enrollment are deleted."""
	frappe.db.delete(CANCELLATION, {"student": student, "docstatus": 0, "program_enrollment": ("is", "not set")})


def refer_no_shows(as_of=None):
	"""Scheduler entry point: one bulk run that refers today's unreferred no-shows; returns the Bulk Run name or None."""
	items = [
		{"student": row.student, "reporting_deadline": str(row.reporting_deadline)}
		for row in no_shows(as_of)
		if not open_cancellation(row.student)
	]
	if items:
		return run_bulk(REFERRAL_RUN_TYPE, items, REFERRAL_HANDLER, key=REFERRAL_KEY)


def referral_key(item):
	return item["student"]


def refer_no_show(item, run=None):
	"""Bulk handler: a draft Admission Cancellation for a student still Admitted and not yet referred. DB-only."""
	student = item["student"]
	if frappe.db.get_value("Student", student, "oc_academic_status") != ADMITTED or open_cancellation(student):
		return
	reason = _("No-show: did not join by the reporting deadline {0}.").format(frappe.format(item["reporting_deadline"], "Date"))
	frappe.get_doc(
		{"doctype": CANCELLATION, "student": student, "cancellation_date": today(), "reason": reason}
	).insert(ignore_permissions=True)  # fmt: skip
