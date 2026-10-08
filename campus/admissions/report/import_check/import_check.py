"""M17-07 Import Check: pre-import validation of the file on a Data Import (see campus.admissions.legacy_import).

Limited to the companies the user is permitted for; Aadhaar numbers appear masked only.
"""

import frappe
from frappe import _

from campus.admissions.legacy_import import validate_import


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), validate_import(filters.data_import, filters.template, filters.company)


def columns():
	return [
		{"fieldname": "row", "label": _("Sheet Row"), "fieldtype": "Int", "width": 90},
		{"fieldname": "column", "label": _("Column"), "fieldtype": "Data", "width": 180},
		{"fieldname": "check", "label": _("Check"), "fieldtype": "Data", "width": 150},
		{"fieldname": "message", "label": _("Message"), "fieldtype": "Data", "width": 480},
	]
