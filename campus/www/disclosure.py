"""M01-01 Public disclosure: /disclosure (public evidence by year and type) and /disclosure/<slug> (route rule in hooks).

Guest accessible. /disclosure/<slug> redirects (302, the file can change) to the current public file of a public Evidence; a URL evidence is
never redirected off this site, it gets a small page showing the link. An unknown slug, a non-public Evidence and a private
file all give the same 404, so slugs cannot be enumerated.
"""

import frappe
from frappe import _
from frappe.utils import cstr

from campus.iqac.evidence import public_listing, public_target

no_cache = 1
GROUPS_TEMPLATE = "campus/templates/includes/disclosure_groups.html"
EXTERNAL_TEMPLATE = "campus/templates/includes/disclosure_external.html"


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	slug = cstr(frappe.form_dict.get("slug"))
	if slug:
		target = public_target(slug)
		if not target:
			raise frappe.PageDoesNotExistError
		if frappe.db.get_value("Evidence", slug, "kind") == "URL":
			context.title = frappe.db.get_value("Evidence", slug, "title")
			context.external_url = target
			context.external_html = frappe.render_template(EXTERNAL_TEMPLATE, {"title": context.title, "external_url": target})
			return
		frappe.local.flags.redirect_location = target
		raise frappe.Redirect(302)
	context.title = _("Public disclosure")
	context.groups = public_listing()
	context.groups_html = frappe.render_template(GROUPS_TEMPLATE, {"groups": context.groups})
