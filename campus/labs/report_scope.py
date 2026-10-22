"""M12 Company scoping of the lab script reports."""

import frappe

from campus.campus_platform.company_scope import permitted_companies


def scoped_companies(company=None):
	"""Companies a report may read: None when unrestricted, else a list (empty when nothing is permitted).

	The user's Company User Permissions always apply; a `company` filter narrows within them.
	"""
	allowed = permitted_companies(frappe.session.user)
	if not company:
		return allowed
	if allowed is not None and company not in allowed:
		return []
	return [company]
