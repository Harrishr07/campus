"""P1-T10 messaging core: rendering, consent table, quiet hours, fallback, idempotency, webhook status."""

from datetime import datetime, time, timedelta
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import now_datetime

from campus.campus_messaging import api, channels, consent, delivery, quiet_hours, recipients, rendering
from campus.campus_messaging.channels import ChannelError
from campus.tests.utils import CampusTestCase

GUARDIAN_PREFIX = "T10 Guardian"


def ok(provider_id):
	return MagicMock(return_value=provider_id)


def failing(message="boom"):
	return MagicMock(side_effect=ChannelError(message))


def adapters(**overrides):
	"""Patch the adapter registry: every channel succeeds unless overridden."""
	registry = {c: ok(f"{c}-id") for c in ("email", "sms", "whatsapp", "push")}
	registry.update(overrides)
	return patch.dict(channels.ADAPTERS, registry)


class TestMessagingUnits(CampusTestCase):
	def test_consent_decision_table(self):
		table = [
			(None, "transactional", True),
			(None, "promotional", False),
			("Opted In", "transactional", True),
			("Opted In", "promotional", True),
			("Opted Out", "transactional", False),
			("Opted Out", "promotional", False),
		]
		for status, purpose, expected in table:
			self.assertEqual(consent.decide(status, purpose), expected, (status, purpose))

	def test_quiet_hours_window_spanning_midnight(self):
		start, end = time(21), time(7)
		day = datetime(2026, 10, 4)
		self.assertEqual(quiet_hours.release_time(day.replace(hour=22), start, end), datetime(2026, 10, 5, 7))
		self.assertEqual(quiet_hours.release_time(day.replace(hour=3), start, end), datetime(2026, 10, 4, 7))
		self.assertIsNone(quiet_hours.release_time(day.replace(hour=12), start, end))
		self.assertIsNone(quiet_hours.release_time(day.replace(hour=7), start, end))  # end is exclusive

	def test_quiet_hours_same_day_window_and_unset(self):
		day = datetime(2026, 10, 4)
		self.assertEqual(
			quiet_hours.release_time(day.replace(hour=13), time(12), time(14)), day.replace(hour=14)
		)
		self.assertIsNone(quiet_hours.release_time(day.replace(hour=15), time(12), time(14)))
		self.assertIsNone(quiet_hours.release_time(day, None, None))
		self.assertIsNone(quiet_hours.release_time(day, time(8), time(8)))

	def test_render_picks_language_variant_with_english_fallback(self):
		template = frappe.get_doc("Message Template", "fees.due")
		doc = frappe._dict(doctype="Fees", name="FEE-1")
		_s, en, _v = rendering.render(template, "en", doc, {"amount": "500"}, {"display_name": "Asha"})
		_s, ta, _v = rendering.render(template, "ta", doc, {"amount": "500"}, {"display_name": "Asha"})
		_s, hi, _v = rendering.render(template, "hi", doc, {"amount": "500"}, {"display_name": "Asha"})
		self.assertIn("Dear Asha", en)
		self.assertIn("500", en)
		self.assertIn("அன்புள்ள", ta)
		self.assertEqual(hi, en)

	def test_render_whatsapp_variables_are_ordered_expressions(self):
		template = frappe._dict(
			variables="doc.name\ncontext.amount", bodies=[frappe._dict(language="en", subject="", body="x")]
		)
		*_, variables = rendering.render(template, "en", frappe._dict(name="F1"), {"amount": 5}, {})
		self.assertEqual(variables, ["F1", "5"])

	def test_recipient_formats(self):
		self.assertEqual(recipients.parse({"doctype": "Guardian", "name": "G1"}), ("Guardian", "G1"))
		self.assertEqual(recipients.parse("User:a@b.com"), ("User", "a@b.com"))
		self.assertEqual(recipients.resolve("phone:+919800000000")["mobile"], "+919800000000")
		with self.assertRaises(frappe.ValidationError):
			recipients.parse("nonsense")

	def test_push_adapter_is_a_stub(self):
		with self.assertRaisesRegex(ChannelError, "not configured"):
			channels.send_push(frappe._dict(), frappe._dict())

	def test_sms_adapter_sends_dlt_id_as_configured_param(self):
		frappe.db.set_single_value(
			"SMS Settings",
			{
				"sms_gateway_url": "https://sms.invalid/send",
				"message_parameter": "msg",
				"receiver_parameter": "to",
			},
		)
		frappe.db.set_single_value("Messaging Settings", "sms_dlt_param_name", "dlt_te_id")
		template = frappe._dict(sms_dlt_template_id="1107123", event_key="fees.due")
		log = frappe._dict(address="+91 98000-00000", message="Hello")
		with patch("frappe.core.doctype.sms_settings.sms_settings.send_request") as send_request:
			channels.send_sms(log, template)
		params = send_request.call_args.args[1]
		self.assertEqual(
			(params["msg"], params["to"], params["dlt_te_id"]), ("Hello", "+919800000000", "1107123")
		)


