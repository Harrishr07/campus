"""M16-02 Delivery Summary: Message Logs counted by event, channel and status.

Limited to the companies the user is permitted for (User Permission on Company); a Company filter narrows further.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Count

from campus.campus_messaging.report_scope import scoped_companies


def execute(filters=None):
	return columns(), data(frappe._dict(filters or {}))


def columns():
	return [
		{"fieldname": "event_key", "label": _("Event"), "fieldtype": "Data", "width": 200},
		{"fieldname": "channel", "label": _("Channel"), "fieldtype": "Data", "width": 100},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "count", "label": _("Messages"), "fieldtype": "Int", "width": 100},
	]


def data(filters):
	log = frappe.qb.DocType("Message Log")
	query = (
		frappe.qb.from_(log)
		.select(log.event_key, log.channel, log.status, Count(log.name).as_("count"))
		.groupby(log.event_key, log.channel, log.status)
		.orderby(log.event_key)
		.orderby(log.channel)
		.orderby(log.status)
	)
	companies = scoped_companies(filters.company)
	if companies is not None:
		query = query.where(log.company.isin(companies or [""]))
	for fieldname in ("event_key", "channel", "status"):
		if filters.get(fieldname):
			query = query.where(log[fieldname] == filters[fieldname])
	if filters.from_date:
		query = query.where(log.creation >= filters.from_date)
	if filters.to_date:
		query = query.where(log.creation < frappe.utils.add_days(filters.to_date, 1))
	return query.run(as_dict=True)
