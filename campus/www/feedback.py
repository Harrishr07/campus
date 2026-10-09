"""M01-05 /feedback/<campaign>: answer a Feedback Campaign (route rule in hooks).

Students, parents and staff answer when logged in; invited alumni and employers answer by their signed link
(?member=&signature=) without a login. An unknown campaign, a bad link and a campaign not addressed to the user all show
the same notice, so the page tells nobody who else was invited.
"""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cstr

from campus.iqac import feedback
from campus.iqac.doctype.feedback_form.feedback_form import choice_options

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	context.title = _("Feedback")
	name, member, signature = (cstr(frappe.form_dict.get(k)) for k in ("campaign", "member", "signature"))
	if frappe.session.user == "Guest" and not member:
		frappe.local.flags.redirect_location = f"/login?redirect-to={quote(f'/feedback/{name}')}"
		raise frappe.Redirect
	context.member, context.signature, context.state = member, signature, "denied"
	campaign = frappe.db.exists("Feedback Campaign", name) and frappe.get_doc("Feedback Campaign", name)
	if not campaign:
		return
	try:
		key = feedback.respondent_key(campaign, member or None, signature or None)
	except frappe.PermissionError:
		frappe.clear_last_message()
		return
	context.title, context.campaign = campaign.campaign_title, campaign.name
	context.is_anonymous = campaign.is_anonymous
	if feedback.has_responded(campaign.name, key):
		context.state = "answered"
	elif not feedback.is_open(campaign):
		context.state = "closed"
	else:
		context.state = "open"
		context.questions = [
			frappe._dict(name=q.name, question=q.question, question_type=q.question_type, is_required=q.is_required, options=choice_options(q))
			for q in frappe.get_doc("Feedback Form", campaign.form).questions
		]
