"""M06-08 Faculty portal: /campus-portal/faculty/cia, CIA marks of the teacher's own Mark Sheet Entries.
Posted to campus.faculty.portal.save_cia_marks; the Mark Sheet Entry controller applies the CIA lock."""

import frappe

from campus.faculty import portal

no_cache = 1


def get_context(context):
	if not portal.page_context(context, "cia"):
		return
	mark_sheet = frappe.form_dict.get("mark_sheet")
	context.sheet = portal.cia_sheet(mark_sheet) if mark_sheet else None
	if not context.sheet:
		context.sheets = portal.my_mark_sheets()
