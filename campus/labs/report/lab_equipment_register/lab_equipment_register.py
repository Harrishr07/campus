"""M12-01 Lab Equipment Register (NBA): the equipment of each laboratory, limited to the companies the user may read."""

import frappe
from frappe import _

from campus.labs.report_scope import scoped_companies
from campus.labs.equipment import lab_equipment


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), lab_equipment(scoped_companies(filters.company), filters.laboratory)


def columns():
	return [
		{"fieldname": "laboratory", "label": _("Laboratory"), "fieldtype": "Link", "options": "Laboratory", "width": 180},
		{"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 160},
		{"fieldname": "asset", "label": _("Asset"), "fieldtype": "Link", "options": "Asset", "width": 140},
		{"fieldname": "asset_name", "label": _("Equipment"), "fieldtype": "Data", "width": 200},
		{"fieldname": "asset_category", "label": _("Category"), "fieldtype": "Link", "options": "Asset Category", "width": 140},
		{"fieldname": "purchase_date", "label": _("Purchased"), "fieldtype": "Date", "width": 100},
		{"fieldname": "net_purchase_amount", "label": _("Cost"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
	]  # fmt: skip
