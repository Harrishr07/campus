"""M06-04 Examiner portal: /campus-portal/valuation lists the user's allocated bundles by dummy number only.

Marks are posted to campus.examinations.valuation.submit_marks (POST, ownership-checked there).
"""

from urllib.parse import quote

import frappe

from campus.examinations.valuation import my_allocations

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={quote('/campus-portal/valuation')}"
		raise frappe.Redirect
	context.allocations = my_allocations()
