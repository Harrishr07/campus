"""M07-03 Faculty portal: /campus-portal/faculty, my timetable (own and substituted periods) for a week."""

import frappe

from campus.faculty import portal

no_cache = 1


def get_context(context):
	if not portal.page_context(context, "timetable"):
		return
	context.timetable = portal.my_timetable(frappe.form_dict.get("from_date"))
