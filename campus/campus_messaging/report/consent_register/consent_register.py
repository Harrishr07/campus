"""M16-02 Consent Register: every recorded opt-in and opt-out with when and where it came from.

Limited to the companies the user is permitted for (User Permission on Company); a Company filter narrows further.
"""

import frappe
from frappe import _

from campus.campus_messaging.report_scope import scoped_companies


def execute(filters=None):
	return columns(), data(frappe._dict(filters or {}))


def columns():
	return [
		{"fieldname": "party_type", "label": _("Party Type"), "fieldtype": "Data", "width": 100},
		{"fieldname": "party", "label": _("Party"), "fieldtype": "Dynamic Link", "options": "party_type", "width": 160},
		{"fieldname": "channel", "label": _("Channel"), "fieldtype": "Data", "width": 90},
		{"fieldname": "purpose", "label": _("Purpose"), "fieldtype": "Data", "width": 110},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
		{"fieldname": "source", "label": _("Source"), "fieldtype": "Data", "width": 140},
		{"fieldname": "timestamp", "label": _("Recorded At"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 180},
	]


def data(filters):
	conditions = {f: filters[f] for f in ("party_type", "channel", "purpose", "status") if filters.get(f)}
	companies = scoped_companies(filters.company)
	if companies is not None:
		conditions["company"] = ["in", companies or [""]]
	return frappe.get_all(
		"Communication Consent",
		filters=conditions,
		fields=["party_type", "party", "channel", "purpose", "status", "source", "timestamp", "company"],
		order_by="party_type, party, channel, purpose",
	)
