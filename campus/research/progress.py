"""M08-08 Progress reports and mid-term reviews of a sanctioned project on ERPNext Project Update (no new DocType).

A Project Update of a sanction's project is a report to the agency: its type (Progress Report or Mid-term Review), the
period it covers (inside the sanction period), the milestones (the project's milestone Tasks with their status, filled
on every save) and the deliverables. Updates of other projects are left as ERPNext has them."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import getdate

REPORT_TYPES = ("Progress Report", "Mid-term Review")


def progress_fields():
	return {
		"Project Update": [
			{"fieldname": "oc_sanction", "label": "Sanction", "fieldtype": "Link", "options": "Sanction", "insert_after": "project",
			 "read_only": 1, "in_standard_filter": 1},
			{"fieldname": "oc_report_type", "label": "Report Type", "fieldtype": "Select", "options": "\n" + "\n".join(REPORT_TYPES),
			 "insert_after": "oc_sanction", "description": "Required on a sanctioned project's update."},
			{"fieldname": "oc_from_date", "label": "Period From", "fieldtype": "Date", "insert_after": "oc_report_type"},
			{"fieldname": "oc_to_date", "label": "Period To", "fieldtype": "Date", "insert_after": "oc_from_date"},
			{"fieldname": "oc_progress_section", "label": "Progress", "fieldtype": "Section Break", "insert_after": "time"},
			{"fieldname": "oc_milestones", "label": "Milestones", "fieldtype": "Small Text", "read_only": 1,
			 "insert_after": "oc_progress_section", "description": "The project's milestone tasks and their status."},
			{"fieldname": "oc_deliverables", "label": "Deliverables", "fieldtype": "Text Editor", "insert_after": "oc_milestones"},
		]
	}  # fmt: skip


def setup_progress_fields():
	create_custom_fields(progress_fields(), update=True)


def validate_project_update(doc, method=None):
	"""validate of Project Update: a sanctioned project's update is a report with a type and a period in the sanction."""
	sanction = frappe.db.get_value(
		"Sanction", {"project": doc.project, "docstatus": 1}, ["name", "start_date", "end_date"], as_dict=True
	)
	doc.oc_sanction = sanction.name if sanction else None
	if not sanction:
		return
	if doc.oc_report_type not in REPORT_TYPES:
		frappe.throw(_("Select the report type of this update of Sanction {0}'s project.").format(sanction.name))
	if not doc.oc_from_date or not doc.oc_to_date:
		frappe.throw(_("Enter the period the report covers."))
	if getdate(doc.oc_from_date) > getdate(doc.oc_to_date):
		frappe.throw(_("The period can't end before it starts."))
	if getdate(doc.oc_from_date) < getdate(sanction.start_date) or getdate(doc.oc_to_date) > getdate(sanction.end_date):
		frappe.throw(
			_("The period must be inside the sanction period ({0} to {1}).").format(
				frappe.format(sanction.start_date, "Date"), frappe.format(sanction.end_date, "Date")
			)
		)
	doc.oc_milestones = milestone_summary(doc.project)


def milestone_summary(project):
	lines = []
	for task in frappe.get_all(
		"Task", {"project": project, "is_milestone": 1}, ["subject", "status", "exp_end_date"], order_by="exp_end_date, creation"
	):
		due = _(" (due {0})").format(frappe.format(getdate(task.exp_end_date), "Date")) if task.exp_end_date else ""
		lines.append(f"{task.subject}: {_(task.status)}{due}")
	return "\n".join(lines)
