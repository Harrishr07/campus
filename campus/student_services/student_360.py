"""M05-11 Student 360 view: one record of a student across the college, for the desk page (`desk_view`) and a compact
version for the student and guardian on the portal (`portal_view`).

Each desk section is read through the source DocType's own permission (frappe.has_permission, then get_list, so role
permissions, User Permissions on company and the DocType's permission hooks apply) and is left out when the viewer
cannot read the source: a hidden section is absent, never empty. Mentoring shows only the count and names of the
Counselling Notes and Parent Interactions the viewer can read (campus.campus_platform.restricted_records), never their
text. The portal view uses the portal's ownership checks (portal.resolve_student).
"""

import frappe
from frappe import _

from campus.campus_platform.restricted_records import reference_allows
from campus.student_services import corrections, lifecycle
from campus.student_services.mentoring import INTERACTION, NOTE

PROFILE_FIELDS = (
	"student_name", "date_of_birth", "gender", "student_email_id", "student_mobile_number", "oc_company", "oc_batch",
	"oc_register_no", "oc_roll_no", "oc_aadhaar_masked", "oc_mentor", "joining_date", "enabled",
)  # fmt: skip
LIST_LIMIT = 50


def can_read(doctype):
	return bool(frappe.has_permission(doctype, "read"))


def listed(doctype, student, fields, order_by="creation desc", filters=None):
	return frappe.get_list(
		doctype,
		{"student": student, **(filters or {})},
		fields,
		order_by=order_by,
		limit_page_length=LIST_LIMIT,
	)


@frappe.whitelist()
def desk_view(student):
	"""{student, sections: {key: data}} of the sections the session user may read; throws unless they read the Student."""
	frappe.has_permission("Student", "read", doc=student, throw=True)
	sections = {"profile": profile(student)}
	for key, doctypes, build in SECTIONS:
		if any(can_read(doctype) for doctype in doctypes) and (data := build(student)) is not None:
			sections[key] = data
	return {"student": student, "sections": sections}


def profile(student):
	doc = frappe.get_doc("Student", student)
	data = {field: doc.get(field) for field in PROFILE_FIELDS}
	data["guardians"] = [
		{"guardian": row.guardian, "guardian_name": row.guardian_name, "relation": row.relation}
		for row in doc.guardians
	]
	return data


def lifecycle_section(student):
	return {
		"status": lifecycle.current_status(student),
		"history": listed(
			lifecycle.LOG, student,
			["name", "kind", "from_status", "to_status", "effective_date", "reason", "source_doctype", "source_name"],
			order_by="creation asc, name asc",
		),
	}  # fmt: skip


def enrollments_section(student):
	return listed(
		"Program Enrollment",
		student,
		["name", "program", "academic_year", "student_batch_name", "enrollment_date"],
		filters={"docstatus": 1},
	)


def attendance_section(student):
	from campus.student_services.api import student_terms, summarise, term_window

	terms = student_terms(student)
	if not terms:
		return {"academic_term": None, "summary": None}
	try:
		summary = summarise(student, terms[0].name, term_window(terms[0].name), {})
	except frappe.ValidationError:  # e.g. the regulation has no Attendance Rule yet
		summary = None
	return {"academic_term": terms[0].name, "summary": summary}


def results_section(student):
	rows = listed("Student Result", student, ["name", "exam_session", "sgpa", "cgpa", "credits_earned"])
	return {"cgpa": rows[0].cgpa if rows else None, "results": rows}


def fees_section(student):
	"""The invoices the fee ledger counts (campus_finance.ledger.student_invoices), as far as the viewer reads them:
	those of the student, and those made out to the student's Customer with no student set."""
	fields = ["name", "posting_date", "grand_total", "outstanding_amount", "company"]
	scopes = [{"student": student}]
	if customer := frappe.db.get_value("Student", student, "customer"):
		scopes.append({"customer": customer, "student": ["in", ["", None]]})
	rows = [
		row
		for scope in scopes
		for row in frappe.get_list("Sales Invoice", {**scope, "docstatus": 1}, fields, limit_page_length=0)
	]
	rows.sort(key=lambda row: (row.posting_date, row.name), reverse=True)
	return {
		"invoices": rows[:LIST_LIMIT],
		"total_outstanding": sum(row.outstanding_amount or 0 for row in rows),
	}


def certificates_section(student):
	return listed(
		"Certificate Request",
		student,
		["name", "certificate_type", "docstatus", "issued_on", "certificate_number"],
	)


def mentoring_section(student):
	"""Counts and names of the notes and interactions the viewer reads. Nothing else of them is returned."""
	section = {}
	for key, doctype in (("counselling_notes", NOTE), ("parent_interactions", INTERACTION)):
		if can_read(doctype):
			names = [
				n
				for n in frappe.get_list(
					doctype, {"student": student}, pluck="name", limit_page_length=LIST_LIMIT
				)
				if reference_allows(doctype, n, "read")
			]
			section[key] = {"count": len(names), "names": names}
	return section or None


def corrections_section(student):
	return listed(corrections.DOCTYPE, student, ["name", "category", "field_name", "status", "creation"])


# key, DocTypes of which the viewer must read one to see the section, builder. The profile is gated by the Student.
SECTIONS = (
	("lifecycle", (lifecycle.LOG,), lifecycle_section),
	("enrollments", ("Program Enrollment",), enrollments_section),
	("attendance", ("Student Attendance",), attendance_section),
	("results", ("Student Result",), results_section),
	("fees", ("Sales Invoice",), fees_section),
	("certificates", ("Certificate Request",), certificates_section),
	("mentoring", (NOTE, INTERACTION), mentoring_section),
	("corrections", (corrections.DOCTYPE,), corrections_section),
)


@frappe.whitelist()
def portal_view(student=None):
	"""The compact 360 of the student's own record (or a ward's) for the portal; never mentoring, never other students."""
	from campus.student_services import portal

	student = portal.resolve_student(student)
	doc = frappe.get_doc("Student", student)
	history = frappe.get_all(
		lifecycle.LOG,
		{"student": student},
		["kind", "from_status", "to_status", "effective_date"],
		order_by="creation asc, name asc",
	)  # ownership came from resolve_student
	enrollments = frappe.get_all(
		"Program Enrollment",
		{"student": student, "docstatus": 1},
		["program", "academic_year", "enrollment_date"],
		order_by="enrollment_date desc",
	)
	try:
		attendance = portal.get_attendance(student)
	except frappe.ValidationError:
		attendance = {"academic_term": None, "summary": None}
	results = portal.get_results(student)["results"]
	fees = portal.get_fees(student)
	return frappe._dict(
		student=student,
		profile={
			field: doc.get(field)
			for field in ("student_name", "oc_register_no", "oc_roll_no", "oc_batch", "oc_company")
		},
		status=lifecycle.current_status(student),
		history=history,
		enrollments=enrollments,
		attendance=attendance,
		cgpa=results[0]["cgpa"] if results else None,
		total_outstanding=fees["total_outstanding"],
		certificates=portal.my_certificates(student)["certificates"],
		corrections=corrections.my_corrections(student)["corrections"],
	)
