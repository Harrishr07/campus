"""M01-04 Committee Compliance: per committee, meetings held in the period against its Body Type's minimum per year (prorated
to the period, rounded up), and the
composition rules it does not meet. A committee below its minimum is flagged. Limited to the companies the user may read."""

import frappe
from frappe import _

from campus.iqac import committees


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), committees.compliance_rows(filters.company, filters.from_date, filters.to_date)


def columns():
	return [
		{"fieldname": "body", "label": _("Committee"), "fieldtype": "Link", "options": "Body", "width": 240},
		{"fieldname": "body_type", "label": _("Body Type"), "fieldtype": "Link", "options": "Body Type", "width": 180},
		{"fieldname": "required", "label": _("Meetings Required (Period)"), "fieldtype": "Int", "width": 130},
		{"fieldname": "held", "label": _("Meetings Held"), "fieldtype": "Int", "width": 120},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 130},
		{"fieldname": "composition", "label": _("Composition Not Met"), "fieldtype": "Data", "width": 300},
	]  # fmt: skip
