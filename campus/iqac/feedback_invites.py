"""M01-05 Feedback invitations and reminders, sent through messaging (`send`) by the bulk runner.

Reminders go to everyone the campaign addresses, answered or not: choosing only those who have not answered would put
the set of respondents, day by day, into the Message Log, which with the response day could tell who wrote what.
"""

from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.utils import cint, get_url, getdate, today

from campus.campus_messaging.api import send
from campus.campus_platform.bulk import run_bulk
from campus.iqac import feedback

INVITATION, REMINDER = "Feedback Invitation", "Feedback Reminder"
HANDLER = "campus.iqac.feedback_invites.send_one"


def send_invitations(campaign_name):
	"""Queue the invitation of every respondent of the campaign; returns the Bulk Run name."""
	campaign = frappe.get_doc("Feedback Campaign", campaign_name)
	feedback.check_audience_size(campaign, feedback.respondents(campaign))
	run = queue(campaign, INVITATION, "invitation")
	if not run:
		frappe.throw(_("Nobody is addressed by this campaign yet."))
	frappe.db.set_value("Feedback Campaign", campaign.name, "invitations_sent", 1)
	return run


def send_reminders():
	"""Daily: remind the audience of each open campaign whose reminder falls today; returns the Bulk Run names."""
	runs = []
	for row in frappe.get_all(
		"Feedback Campaign",
		{"start_date": ["<", today()], "end_date": [">=", today()], "reminder_every_days": [">", 0]},
		["name", "start_date", "reminder_every_days"],
	):
		if reminder_due(row.start_date, row.reminder_every_days, today()):
			run = queue(frappe.get_doc("Feedback Campaign", row.name), REMINDER, f"reminder-{today()}")
			if run:
				runs.append(run)
	return runs


def reminder_due(start_date, every_days, day):
	"""True on every `every_days`-th day after the start (never on the start day itself)."""
	every, elapsed = cint(every_days), (getdate(day) - getdate(start_date)).days
	return every > 0 and elapsed > 0 and elapsed % every == 0


def queue(campaign, event_key, dedupe_token):
	"""A bulk run sending `event_key` to the campaign's audience; None when nobody is addressed, or the campaign is
	anonymous with an audience below the minimum group size (it takes no answers)."""
	recipients = feedback.respondents(campaign)
	if not recipients or feedback.too_small(campaign, recipients):
		return None
	parameters = {"campaign": campaign.name, "event_key": event_key, "dedupe_token": dedupe_token}
	return run_bulk(f"{event_key} {campaign.name}", recipients, HANDLER, parameters=parameters)


def send_one(recipient, run):
	"""Bulk run handler: one invitation or reminder, with the recipient's own link."""
	parameters = frappe.parse_json(run.parameters)
	campaign = frappe.get_doc("Feedback Campaign", parameters["campaign"])
	context = {"link": link(campaign, recipient), "dedupe_token": parameters["dedupe_token"]}
	send(parameters["event_key"], campaign, [recipient], context)


def link(campaign, recipient):
	"""The answer page; an invited member's link carries the signature that admits them without a login."""
	path = f"/feedback/{campaign.name}"
	if recipient.startswith("External Member:"):
		member = recipient.partition(":")[2]
		path += "?" + urlencode(
			{"member": member, "signature": feedback.invite_signature(campaign.name, recipient)}
		)
	return get_url(path)
