"""M16-03 Circular Acknowledgement Status.

Without a Circular filter: one row per approved circular that needs acknowledgement, with its audience size,
how many have acknowledged and how many are pending. With a Circular filter: one row per recipient showing
whether they acknowledged and when. A recipient counts as acknowledged when their portal user did; a
recipient without a portal user stays pending. The audience is resolved as it is now.

Limited to the companies the user is permitted for (User Permission on Company); a Company filter narrows further.
"""

import frappe
from frappe import _

from campus.campus_messaging import audience
from campus.campus_messaging.report_scope import scoped_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	circulars = visible_circulars(filters)
	if filters.circular:
		return detail_columns(), detail_rows(circulars)
	return summary_columns(), summary_rows(circulars)


def summary_columns():
	return [
		{"fieldname": "circular", "label": _("Circular"), "fieldtype": "Link", "options": "Circular", "width": 150},
		{"fieldname": "title", "label": _("Title"), "fieldtype": "Data", "width": 240},
		{"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 180},
		{"fieldname": "audience", "label": _("Audience"), "fieldtype": "Int", "width": 90},
		{"fieldname": "acknowledged", "label": _("Acknowledged"), "fieldtype": "Int", "width": 110},
		{"fieldname": "pending", "label": _("Pending"), "fieldtype": "Int", "width": 90},
	]


def detail_columns():
	return [
		{"fieldname": "recipient", "label": _("Recipient"), "fieldtype": "Data", "width": 170},
		{"fieldname": "recipient_name", "label": _("Name"), "fieldtype": "Data", "width": 200},
		{"fieldname": "user", "label": _("User"), "fieldtype": "Link", "options": "User", "width": 200},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "acknowledged_on", "label": _("Acknowledged On"), "fieldtype": "Datetime", "width": 160},
	]


def visible_circulars(filters):
	conditions = {"docstatus": 1, "acknowledgement_required": 1}
	if filters.circular:
		conditions["name"] = filters.circular
	companies = scoped_companies(filters.company)
	if companies is not None:
		conditions["company"] = ["in", companies or [""]]
	return frappe.get_all(
		"Circular", filters=conditions, fields=["name", "title", "company", "audience_rule"], order_by="publish_from desc"
	)


def recipient_status(circular):
	"""[{recipient, recipient_name, user, status, acknowledged_on}] for the circular's audience."""
	recipients = audience.resolve(circular.audience_rule)
	people = audience.users_of(recipients)
	acknowledged = {
		row.user: row.acknowledged_on
		for row in frappe.get_all(
			"Circular Acknowledgement", filters={"circular": circular.name}, fields=["user", "acknowledged_on"]
		)
	}
	rows = []
	for key in recipients:
		user, display_name = people.get(key, (None, key))
		when = acknowledged.get(user) if user else None
		rows.append(
			{
				"recipient": key,
				"recipient_name": display_name,
				"user": user,
				"status": _("Acknowledged") if when else _("Pending"),
				"acknowledged_on": when,
			}
		)
	return rows


def summary_rows(circulars):
	rows = []
	for circular in circulars:
		statuses = recipient_status(circular)
		done = sum(1 for r in statuses if r["acknowledged_on"])
		rows.append(
			{
				"circular": circular.name,
				"title": circular.title,
				"company": circular.company,
				"audience": len(statuses),
				"acknowledged": done,
				"pending": len(statuses) - done,
			}
		)
	return rows


def detail_rows(circulars):
	return [row for circular in circulars for row in recipient_status(circular)]