class TestMessagingSend(CampusTestCase):
	def setUp(self):
		self.cleanup()
		self.addCleanup(self.cleanup)
		settings = frappe.get_single("Messaging Settings")
		settings.quiet_hours_start = settings.quiet_hours_end = None
		settings.save()
		self.guardian = self.make_guardian("A")
		self.doc = frappe.get_doc({"doctype": "ToDo", "description": "T10 fee"}).insert()

	@staticmethod
	def cleanup():
		for dt in ("Message Log", "Communication Consent"):
			frappe.db.delete(dt)
		frappe.db.delete("Message Template", {"event_key": ("like", "t10.%")})
		frappe.db.delete("Guardian", {"guardian_name": ("like", f"{GUARDIAN_PREFIX}%")})
		frappe.db.delete("ToDo", {"description": "T10 fee"})

	def make_guardian(self, suffix, language=None, mobile="+919800000001", email="t10@example.com"):
		return frappe.get_doc(
			{
				"doctype": "Guardian",
				"guardian_name": f"{GUARDIAN_PREFIX} {suffix}",
				"mobile_number": mobile,
				"email_address": email,
				"oc_language": language or "en",
			}
		).insert()

	def make_template(self, key, purpose="transactional", urgent=0, channel_list=("whatsapp", "sms")):
		return frappe.get_doc(
			{
				"doctype": "Message Template",
				"event_key": key,
				"purpose": purpose,
				"urgent": urgent,
				"channels": [{"channel": c} for c in channel_list],
				"bodies": [{"language": "en", "subject": "S", "body": "Hi {{ doc.name }}"}],
			}
		).insert()

	def logs(self, **filters):
		return frappe.get_all(
			"Message Log",
			filters=filters,
			fields=["name", "channel", "status", "error", "recipient"],
			order_by="creation, name",
		)

	def send_fees(self, **kwargs):
		return api.send(
			"fees.due",
			self.doc,
			[{"doctype": "Guardian", "name": self.guardian.name}],
			{"amount": "900"},
			now=True,
			**kwargs,
		)

	def test_fees_due_goes_out_on_whatsapp(self):
		with adapters():
			names = self.send_fees()
		self.assertEqual([(l.channel, l.status) for l in self.logs()], [("whatsapp", "Sent")])
		self.assertEqual(len(names), 1)
		self.assertEqual(frappe.db.get_value("Message Log", names[0], "provider_id"), "whatsapp-id")

	def test_whatsapp_failure_falls_back_to_sms_and_logs_both_attempts(self):
		with adapters(whatsapp=failing("meta down")):
			self.send_fees()
		self.assertEqual(
			[(l.channel, l.status) for l in self.logs()], [("whatsapp", "Failed"), ("sms", "Sent")]
		)
		self.assertIn("meta down", self.logs(channel="whatsapp")[0].error)

	def test_all_channels_failing_logs_every_attempt_failed(self):
		with adapters(whatsapp=failing(), sms=failing(), email=failing()):
			self.send_fees()
		self.assertEqual([l.status for l in self.logs()], ["Failed"] * 3)

	def set_channel_order(self, order):
		settings = frappe.get_single("Messaging Settings")
		settings.channel_order = []
		for channel in order:
			settings.append("channel_order", {"channel": channel})
		settings.save()

	def test_fallback_order_follows_messaging_settings(self):
		self.addCleanup(self.set_channel_order, ("whatsapp", "sms", "email", "push"))
		self.set_channel_order(("email", "sms", "whatsapp"))
		with adapters(email=failing()):
			self.send_fees()
		self.assertEqual([(l.channel, l.status) for l in self.logs()], [("email", "Failed"), ("sms", "Sent")])

	def test_promotional_not_sent_to_opted_out_but_transactional_is(self):
		self.make_template("t10.promo", purpose="promotional")
		for channel in ("whatsapp", "sms"):
			frappe.get_doc(
				{
					"doctype": "Communication Consent",
					"party_type": "Guardian",
					"party": self.guardian.name,
					"channel": channel,
					"purpose": "promotional",
					"status": "Opted Out",
				}
			).insert()
		mocks = {c: ok(f"{c}-id") for c in ("whatsapp", "sms")}
		with adapters(**mocks):
			api.send("t10.promo", self.doc, [f"Guardian:{self.guardian.name}"], now=True)
			self.assertEqual({l.status for l in self.logs(event_key="t10.promo")}, {"Skipped"})
			mocks["whatsapp"].assert_not_called()
			mocks["sms"].assert_not_called()
			self.send_fees()
		self.assertEqual([l.status for l in self.logs(event_key="fees.due")], ["Sent"])

	def test_promotional_needs_opt_in(self):
		self.make_template("t10.promo", purpose="promotional", channel_list=("sms",))
		with adapters():
			api.send("t10.promo", self.doc, [f"Guardian:{self.guardian.name}"], now=True)
			self.assertEqual([l.status for l in self.logs()], ["Skipped"])
			frappe.get_doc(
				{
					"doctype": "Communication Consent",
					"party_type": "Guardian",
					"party": self.guardian.name,
					"channel": "sms",
					"purpose": "promotional",
					"status": "Opted In",
				}
			).insert()
			api.send("t10.promo", self.doc, [f"Guardian:{self.guardian.name}"], now=True)
		self.assertEqual([l.status for l in self.logs()], ["Skipped", "Sent"])

	def test_duplicate_consent_record_rejected(self):
		values = {
			"doctype": "Communication Consent",
			"party_type": "Guardian",
			"party": self.guardian.name,
			"channel": "sms",
			"purpose": "promotional",
			"status": "Opted In",
		}
		frappe.get_doc(values).insert()
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({**values, "status": "Opted Out"}).insert()

	def test_repeat_send_is_a_no_op_returning_existing_logs(self):
		sms = ok("sms-id")
		with adapters(whatsapp=failing(), sms=sms):
			self.send_fees()
			second = self.send_fees()
		self.assertEqual(second, [self.logs(channel="sms")[0].name])
		self.assertEqual(sms.call_count, 1)
		self.assertEqual(len(self.logs()), 2)

	def test_resend_after_total_failure_retries(self):
		with adapters(whatsapp=failing(), sms=failing(), email=failing()):
			self.send_fees()
		with adapters():
			self.send_fees()
		self.assertEqual(self.logs()[-1].status, "Sent")

	def test_different_doc_or_recipient_is_not_deduplicated(self):
		other = self.make_guardian("B", mobile="+919800000002")
		with adapters():
			self.send_fees()
			api.send("fees.due", self.doc, [f"Guardian:{other.name}"], now=True)
		self.assertEqual(len(self.logs()), 2)

	def test_tamil_variant_for_ta_recipient(self):
		tamil = self.make_guardian("T", language="ta", mobile="+919800000003")
		with adapters():
			api.send("fees.due", self.doc, [f"Guardian:{tamil.name}"], {"amount": "1"}, now=True)
		message = frappe.db.get_value("Message Log", {"recipient": f"Guardian:{tamil.name}"}, "message")
		self.assertIn("அன்புள்ள", message)
		with adapters():
			self.send_fees()
		self.assertNotIn(
			"அன்புள்ள",
			frappe.db.get_value("Message Log", {"recipient": f"Guardian:{self.guardian.name}"}, "message"),
		)

	def test_missing_address_is_skipped_and_next_channel_used(self):
		bare = self.make_guardian("C", mobile=None, email="t10c@example.com")
		with adapters():
			api.send("fees.due", self.doc, [f"Guardian:{bare.name}"], now=True)
		self.assertEqual([(l.channel, l.status) for l in self.logs()], [("email", "Sent")])
		nobody = self.make_guardian("D", mobile=None, email=None)
		with adapters():
			api.send("fees.due", self.doc, [f"Guardian:{nobody.name}"], now=True)
		self.assertEqual({l.status for l in self.logs(recipient=f"Guardian:{nobody.name}")}, {"Skipped"})

	def test_phone_and_user_recipients(self):
		with adapters():
			api.send("fees.due", self.doc, ["phone:+919800000009"], now=True)
		self.assertEqual(
			[(l.recipient, l.channel) for l in self.logs()], [("phone:+919800000009", "whatsapp")]
		)

	def test_quiet_hours_schedule_non_urgent_and_scheduler_releases(self):
		self.set_quiet_hours_around_now()
		self.make_template("t10.urgent", urgent=1)
		wa = ok("wa")
		with adapters(whatsapp=wa):
			self.send_fees()
			api.send("t10.urgent", self.doc, [f"Guardian:{self.guardian.name}"], now=True)
			wa.assert_called_once()  # urgent only
			scheduled = self.logs(status="Scheduled")
			self.assertEqual(len(scheduled), 1)
			self.assertGreater(
				frappe.db.get_value("Message Log", scheduled[0].name, "send_after"), now_datetime()
			)
			delivery.dispatch_due()  # not due yet
			self.assertEqual(wa.call_count, 1)
			frappe.db.set_value(
				"Message Log", scheduled[0].name, "send_after", now_datetime() - timedelta(minutes=1)
			)
			delivery.dispatch_due()
		self.assertEqual(wa.call_count, 2)
		self.assertEqual(frappe.db.get_value("Message Log", scheduled[0].name, "status"), "Sent")

	def set_quiet_hours_around_now(self):
		now = now_datetime()
		settings = frappe.get_single("Messaging Settings")
		settings.quiet_hours_start = (now - timedelta(hours=1)).time().replace(microsecond=0)
		settings.quiet_hours_end = (now + timedelta(hours=1)).time().replace(microsecond=0)
		settings.save()

	def test_failed_push_only_template_logs_not_configured(self):
		self.make_template("t10.push", channel_list=("push",))
		user = frappe.get_doc(
			{"doctype": "User", "email": "t10push@example.com", "first_name": "T10", "send_welcome_email": 0}
		).insert()
		self.addCleanup(lambda: frappe.delete_doc("User", user.name, force=True))
		api.send("t10.push", self.doc, [f"User:{user.name}"], now=True)
		log = self.logs()[0]
		self.assertEqual((log.channel, log.status), ("push", "Failed"))
		self.assertIn("not configured", log.error)

	def test_unknown_event_raises(self):
		with self.assertRaises(frappe.ValidationError):
			api.send("t10.nope", self.doc, ["phone:+919800000009"], now=True)

	def test_whatsapp_webhook_updates_message_log(self):
		with adapters(whatsapp=ok("wamid.T10")):
			self.send_fees()
		self.assertEqual(self.logs()[0].status, "Sent")
		for status, expected in [("delivered", "Delivered"), ("read", "Read"), ("delivered", "Read")]:
			self.webhook_status("wamid.T10", status)
			self.assertEqual(self.logs()[0].status, expected)
		self.webhook_status("wamid.T10", "failed")  # too late to fail a Read message
		self.assertEqual(self.logs()[0].status, "Read")
		frappe.db.set_value("Message Log", self.logs()[0].name, "status", "Sent")
		self.webhook_status("wamid.T10", "failed")
		self.assertEqual(self.logs()[0].status, "Failed")
		with adapters():  # a failed log no longer blocks a new send
			self.send_fees()
		self.assertEqual(self.logs()[-1].status, "Sent")

	def webhook_status(self, message_id, status):
		from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message import WhatsAppMessage
		from frappe_whatsapp.utils.webhook import update_message_status

		if not frappe.db.exists("WhatsApp Message", {"message_id": message_id}):
			with (
				patch.object(WhatsAppMessage, "set_whatsapp_account"),
				patch.object(WhatsAppMessage, "before_insert"),
			):
				frappe.get_doc(
					{
						"doctype": "WhatsApp Message",
						"type": "Outgoing",
						"to": "+919800000001",
						"message_id": message_id,
						"content_type": "text",
					}
				).insert()
		with patch.object(WhatsAppMessage, "set_whatsapp_account"):
			update_message_status({"statuses": [{"id": message_id, "status": status}]})

	def test_notify_routes_through_messaging_bus_and_falls_back(self):
		from campus.campus_platform.notify import notify

		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "t10user@example.com",
				"first_name": "T10",
				"mobile_no": "+919800000004",
				"send_welcome_email": 0,
			}
		).insert()
		self.addCleanup(lambda: frappe.delete_doc("User", user.name, force=True))
		with adapters():
			notify([user.name], "Approve me", "please", self.doc)
			notify([user.name], "Approve me", "please", self.doc)  # identical repeat: no-op
			notify([user.name], "Level 2", "again", self.doc)  # distinct event on same doc: sent
		self.assertEqual(len(self.logs(event_key="approval.notification", status="Sent")), 2)
		self.assertEqual(frappe.db.get_value("Message Template", "approval.notification", "urgent"), 1)
		frappe.db.set_value("Message Template", "approval.notification", "enabled", 0)
		with adapters():
			notify([user.name], "Third", "x", self.doc)  # template disabled: legacy path only
		frappe.db.set_value("Message Template", "approval.notification", "enabled", 1)
		self.assertEqual(len(self.logs(event_key="approval.notification", status="Sent")), 2)

	def test_scheduled_promotional_is_skipped_if_consent_withdrawn_before_release(self):
		self.make_template("t10.promo", purpose="promotional", channel_list=("sms",))
		consent_doc = frappe.get_doc(
			{
				"doctype": "Communication Consent",
				"party_type": "Guardian",
				"party": self.guardian.name,
				"channel": "sms",
				"purpose": "promotional",
				"status": "Opted In",
			}
		).insert()
		self.set_quiet_hours_around_now()
		sms = ok("sms-id")
		with adapters(sms=sms):
			api.send("t10.promo", self.doc, [f"Guardian:{self.guardian.name}"], now=True)
			log = self.logs(status="Scheduled")[0]
			consent_doc.status = "Opted Out"
			consent_doc.save()
			frappe.db.set_value("Message Log", log.name, "send_after", now_datetime() - timedelta(minutes=1))
			delivery.dispatch_due()
		sms.assert_not_called()
		self.assertEqual(frappe.db.get_value("Message Log", log.name, "status"), "Skipped")

	def test_notify_never_raises_when_messaging_breaks(self):
		from campus.campus_platform.notify import notify

		with patch("campus.campus_messaging.api.send", side_effect=RuntimeError("bus down")):
			notify(["Administrator"], "Approve", "msg", self.doc)  # must not raise
		self.assertTrue(
			frappe.db.exists("Error Log", {"method": "Approval notification via messaging failed"})
		)

	def test_template_with_bad_jinja_is_rejected_at_save(self):
		bad = {
			"doctype": "Message Template",
			"event_key": "t10.bad",
			"channels": [{"channel": "sms"}],
			"bodies": [{"language": "en", "subject": "S", "body": "Hi {{ doc.name "}],
		}
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(bad).insert()
		bad["bodies"][0]["body"] = "ok"
		bad["variables"] = "doc.name\n{{ broken"
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(bad).insert()
		bad["variables"] = "doc.name"
		bad["bodies"][0]["subject"] = "{% if %}"
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(bad).insert()

	def test_whatsapp_is_a_required_app(self):
		self.assertIn("frappe_whatsapp", frappe.get_hooks("required_apps", app_name="campus"))

	def test_consent_name_is_deterministic_primary_key(self):
		doc = frappe.get_doc(
			{
				"doctype": "Communication Consent",
				"party_type": "Guardian",
				"party": self.guardian.name,
				"channel": "sms",
				"purpose": "promotional",
				"status": "Opted In",
			}
		).insert()
		self.assertEqual(doc.name, f"Guardian-{self.guardian.name}-sms-promotional")

	def test_stored_errors_have_urls_removed(self):
		err = channels.safe_error(Exception("401 for url: https://gw.invalid/send?apikey=SECRET&to=1 bad"))
		self.assertNotIn("SECRET", err)
		with adapters(whatsapp=failing("GET https://x.invalid/?token=SECRET failed"), sms=ok("s")):
			self.send_fees()
		self.assertNotIn("SECRET", self.logs(channel="whatsapp")[0].error)

	def test_failed_webhook_does_not_overwrite_delivered_or_read(self):
		with adapters(whatsapp=ok("wamid.T10B")):
			self.send_fees()
		self.webhook_status("wamid.T10B", "read")
		self.webhook_status("wamid.T10B", "failed")
		self.assertEqual(self.logs()[0].status, "Read")

	def test_dispatch_due_isolates_a_crashing_log(self):
		second = self.make_guardian("E", mobile="+919800000005")
		self.set_quiet_hours_around_now()
		with adapters():
			api.send(
				"fees.due", self.doc, [f"Guardian:{self.guardian.name}", f"Guardian:{second.name}"], now=True
			)
			frappe.db.set_value(
				"Message Log", {"status": "Scheduled"}, "send_after", now_datetime() - timedelta(minutes=1)
			)
			real = delivery.dispatch_log
			calls = []

			def flaky(name):
				calls.append(name)
				if len(calls) == 1:
					raise RuntimeError("boom")
				real(name)

			with patch.object(delivery, "dispatch_log", flaky):
				delivery.dispatch_due()
		self.assertEqual(sorted(l.status for l in self.logs()), ["Scheduled", "Sent"])

	def test_greeting_uses_display_name_not_record_id(self):
		with adapters():
			names = self.send_fees()
		self.assertIn(f"{GUARDIAN_PREFIX} A", frappe.db.get_value("Message Log", names[0], "message"))
		self.assertNotIn(self.guardian.name, frappe.db.get_value("Message Log", names[0], "message"))

	def test_repeated_skip_does_not_add_rows(self):
		nobody = self.make_guardian("F", mobile=None, email=None)
		with adapters():
			for _i in range(3):
				api.send("fees.due", self.doc, [f"Guardian:{nobody.name}"], now=True)
		self.assertEqual(len(self.logs(recipient=f"Guardian:{nobody.name}")), 3)
