"""M16-01 Channel adapters: a registry of `adapter(log, template) -> provider_id`.

An adapter raises ChannelError when the message could not be handed to the provider; the caller logs
the failure and moves to the next channel. Tests replace entries of ADAPTERS.
"""

import json

import frappe
from frappe import _


class ChannelError(Exception):
	pass


def send_email(log, template):
	queued = frappe.sendmail(
		recipients=[log.address],
		subject=log.subject or template.event_key,
		message=log.message,
		reference_doctype=log.reference_doctype,
		reference_name=log.reference_name,
	)
	return getattr(queued, "name", None)


def send_sms(log, template):
	"""Send through the SMS Settings gateway, adding the DLT template id as the configured parameter."""
	from frappe.core.doctype.sms_settings.sms_settings import (
		get_headers,
		send_request,
		validate_receiver_nos,
	)

	settings = frappe.get_single("SMS Settings")
	if not settings.sms_gateway_url:
		raise ChannelError(_("SMS Settings has no gateway configured"))
	headers = get_headers(settings)
	params = {settings.message_parameter: log.message}
	params.update({row.parameter: row.value for row in settings.parameters if not row.header})
	if template.sms_dlt_template_id:
		dlt_param = frappe.db.get_single_value("Messaging Settings", "sms_dlt_param_name") or "template_id"
		params[dlt_param] = template.sms_dlt_template_id
	params[settings.receiver_parameter] = validate_receiver_nos([log.address])[0]
	try:
		send_request(
			settings.sms_gateway_url,
			params,
			headers,
			settings.use_post,
			headers.get("Content-Type") == "application/json",
		)
	except Exception as e:
		raise ChannelError(str(e)) from e


def send_whatsapp(log, template):
	"""Create an outgoing WhatsApp Message (frappe_whatsapp sends it on insert); returns Meta's message id."""
	message = {
		"doctype": "WhatsApp Message",
		"type": "Outgoing",
		"to": log.address,
		"reference_doctype": log.reference_doctype,
		"reference_name": log.reference_name,
		"content_type": "text",
	}
	if template.whatsapp_template:
		values = json.loads(log.variables or "[]")
		message.update(
			message_type="Template",
			template=template.whatsapp_template,
			body_param=json.dumps({str(i + 1): v for i, v in enumerate(values)}),
		)
	else:
		message.update(message_type="Manual", message=log.message)
	try:
		doc = frappe.get_doc(message).insert(ignore_permissions=True)
	except Exception as e:
		raise ChannelError(str(e)) from e
	return doc.message_id


def send_push(log, template):
	"""Interface stub: push (FCM) is not configured in Phase 1."""
	raise ChannelError(_("Push is not configured"))


ADAPTERS = {"email": send_email, "sms": send_sms, "whatsapp": send_whatsapp, "push": send_push}

# Which resolved-recipient field each channel needs, and which Message Log address it is sent to.
ADDRESS_FIELD = {"email": "email", "sms": "mobile", "whatsapp": "mobile", "push": "user"}


def send_via(channel, log, template):
	adapter = ADAPTERS.get(channel)
	if not adapter:
		raise ChannelError(_("Unknown channel {0}").format(channel))
	return adapter(log, template)
