"""M16-01 / M16-02 Messaging bus: every module notifies through `send`.

Recipient formats: see campus.campus_messaging.recipients. Consent rules: see ...consent.
"""

import json

import frappe
from frappe import _

from campus.campus_messaging import consent, delivery, quiet_hours, rendering
from campus.campus_messaging import recipients as recipient_lookup
from campus.campus_messaging.channels import ADDRESS_FIELD

DISPATCH = "campus.campus_messaging.delivery.dispatch_log"


def send(event_key, doc, recipients, context=None, now=False):
	"""Send the template for `event_key` about `doc` to each recipient; returns Message Log names.

	Per recipient the template's channels are tried in the fallback order of Messaging Settings, skipping
	channels without an address or consent; every attempt gets a Message Log. A repeat call for the same
	(event, doc, recipient) while an earlier attempt is live is a no-op returning that attempt's logs. Distinct repeat events about
	the same doc (e.g. successive approval levels) pass a different context['dedupe_token'].
	Sending runs in a background job (inline when `now` or under tests).
	"""
	template = _get_template(event_key)
	settings = frappe.get_single("Messaging Settings")
	names = []
	for recipient in recipients or []:
		names += _send_to(template, settings, doc, recipient_lookup.resolve(recipient), context, now)
	return names


def _get_template(event_key):
	if not frappe.db.get_value("Message Template", event_key, "enabled"):
		frappe.throw(_("No enabled Message Template for event {0}").format(event_key))
	return frappe.get_cached_doc("Message Template", event_key)


def _send_to(template, settings, doc, entry, context, now):
	token = (context or {}).get("dedupe_token", "")
	existing = delivery.existing_logs(template.event_key, doc, entry["key"], token)
	if existing:
		return existing
	eligible, skipped = plan_channels(template, settings, entry)
	subject, message, variables = rendering.render(template, entry["language"], doc, context, entry)
	names = [
		delivery.create_log(
			template, doc, entry, channel, None, subject, message, variables, status="Skipped", error=reason
		).name
		for channel, reason in skipped
	]
	if not eligible:
		return names
	(channel, address), rest = eligible[0], eligible[1:]
	release = None if template.urgent else quiet_hours.current_release_time(settings)
	extra = {"send_after": release} if release else {}
	log = delivery.create_log(
		template,
		doc,
		entry,
		channel,
		address,
		subject,
		message,
		variables,
		status="Scheduled" if release else "Queued",
		token=token,
		fallback_channels=json.dumps([{"channel": c, "address": a} for c, a in rest]),
		**extra,
	)
	if not log:  # a concurrent send took the key
		return names + delivery.existing_logs(template.event_key, doc, entry["key"], token)
	if not release:
		frappe.enqueue(DISPATCH, queue="short", enqueue_after_commit=True, now=now or frappe.in_test, name=log.name)
	return [*names, log.name]


def plan_channels(template, settings, entry):
	"""Split the template's channels, in fallback order, into eligible [(channel, address)] and skipped [(channel, reason)].

	A channel the recipient has no address for is skipped silently (not an attempt) unless nothing else
	is eligible or consent-skipped, so the recipient still leaves one log explaining why nothing was sent.
	"""
	order = [row.channel for row in settings.channel_order]
	channels = sorted((row.channel for row in template.channels), key=lambda c: order.index(c) if c in order else len(order))
	eligible, skipped, unaddressed = [], [], []
	for channel in channels:
		address = entry[ADDRESS_FIELD[channel]]
		if not address:
			unaddressed.append((channel, _("No address for {0}").format(channel)))
		elif not consent.is_allowed(entry["party_type"], entry["party"], channel, template.purpose):
			skipped.append((channel, _("Recipient has not consented to {0} {1} messages").format(template.purpose, channel)))
		else:
			eligible.append((channel, address))
	if not eligible and not skipped:
		skipped = unaddressed
	return eligible, skipped


def audience_members(rule):
	"""Recipients ("Doctype:name") of an Audience Rule, a saved name or an unsaved document."""
	from campus.campus_messaging.audience import resolve

	return resolve(rule)


def recipient_keys_for_user(user):
	"""Every recipient key ("Doctype:name") a user answers to: the user and their Student / Guardian / Employee records."""
	from campus.campus_messaging.audience import keys_for_user

	return keys_for_user(user)
