"""M01-01 Public disclosure: /disclosure (public evidence by year and type) and /disclosure/<slug> (route rule in hooks).

Guest accessible. /disclosure/<slug> redirects (302, the file can change) to the current public file or address of a public
Evidence; an unknown slug, a non-public Evidence and a private file all give the same 404, so slugs cannot be enumerated.
"""

import frappe
from frappe import _

from campus.iqac.evidence import public_listing, public_target

no_cache = 1
GROUPS_TEMPLATE = "campus/templates/includes/disclosure_groups.html"


class TemporaryRedirect(frappe.Redirect):
	http_status_code = 302


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	slug = frappe.form_dict.get("slug")
	if slug:
		target = public_target(slug)
		if not target:
			raise frappe.PageDoesNotExistError
		frappe.local.flags.redirect_location = target
		raise TemporaryRedirect
	context.title = _("Public disclosure")
	context.groups = public_listing()
	context.groups_html = frappe.render_template(GROUPS_TEMPLATE, {"groups": context.groups})
