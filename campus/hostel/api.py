"""M10-01 Hostel service API. Other modules call these, never the controllers (D7)."""

import frappe
from frappe import _

from campus.campus_platform.api import served_companies
from campus.hostel.rules import gender_allowed

SERVICE = "Hostel"


def served_colleges(hostel):
	"""Colleges the hostel's owner serves under its Hostel Shared Service Agreements in force today."""
	return served_companies(SERVICE, frappe.db.get_value("Hostel", hostel, "company"))


def validate_allotment(hostel, student):
	"""Throw unless `student` (Student name) may be allotted in `hostel`: same gender, college served."""
	gender = frappe.db.get_value("Student", student, "gender")
	if not gender_allowed(frappe.db.get_value("Hostel", hostel, "gender"), gender):
		frappe.throw(_("{0} cannot take a student of gender {1}").format(hostel, gender or _("not set")))
	company = frappe.db.get_value("Student", student, "oc_company")
	if company not in served_colleges(hostel):
		frappe.throw(_("{0} does not serve {1}").format(hostel, company))


def fee_rate(company, academic_year, room_type):
	"""{fee category: amount} for the room type in the academic year, or {} when no rate is set."""
	name = frappe.db.exists("Hostel Fee Rate", {"company": company, "academic_year": academic_year, "room_type": room_type})
	if not name:
		return {}
	rows = frappe.get_all("Hostel Fee Rate Item", filters={"parent": name}, fields=["fee_category", "amount"])
	return {row.fee_category: row.amount for row in rows}


def add_beds(room, count):
	"""Add `count` active beds to `room`, numbered after the highest existing number; returns their names."""
	existing = frappe.get_all("Hostel Bed", filters={"room": room}, pluck="bed_no")
	start = max((int(n) for n in existing if str(n).isdigit()), default=0)
	beds = []
	for number in range(start + 1, start + 1 + int(count)):
		beds.append(frappe.get_doc({"doctype": "Hostel Bed", "room": room, "bed_no": str(number)}).insert().name)
	return beds
