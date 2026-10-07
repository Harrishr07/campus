"""M05-02 Student Services setup: leave kind and certificate on Student Leave Application, with their submit check."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from campus.student_services.attendance_rules import MEDICAL, ON_DUTY

MODULE = "Student Services"
LEAVE_KINDS = ["Leave", MEDICAL, ON_DUTY]
EVIDENCE_KINDS = (MEDICAL, ON_DUTY)


def setup_student_services():
	"""Create/refresh the Student Leave Application custom fields. Idempotent."""
	create_custom_fields(
		{
			"Student Leave Application": [
				{
					"fieldname": "oc_leave_kind", "fieldtype": "Select", "label": "Leave Kind",
					"options": "\n".join(LEAVE_KINDS), "default": "Leave", "insert_after": "to_date", "reqd": 1,
					"in_list_view": 1, "in_standard_filter": 1, "module": MODULE,
					"description": "Medical and On Duty leave count towards attendance as the Attendance Rule says.",
				},
				{
					"fieldname": "oc_certificate", "fieldtype": "Attach", "label": "Certificate",
					"insert_after": "oc_leave_kind", "module": MODULE,
					"depends_on": "eval:doc.oc_leave_kind != 'Leave'",
					"description": "Medical certificate or On Duty permission letter.",
				},
			]
		},
		update=True,
	)


def require_certificate(doc, method=None):
	"""Doc event (Student Leave Application before_submit): Medical and On Duty leave need their certificate."""
	if doc.oc_leave_kind in EVIDENCE_KINDS and not doc.oc_certificate:
		frappe.throw(_("Attach the certificate for {0} leave before submitting.").format(_(doc.oc_leave_kind)))
