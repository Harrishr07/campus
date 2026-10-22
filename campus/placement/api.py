"""M14-01, M14-02 Placement service API. Other modules call these, never the controllers (D7)."""

import frappe

from campus.placement import eligibility
from campus.placement.eligibility import evaluate as evaluate_eligibility  # noqa: F401  (public API)

REGISTERED = "Registered"


def registered_students(drive):
	"""Students with a live (not withdrawn) Drive Registration for `drive`."""
	return frappe.get_all("Drive Registration", {"drive": drive, "status": REGISTERED}, pluck="student")


def open_drives(student):
	"""Open Placement Drives of the student's college with their live eligibility and registration state."""
	company = frappe.db.get_value("Student", student, "oc_company")
	rows = []
	for drive in frappe.get_all(
		"Placement Drive", {"company": company, "status": "Open"}, pluck="name", order_by="drive_date"
	):
		doc = frappe.get_doc("Placement Drive", drive)
		registration = frappe.db.get_value("Drive Registration", {"drive": drive, "student": student}, "status")
		rows.append(
			{
				"drive": doc, "registration": registration, "closed": registration_closed(doc),
				**eligibility.evaluate(doc, student),
			}
		)  # fmt: skip
	return rows


def registration_closed(drive):
	return bool(drive.registration_deadline and frappe.utils.get_datetime(drive.registration_deadline) < frappe.utils.now_datetime())
