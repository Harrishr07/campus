"""M14-01 Student portal pages of placement (/campus-portal/placement): open drives with the student's live eligibility,
opt-in registration and withdrawal.

The student comes from the portal's resolve_student (the session user's own student, or a guardian's ward), never from
the request alone. A guardian reads; only the student registers. Eligibility is re-read live by the Drive Registration."""

import frappe
from frappe import _

from campus.placement import api
from campus.student_services.api import is_the_student, resolve_student

REGISTRATION = "Drive Registration"


def require_the_student(student):
	if not is_the_student(student):
		frappe.throw(_("Only the student can register."), frappe.PermissionError)


@frappe.whitelist()
def my_drives(student=None):
	"""Open drives of the student's college with live eligibility, reasons and the student's registration, plus the
	drives they are registered for."""
	student = resolve_student(student)
	drives = [
		{
			"name": row["drive"].name, "drive_title": row["drive"].drive_title, "recruiter": row["drive"].recruiter,
			"drive_date": row["drive"].drive_date, "deadline": row["drive"].registration_deadline,
			"roles": [{"role_title": r.role_title, "ctc": r.ctc} for r in row["drive"].roles],
			"eligible": row["eligible"], "reasons": row["reasons"], "registration": row["registration"],
			"can_register": row["eligible"] and not row["closed"] and row["registration"] != api.REGISTERED,
			"closed": row["closed"],
		}
		for row in api.open_drives(student)
	]  # fmt: skip
	return {"student": student, "can_act": is_the_student(student), "drives": drives}


@frappe.whitelist(methods=["POST"])
def register(drive, student=None):
	"""The student opts in to an open drive; the registration checks the roll, the window and the live criteria."""
	student = resolve_student(student)
	require_the_student(student)
	name = frappe.db.exists(REGISTRATION, {"drive": drive, "student": student})
	if name:
		doc = frappe.get_doc(REGISTRATION, name)
		doc.status = "Registered"
	else:
		doc = frappe.get_doc({"doctype": REGISTRATION, "drive": drive, "student": student})
	doc.flags.ignore_permissions = True  # portal roles hold no right on the doctype; every value is checked server-side
	doc.save() if name else doc.insert()
	return doc.name


@frappe.whitelist(methods=["POST"])
def withdraw(drive, student=None):
	"""The student withdraws their registration (refused once they appear in a round result)."""
	student = resolve_student(student)
	require_the_student(student)
	name = frappe.db.exists(REGISTRATION, {"drive": drive, "student": student, "status": api.REGISTERED})
	if not name:
		frappe.throw(_("You are not registered for this drive."))
	doc = frappe.get_doc(REGISTRATION, name)
	doc.status = "Withdrawn"
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name
