"""M17-04 Public verification page: /verify/<code> (route rule in hooks). Guest accessible, rate limited."""

import frappe
from frappe import _
from frappe.utils import format_datetime

from campus.campus_platform.verification import public_lookup

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	code = frappe.form_dict.get("code")
	found = public_lookup(code) if code else None
	if not found:
		raise frappe.PageDoesNotExistError  # Frappe's own 404 page: no data, HTTP 404
	context.found = True
	context.title = _("Document verification")
	context.record = found
	context.issued_on = format_datetime(found.issued_on, "dd MMM yyyy")
	context.revoked_on = format_datetime(found.revoked_on, "dd MMM yyyy") if found.revoked_on else None
