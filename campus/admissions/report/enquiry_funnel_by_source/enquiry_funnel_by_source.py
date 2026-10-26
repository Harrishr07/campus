"""M04-05 Enquiry Funnel by Source: enquiries -> contacted -> applicant -> admitted, per Lead source.

Contacted = the Lead has moved past its initial "Lead" status. Applicant = converted to a Student Applicant.
Admitted = that applicant's status is Admitted. Counts are cumulative per stage. The company filter is required
and limited to the user's permitted companies; Lead User Permissions apply.
"""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies

NO_SOURCE = "Unknown"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Company is required."))
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "source", "label": _("Source"), "fieldtype": "Data", "width": 180},
		{"fieldname": "leads", "label": _("Enquiries"), "fieldtype": "Int", "width": 110},
		{"fieldname": "contacted", "label": _("Contacted"), "fieldtype": "Int", "width": 110},
		{"fieldname": "applicants", "label": _("Applicants"), "fieldtype": "Int", "width": 110},
		{"fieldname": "admitted", "label": _("Admitted"), "fieldtype": "Int", "width": 110},
	]


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	conditions = {"company": filters.company}
	if filters.from_date and filters.to_date:
		conditions["creation"] = ("between", [f"{filters.from_date} 00:00:00", f"{filters.to_date} 23:59:59"])
	elif filters.from_date:
		conditions["creation"] = (">=", f"{filters.from_date} 00:00:00")
	elif filters.to_date:
		conditions["creation"] = ("<=", f"{filters.to_date} 23:59:59")
	leads = frappe.get_list(
		"Lead", filters=conditions, fields=["utm_source", "status", "oc_applicant"], limit=0
	)
	admitted = set(
		frappe.get_all(
			"Student Applicant",
			{
				"name": ("in", [lead.oc_applicant for lead in leads if lead.oc_applicant] or [""]),
				"application_status": "Admitted",
			},
			pluck="name",
			limit=0,
		)
	)
	rows = {}
	for lead in leads:
		row = rows.setdefault(
			lead.utm_source or NO_SOURCE,
			{
				"source": lead.utm_source or NO_SOURCE,
				"leads": 0,
				"contacted": 0,
				"applicants": 0,
				"admitted": 0,
			},
		)
		row["leads"] += 1
		row["contacted"] += lead.status != "Lead" or bool(lead.oc_applicant)
		row["applicants"] += bool(lead.oc_applicant)
		row["admitted"] += lead.oc_applicant in admitted
	return sorted(rows.values(), key=lambda r: r["source"])
