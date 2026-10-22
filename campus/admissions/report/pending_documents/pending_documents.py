"""M04-03 Pending Documents: mandatory documents not yet complete for applicants still in the pipeline.

Limited to the companies the user is permitted for (User Permissions apply to the applicant list).
"""

import frappe
from frappe import _

from campus.admissions.documents import OPEN_STATUSES
from campus.campus_platform.company_scope import permitted_companies

INCOMPLETE = ("Pending", "Rejected", "Submitted")  # Submitted still needs verification where the rule says so


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "applicant", "label": _("Applicant"), "fieldtype": "Link", "options": "Student Applicant", "width": 150},
		{"fieldname": "applicant_name", "label": _("Name"), "fieldtype": "Data", "width": 160},
		{"fieldname": "program", "label": _("Program"), "fieldtype": "Link", "options": "Program", "width": 180},
		{"fieldname": "quota", "label": _("Quota"), "fieldtype": "Link", "options": "Admission Quota", "width": 110},
		{"fieldname": "document_type", "label": _("Document"), "fieldtype": "Data", "width": 180},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 90},
		{"fieldname": "remarks", "label": _("Remarks"), "fieldtype": "Data", "width": 200},
	]


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	conditions = {"oc_company": filters.company, "application_status": ("in", OPEN_STATUSES)}
	for field, column in (("program", "program"), ("academic_year", "academic_year"), ("quota", "oc_admission_quota")):
		if filters.get(field):
			conditions[column] = filters[field]
	applicants = frappe.get_list(
		"Student Applicant", filters=conditions, fields=["name", "title", "program", "oc_admission_quota"], limit=0
	)
	by_name = {a.name: a for a in applicants}
	documents = frappe.get_all(
		"Applicant Document",
		{"parent": ("in", list(by_name) or [""]), "parenttype": "Student Applicant", "mandatory": 1, "status": ("in", INCOMPLETE)},
		["parent", "document_type", "status", "remarks", "verification_needed"],
		order_by="parent, idx",
		limit=0,
	)
	rows = []
	for doc in documents:
		if doc.status == "Submitted" and not doc.verification_needed:
			continue  # complete
		applicant = by_name[doc.parent]
		rows.append(
			{
				"applicant": doc.parent, "applicant_name": applicant.title, "program": applicant.program,
				"quota": applicant.oc_admission_quota, "document_type": doc.document_type, "status": doc.status, "remarks": doc.remarks,
			}
		)  # fmt: skip
	return rows
