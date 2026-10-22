"""M04-01 Admit: turn an approved applicant into a Student with enrollment, register number and fee invoice.

Everything happens in one transaction behind a savepoint: Student (+ Customer, via Education's own
Student hooks), Program Enrollment (submitted, regulation assigned by the campus hook), register and roll
numbers, the fee Sales Invoice, the applicant's Admitted status and the student's lifecycle (Admitted, then Joined
and Active on the enrollment; M05-09). Any failure rolls back to the savepoint
and re-raises, so nothing half-created remains. The one exception is the Aadhaar "admission copy" log row,
which is committed on its own connection by design (an audit row for a number that was read).
"""

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import add_days, today

from campus.admissions import documents, numbers
from campus.admissions import seat_matrix as seats
from campus.admissions.aadhaar import copy_aadhaar
from campus.admissions.setup import OFFICER_ROLE
from campus.campus_finance.api import fee_structure_for
from campus.campus_platform.company_scope import permitted_companies
from campus.student_services.api import ACTIVE, ADMITTED, JOINED, create_onboarding, transition

SAVEPOINT = "campus_admit"


def admit(applicant):
	"""See `campus.admissions.api.admit`.

	A deadlock (MariaDB aborts one of two admissions that lock against each other, e.g. over the naming series or
	the Program Enrollment index gaps) rolls the transaction back; the admission is attempted once more and
	then reported as busy. The abort is fail closed: nothing was admitted.
	"""
	frappe.only_for(OFFICER_ROLE)
	for _attempt in range(2):
		try:
			return admit_once(applicant)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
	frappe.throw(_("The admission desk is busy. Please try admitting {0} again.").format(applicant))


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
	"""The applicant's decisive fields, read with a locking read: a second Admit of the same applicant waits and then sees Admitted."""
	fields = ["application_status", "oc_eligibility_status", "oc_company", "program", "academic_year", "oc_admission_quota", "student_category"]
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
	if state.oc_eligibility_status != "Eligible":
		frappe.throw(_("Applicant {0} is not Eligible ({1}).").format(applicant, state.oc_eligibility_status))
	if not documents.documents_complete(applicant):
		frappe.throw(_("Applicant {0} has incomplete mandatory documents.").format(applicant))
	if not state.program or not state.oc_admission_quota or not state.student_category:
		frappe.throw(_("Applicant {0} needs a program, an admission quota and a student category.").format(applicant))


def create_admission(applicant, state):
	year = state.academic_year or frappe.db.get_single_value("Admission Settings", "active_admission_year")
	if not year:
		frappe.throw(_("Set the applicant's academic year or the active admission year in Admission Settings."))
	seats.check_seat_available(state.program, year, state.oc_admission_quota, state.student_category, applicant)
	source = frappe.get_doc("Student Applicant", applicant)
	student = create_student(source, state, year)
	enrollment = create_enrollment(student, source, state, year)
	record_joining(student, enrollment)
	invoice = create_fee_invoice(student, enrollment, state, year)
	create_onboarding(student.name)
	frappe.db.set_value("Student Applicant", applicant, "application_status", "Admitted")
	return {
		"student": student.name, "program_enrollment": enrollment.name, "invoice": invoice.name,
		"register_no": student.oc_register_no,
	}


def create_student(source, state, year):
	"""Education's applicant-to-student mapping, plus company, numbers and the Aadhaar copy."""
	student = get_mapped_doc(
		"Student Applicant", source.name,
		{"Student Applicant": {"doctype": "Student", "field_map": {"name": "student_applicant"}}},
		ignore_permissions=True,
	)  # fmt: skip
	settings = frappe.get_doc("Admission Settings")
	student.oc_company = state.oc_company
	student.oc_academic_status = ADMITTED
	student.joining_date = today()
	student.oc_admission_quota = state.oc_admission_quota
	student.oc_lateral_entry = int(source.oc_admission_type == "Lateral")
	student.oc_register_no = numbers.next_number(settings.register_no_pattern, state.oc_company, state.program, year)
	if settings.roll_no_pattern:
		student.oc_roll_no = numbers.next_number(settings.roll_no_pattern, state.oc_company, state.program, year)
	copy_aadhaar(source, student)
	return student.insert(ignore_permissions=True)


def create_enrollment(student, source, state, year):
	enrollment = frappe.get_doc(
		{
			"doctype": "Program Enrollment", "student": student.name, "program": state.program, "academic_year": year,
			"academic_term": source.academic_term, "enrollment_date": today(), "student_category": state.student_category,
			"oc_admission_quota": state.oc_admission_quota,
		}
	)  # fmt: skip
	enrollment.insert(ignore_permissions=True)
	return enrollment.submit()


def record_joining(student, enrollment):
	"""Lifecycle (M05-09): admitted with the Student record, joined and active with the enrollment."""
	for status in (JOINED, ACTIVE):
		transition(student.name, status, enrollment.enrollment_date, _("Enrolled on admission"), enrollment, program_enrollment=enrollment.name)


def create_fee_invoice(student, enrollment, state, year):
	"""Submitted Sales Invoice from the quota/category Fee Structure, flagged with the admission's enrollment."""
	name = fee_structure_for(state.program, year, state.oc_admission_quota, state.student_category, state.oc_company)
	if not name:
		frappe.throw(_("No Fee Structure for {0}, {1}, {2} / {3}.").format(state.program, year, state.oc_admission_quota, state.student_category))
	structure = frappe.get_doc("Fee Structure", name)
	customer = frappe.db.get_value("Student", student.name, "customer")
	invoice = frappe.get_doc(
		{
			"doctype": "Sales Invoice", "company": structure.company,
			"selling_price_list": frappe.db.get_single_value("Selling Settings", "selling_price_list"), "customer": customer, "student": student.name,
			"posting_date": today(), "due_date": add_days(today(), 30), "debit_to": structure.receivable_account,
			"oc_program_enrollment": enrollment.name,
			"items": [
				{"item_code": row.item, "qty": 1, "price_list_rate": row.amount, "discount_percentage": row.discount, "cost_center": structure.cost_center}
				for row in structure.components
			],
		}
	)  # fmt: skip
	invoice.flags.ignore_permissions = True  # the officer's role was checked in admit(); every input is server-side
	invoice.insert()
	return invoice.submit()
