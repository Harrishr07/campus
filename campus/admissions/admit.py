"""M04-01, M04-09 Admit: the admission approval turns an approved applicant into an admitted Student.

Admit creates the Student (+ Customer, via Education's own Student hooks) in lifecycle status Admitted (M05-09) and
sets the applicant Admitted. It creates nothing billable and no ID: the Program Enrollment, register and roll
numbers, fee invoice, onboarding checklist, attendance start and the Student's joining date follow the joining
confirmation (campus.admissions.joining). The reporting deadline in force is stamped on the Student (M04-10). Money
taken before joining is an advance (a Payment Entry against the student's customer), allocated to the fee invoice at
joining.

One transaction behind a savepoint: any failure rolls back to the savepoint and re-raises, so nothing half-created
remains. The one exception is the Aadhaar "admission copy" log row, which is committed on its own connection by
design (an audit row for a number that was read).
"""

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc

from campus.admissions import documents
from campus.admissions.aadhaar import copy_aadhaar
from campus.admissions.reporting import deadline_in_force
from campus.admissions.setup import OFFICER_ROLE
from campus.campus_platform.company_scope import permitted_companies
from campus.student_services.api import ADMITTED

SAVEPOINT = "campus_admit"


def admit(applicant):
	"""See `campus.admissions.api.admit`."""
	frappe.only_for(OFFICER_ROLE)
	return retry_on_deadlock(admit_once, applicant, action=_("admitting {0}").format(applicant))


def retry_on_deadlock(once, applicant, *args, action):
	"""Run `once(applicant, *args)`, once more after a deadlock, then report the desk as busy with `action` to retry
	(e.g. "admitting APP-0001").

	MariaDB aborts one of two transactions that lock against each other (e.g. over the naming series or the
	Program Enrollment index gaps) and rolls it back; the abort is fail closed: nothing was written.
	"""
	for _attempt in range(2):
		try:
			return once(applicant, *args)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
	frappe.throw(_("The admission desk is busy. Please try {0} again.").format(action))


def admit_once(applicant):
	state = lock_applicant(applicant)
	check_company_access(state.oc_company)
	check_admittable(applicant, state)
	frappe.db.savepoint(SAVEPOINT)
	try:
		return create_admission(applicant, state)
	except frappe.QueryDeadlockError:
		raise  # the transaction and its savepoints are gone; admit() rolls back and retries
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise


def lock_applicant(applicant):
	"""The applicant's decisive fields, read with a locking read: a second Admit (or joining) of the same applicant
	waits and then sees the first one's result."""
	fields = [
		"application_status", "oc_eligibility_status", "oc_company", "program", "academic_year", "academic_term",
		"oc_admission_quota", "student_category",
	]  # fmt: skip
	state = frappe.db.get_value("Student Applicant", applicant, fields, as_dict=True, for_update=True)
	if not state:
		raise frappe.DoesNotExistError(_("Student Applicant {0} does not exist.").format(applicant))
	return state


def check_company_access(company):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and company not in permitted:
		frappe.throw(_("You are not permitted to admit into {0}.").format(company), frappe.PermissionError)


def check_admittable(applicant, state):
	if state.application_status != "Approved":
		frappe.throw(_("Only an Approved applicant can be admitted; {0} is {1}.").format(applicant, state.application_status))
	check_cleared(applicant, state)


def check_cleared(applicant, state):
	"""The clearances admission and joining both need: eligible, documents complete (or under a running temporary
	clearance, M04-10), program, quota, category, year."""
	if state.oc_eligibility_status != "Eligible":
		frappe.throw(_("Applicant {0} is not Eligible ({1}).").format(applicant, state.oc_eligibility_status))
	missing = documents.uncleared_mandatory(frappe.get_doc("Student Applicant", applicant))
	if missing:
		frappe.throw(_("Applicant {0} has incomplete mandatory documents: {1}.").format(applicant, ", ".join(missing)))
	if not state.program or not state.oc_admission_quota or not state.student_category:
		frappe.throw(_("Applicant {0} needs a program, an admission quota and a student category.").format(applicant))
	admission_year(state)


def admission_year(state):
	year = state.academic_year or frappe.db.get_single_value("Admission Settings", "active_admission_year")
	if not year:
		frappe.throw(_("Set the applicant's academic year or the active admission year in Admission Settings."))
	return year


def create_admission(applicant, state):
	student = create_student(frappe.get_doc("Student Applicant", applicant), state)
	frappe.db.set_value("Student Applicant", applicant, "application_status", "Admitted")
	return {"student": student.name}


def create_student(source, state):
	"""Education's applicant-to-student mapping, plus company, quota, reporting deadline and the Aadhaar copy;
	lifecycle Admitted. The joining date is left blank: the joining's enrollment sets it (Education defaults it to
	today on insert, so it is cleared afterwards; the lifecycle's initial record is dated before that)."""
	student = get_mapped_doc(
		"Student Applicant", source.name,
		{"Student Applicant": {"doctype": "Student", "field_map": {"name": "student_applicant"}}},
		ignore_permissions=True,
	)  # fmt: skip
	student.oc_company = state.oc_company
	student.oc_academic_status = ADMITTED
	student.oc_admission_quota = state.oc_admission_quota
	student.oc_lateral_entry = int(source.oc_admission_type == "Lateral")
	student.oc_reporting_deadline = deadline_in_force(state.program)
	copy_aadhaar(source, student)
	student.insert(ignore_permissions=True)
	frappe.db.set_value("Student", student.name, "joining_date", None)
	student.joining_date = None
	return student
