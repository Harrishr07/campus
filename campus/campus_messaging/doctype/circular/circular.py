"""M16-03 Circular: an approved notice shown to an audience inside a publish window.

Only an approved (submitted) circular whose window is open is visible to its audience (see
campus.campus_messaging.circulars). When it first becomes live, on submit or when the scheduler sees the
window open, the audience is notified through the "circular.published" template. Attachments are the
standard Frappe attachments of the document.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from campus.campus_messaging import audience, bulk_send
from campus.campus_messaging.circulars import check_author_audience
from campus.campus_platform.approvals import ApprovableDocument

EVENT_KEY = "circular.published"


class Circular(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		rule = frappe.get_doc("Audience Rule", self.audience_rule)
		if rule.company != self.company:
			frappe.throw(
				_("Audience Rule {0} belongs to {1}, not {2}.").format(rule.name, rule.company, self.company)
			)
		check_author_audience(rule)
		audience.ensure_available(rule)
		if self.publish_until and get_datetime(self.publish_until) <= get_datetime(self.publish_from):
			frappe.throw(_("Publish Until must be after Publish From."))

	def on_submit(self):
		publish_if_due(self.name)


def publish_if_due(name):
	"""Notify the audience once, when the circular is approved and its window is open."""
	docstatus, published_on = frappe.db.get_value(
		"Circular", name, ["docstatus", "published_on"], for_update=True
	)
	circular = frappe.get_doc("Circular", name)
	if docstatus != 1 or published_on or not is_live(circular):
		return
	frappe.db.set_value("Circular", name, "published_on", now_datetime(), update_modified=False)
	recipients = audience.resolve(circular.audience_rule)
	bulk_send.start(f"Circular {name}", EVENT_KEY, circular, recipients)


def is_live(circular, at=None):
	"""Whether the circular is approved and `at` (default now) is inside its publish window."""
	at = get_datetime(at or now_datetime())
	return (
		circular.docstatus == 1
		and get_datetime(circular.publish_from) <= at
		and (not circular.publish_until or get_datetime(circular.publish_until) > at)
	)


def publish_due():
	"""Scheduler: notify the audience of circulars whose publish time has been reached."""
	due = frappe.get_all(
		"Circular",
		filters={"docstatus": 1, "published_on": ["is", "not set"], "publish_from": ["<=", now_datetime()]},
		pluck="name",
	)
	for name in due:
		try:
			publish_if_due(name)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Circular {name} could not be published")
		frappe.db.commit()
