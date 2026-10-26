"""P1-T11 circulars and reports: approval and window visibility, notification, acknowledgement, reporting."""

from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from campus.campus_messaging import circulars
from campus.campus_messaging.doctype.circular import circular as circular_module
from campus.campus_messaging.report.circular_acknowledgement_status import (
	circular_acknowledgement_status as ack_report,
)
from campus.campus_messaging.report.consent_register import consent_register
from campus.campus_messaging.report.delivery_summary import delivery_summary
from campus.campus_platform import bulk
from campus.campus_platform.approvals import approve, request_approval
from campus.tests import broadcast_fixtures as fx
from campus.tests.test_broadcasts import BroadcastTestCase
from campus.tests.test_messaging import adapters

HOUR_AGO = {"hours": -1}
IN_AN_HOUR = {"hours": 1}


def when(**delta):
	return add_to_date(now_datetime(), **delta)


class CircularTestCase(BroadcastTestCase):
	def setUp(self):
		super().setUp()
		self.rule = fx.make_rule(
			"T11 Guardians CSE", "Guardians of", guardians_of="Program and Semester", program=fx.CSE
		).name

	def circular(self, publish_from=None, **extra):
		return frappe.get_doc(
			{"doctype": "Circular", "title": "Exam timetable", "company": fx.COLLEGE, "audience_rule": self.rule,
			 "body": "<p>Exams start on Monday.</p>", "publish_from": publish_from or when(**HOUR_AGO),
			 "acknowledgement_required": 1, **extra}
		).insert()  # fmt: skip

	def names_for(self, user):
		return [c["name"] for c in circulars.circulars_for(user)]

	def listed_for(self, user):
		return frappe.get_list("Circular", user=user, pluck="name")

	def process_pending_runs(self):
		frappe.db.commit()
		with adapters():
			for run in frappe.get_all(
				"Bulk Run", filters={"status": "Queued", "run_type": ["like", "Circular %"]}, pluck="name"
			):
				bulk.process_bulk_run(run)

	def acknowledge_as(self, user, name):
		frappe.set_user(user)
		try:
			return circulars.acknowledge(name)
		finally:
			frappe.set_user("Administrator")


class TestCircularVisibility(CircularTestCase):
	def test_draft_is_invisible_to_its_audience(self):
		circular = self.circular()
		self.assertEqual(self.names_for(fx.GUARDIAN_USER), [])
		self.assertEqual(self.listed_for(fx.GUARDIAN_USER), [])
		self.assertFalse(frappe.has_permission("Circular", "read", circular.name, user=fx.GUARDIAN_USER))

	def test_approved_but_not_yet_published_is_invisible_and_silent(self):
		circular = self.circular(publish_from=when(**IN_AN_HOUR))
		circular.submit()
		self.assertEqual(self.names_for(fx.GUARDIAN_USER), [])
		self.assertEqual(self.listed_for(fx.GUARDIAN_USER), [])
		self.assertIsNone(frappe.db.get_value("Circular", circular.name, "published_on"))
		circular_module.publish_due()
		self.assertEqual(
			frappe.db.count(
				"Message Log", {"reference_name": circular.name, "event_key": "circular.published"}
			),
			0,
		)

	def test_published_circular_shows_to_the_audience_only(self):
		circular = self.circular()
		circular.submit()
		self.assertEqual(self.names_for(fx.GUARDIAN_USER), [circular.name])
		self.assertEqual(self.listed_for(fx.GUARDIAN_USER), [circular.name])
		self.assertTrue(frappe.has_permission("Circular", "read", circular.name, user=fx.GUARDIAN_USER))
		self.assertFalse(frappe.has_permission("Circular", "write", circular.name, user=fx.GUARDIAN_USER))
		# not addressed to them: another college's student, and a guardian of an ECE student
		for user in (fx.OTHER_COLLEGE_USER, fx.OUTSIDE_GUARDIAN_USER, fx.STUDENT_USER):
			self.assertEqual(self.names_for(user), [], user)
			self.assertEqual(self.listed_for(user), [], user)
			self.assertFalse(frappe.has_permission("Circular", "read", circular.name, user=user))

	def test_student_audience_sees_it_through_their_own_record(self):
		rule = fx.make_rule("T11 Group Rule", "Student Group", student_group=self.world["group"]).name
		circular = self.circular(audience_rule=rule)
		circular.submit()
		self.assertEqual(self.names_for(fx.STUDENT_USER), [circular.name])
		self.assertEqual(self.names_for(fx.GUARDIAN_USER), [])

	def test_window_end_hides_the_circular_again(self):
		circular = self.circular(publish_from=when(hours=-3), publish_until=when(hours=-1))
		circular.submit()
		self.assertEqual(self.names_for(fx.GUARDIAN_USER), [])
		frappe.db.set_value("Circular", circular.name, "publish_until", when(**IN_AN_HOUR))
		self.assertEqual(self.names_for(fx.GUARDIAN_USER), [circular.name])

	def test_cancelled_circular_disappears(self):
		circular = self.circular()
		circular.submit()
		circular.cancel()
		self.assertEqual(self.names_for(fx.GUARDIAN_USER), [])

	def test_staff_follow_role_permissions_and_see_unpublished_circulars(self):
		circular = self.circular(publish_from=when(**IN_AN_HOUR))
		self.assertIn(circular.name, self.listed_for(fx.STAFF_USER))
		self.assertEqual(circulars.get_permission_query_conditions(fx.STAFF_USER), "")

	def test_publish_window_is_validated(self):
		with self.assertRaisesRegex(frappe.ValidationError, "after Publish From"):
			self.circular(publish_until=when(hours=-2))

	def test_approval_gates_the_circular_when_a_policy_matches(self):
		fx.make_policy("Circular")
		circular = self.circular()
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			circular.submit()
		request = request_approval("Circular", circular.name)
		self.assertEqual(self.names_for(fx.GUARDIAN_USER), [])  # pending approval: still invisible
		frappe.set_user(fx.STAFF_USER)
		approve(request)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Circular", circular.name, "docstatus"), 1)
		self.assertEqual(self.names_for(fx.GUARDIAN_USER), [circular.name])


class TestCircularPublishing(CircularTestCase):
	def notified(self, circular):
		return sorted(
			frappe.get_all(
				"Message Log",
				filters={
					"reference_doctype": "Circular",
					"reference_name": circular.name,
					"event_key": "circular.published",
				},
				pluck="recipient",
			)
		)

	def test_submitting_inside_the_window_notifies_the_audience(self):
		circular = self.circular()
		circular.submit()
		self.assertTrue(frappe.db.get_value("Circular", circular.name, "published_on"))
		self.process_pending_runs()
		self.assertEqual(self.notified(circular), self.keys("Guardian", "g_asha", "g_chitra"))

	def test_scheduler_notifies_once_the_publish_time_is_reached(self):
		circular = self.circular(publish_from=when(**IN_AN_HOUR))
		circular.submit()
		self.process_pending_runs()
		self.assertEqual(self.notified(circular), [])
		frappe.db.set_value("Circular", circular.name, "publish_from", when(minutes=-1))
		frappe.db.commit()
		circular_module.publish_due()
		self.process_pending_runs()
		self.assertEqual(self.notified(circular), self.keys("Guardian", "g_asha", "g_chitra"))
		self.assertEqual(self.names_for(fx.GUARDIAN_USER), [circular.name])

	def test_the_audience_is_notified_only_once(self):
		circular = self.circular()
		circular.submit()
		circular_module.publish_due()
		circular_module.publish_if_due(circular.name)
		self.assertEqual(frappe.db.count("Bulk Run", {"run_type": f"Circular {circular.name}"}), 1)
		self.process_pending_runs()
		self.assertEqual(len(self.notified(circular)), 2)

	def test_a_window_that_already_closed_is_never_notified(self):
		circular = self.circular(publish_from=when(hours=-3), publish_until=when(hours=-1))
		circular.submit()
		self.assertIsNone(frappe.db.get_value("Circular", circular.name, "published_on"))
		circular_module.publish_due()
		self.assertEqual(frappe.db.count("Bulk Run", {"run_type": f"Circular {circular.name}"}), 0)


class TestCircularFeedAndAcknowledgement(CircularTestCase):
	def setUp(self):
		super().setUp()
		self.published = self.circular()
		self.published.submit()

	def feed(self, user):
		frappe.set_user(user)
		try:
			return circulars.get_my_circulars()
		finally:
			frappe.set_user("Administrator")

	def test_portal_feed_lists_live_circulars_with_attachments(self):
		file = frappe.get_doc(
			{"doctype": "File", "file_name": "t11-timetable.txt", "content": "x", "attached_to_doctype": "Circular",
			 "attached_to_name": self.published.name, "is_private": 1}
		).insert()  # fmt: skip
		self.addCleanup(frappe.delete_doc, "File", file.name, force=True)
		feed = self.feed(fx.GUARDIAN_USER)
		self.assertEqual([c["name"] for c in feed], [self.published.name])
		self.assertEqual((feed[0]["title"], feed[0]["acknowledged"]), ("Exam timetable", False))
		self.assertEqual([a["file_name"] for a in feed[0]["attachments"]], ["t11-timetable.txt"])
		self.assertEqual(self.feed(fx.OUTSIDE_GUARDIAN_USER), [])

	def test_acknowledging_is_recorded_once_per_user(self):
		name = self.acknowledge_as(fx.GUARDIAN_USER, self.published.name)
		self.assertEqual(self.acknowledge_as(fx.GUARDIAN_USER, self.published.name), name)
		rows = frappe.get_all(
			"Circular Acknowledgement",
			filters={"circular": self.published.name},
			fields=["user", "party_type", "party", "company"],
		)
		self.assertEqual(
			[(r.user, r.party_type, r.party, r.company) for r in rows],
			[(fx.GUARDIAN_USER, "Guardian", self.world["g_asha"], fx.COLLEGE)],
		)
		self.assertTrue(self.feed(fx.GUARDIAN_USER)[0]["acknowledged"])

	def test_database_refuses_a_second_acknowledgement(self):
		self.acknowledge_as(fx.GUARDIAN_USER, self.published.name)
		duplicate = frappe.get_doc(
			{"doctype": "Circular Acknowledgement", "circular": self.published.name, "user": fx.GUARDIAN_USER}
		)
		with self.assertRaises(frappe.DuplicateEntryError):
			duplicate.insert(ignore_permissions=True)

	def test_only_the_audience_can_acknowledge_a_live_circular(self):
		with self.assertRaises(frappe.PermissionError):
			self.acknowledge_as(fx.OUTSIDE_GUARDIAN_USER, self.published.name)
		frappe.db.set_value("Circular", self.published.name, "publish_until", when(minutes=-5))
		with self.assertRaises(frappe.PermissionError):
			self.acknowledge_as(fx.GUARDIAN_USER, self.published.name)

	def test_circular_without_acknowledgement_requirement_refuses_it(self):
		plain = self.circular(acknowledgement_required=0)
		plain.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "does not need acknowledgement"):
			self.acknowledge_as(fx.GUARDIAN_USER, plain.name)

	def test_guests_see_and_acknowledge_nothing(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				circulars.get_my_circulars()
			with self.assertRaises(frappe.PermissionError):
				circulars.acknowledge(self.published.name)
		finally:
			frappe.set_user("Administrator")


class TestReports(CircularTestCase):
	def rows(self, report, filters=None, user="Administrator"):
		frappe.set_user(user)
		try:
			return report.execute(filters or {})[1]
		finally:
			frappe.set_user("Administrator")

	def test_acknowledgement_status_per_circular_and_per_recipient(self):
		circular = self.circular()
		circular.submit()
		self.acknowledge_as(fx.GUARDIAN_USER, circular.name)
		summary = [
			r for r in self.rows(ack_report, {"company": fx.COLLEGE}) if r["circular"] == circular.name
		]
		self.assertEqual([(r["audience"], r["acknowledged"], r["pending"]) for r in summary], [(2, 1, 1)])

		detail = {r["recipient"]: r for r in self.rows(ack_report, {"circular": circular.name})}
		asha, chitra = (
			detail[f"Guardian:{self.world['g_asha']}"],
			detail[f"Guardian:{self.world['g_chitra']}"],
		)
		self.assertEqual((asha["status"], asha["user"]), ("Acknowledged", fx.GUARDIAN_USER))
		self.assertTrue(asha["acknowledged_on"])
		self.assertEqual(
			(chitra["status"], chitra["user"], chitra["acknowledged_on"]), ("Pending", None, None)
		)

	def test_acknowledgement_report_skips_circulars_not_requiring_it_and_other_colleges(self):
		plain = self.circular(acknowledgement_required=0)
		plain.submit()
		self.assertNotIn(plain.name, [r["circular"] for r in self.rows(ack_report)])
		circular = self.circular()
		circular.submit()
		self.assertIn(circular.name, [r["circular"] for r in self.rows(ack_report)])
		self.assertEqual(self.rows(ack_report, {"company": fx.OTHER_COLLEGE}), [])
		self.assertEqual(self.rows(ack_report, user=fx.OTHER_COLLEGE_USER), [])

	def test_delivery_summary_groups_by_event_channel_status_and_company(self):
		circular = self.circular()
		circular.submit()
		self.process_pending_runs()
		rows = self.rows(delivery_summary, {"company": fx.COLLEGE, "event_key": "circular.published"})
		# the seeded template honours quiet hours, so the two messages are Sent or Scheduled depending on the clock
		self.assertEqual(
			[(r["event_key"], r["channel"]) for r in rows], [("circular.published", "email")] * len(rows)
		)
		self.assertEqual(sum(r["count"] for r in rows), 2)
		self.assertEqual(
			self.rows(delivery_summary, {"company": fx.OTHER_COLLEGE, "event_key": "circular.published"}), []
		)
		self.assertEqual(
			self.rows(delivery_summary, {"event_key": "circular.published"}, user=fx.OTHER_COLLEGE_USER), []
		)
		self.assertEqual(
			self.rows(
				delivery_summary,
				{"company": fx.COLLEGE, "event_key": "circular.published", "status": "Failed"},
			),
			[],
		)

	def test_consent_register_lists_consents_by_company(self):
		consent = frappe.get_doc(
			{"doctype": "Communication Consent", "party_type": "Guardian", "party": self.world["g_asha"],
			 "channel": "sms", "purpose": "promotional", "status": "Opted Out", "source": "T11 test"}
		).insert()  # fmt: skip
		self.addCleanup(frappe.delete_doc, "Communication Consent", consent.name)
		self.assertEqual(consent.company, fx.COLLEGE)
		rows = self.rows(consent_register, {"company": fx.COLLEGE, "channel": "sms"})
		self.assertIn(
			("Guardian", self.world["g_asha"], "Opted Out"),
			[(r["party_type"], r["party"], r["status"]) for r in rows],
		)
		self.assertEqual(self.rows(consent_register, {"company": fx.OTHER_COLLEGE}), [])
		self.assertEqual(self.rows(consent_register, user=fx.OTHER_COLLEGE_USER), [])


class TestMessagingJavascript(CircularTestCase):
	def test_every_method_the_forms_call_resolves(self):
		import re

		for doctype in ("audience_rule", "broadcast", "circular"):
			path = frappe.get_app_path("campus", "campus_messaging", "doctype", doctype, f"{doctype}.js")
			source = open(path).read()
			constants = dict(re.findall(r'const (\w+) = "([\w.]+)"', source))
			calls = re.findall(r'xcall\(\s*(?:(\w+) \+ )?(?:"(\w+)"|(\w+))', source)
			methods = set(re.findall(r'xcall\(\s*"([\w.]+)"', source))
			for prefix, name, constant in calls:
				if constant:
					methods.add(constants[constant])
				elif prefix:
					methods.add(constants[prefix] + name)
			self.assertTrue(methods, doctype)
			for method in methods:
				self.assertTrue(callable(frappe.get_attr(method)), method)
				self.assertIn(frappe.get_attr(method), frappe.whitelisted, method)

	def test_acknowledge_returns_existing_row_when_insert_races(self):
		circular = self.circular()
		circular.submit()
		name = self.acknowledge_as(fx.GUARDIAN_USER, circular.name)
		with patch(
			"frappe.db.exists", return_value=None
		):  # the pre-check misses the row another request just wrote
			self.assertEqual(self.acknowledge_as(fx.GUARDIAN_USER, circular.name), name)
		self.assertEqual(frappe.db.count("Circular Acknowledgement", {"circular": circular.name}), 1)

	def test_refresh_status_needs_write_permission(self):
		broadcast = frappe.get_doc(
			{
				"doctype": "Broadcast",
				"title": "x",
				"company": fx.COLLEGE,
				"audience_rule": self.rule,
				"message_template": "t11.notice",
			}
		).insert()
		broadcast.submit()
		frappe.set_user(fx.STUDENT_USER)
		try:
			with self.assertRaises(frappe.PermissionError):
				frappe.get_attr("campus.campus_messaging.doctype.broadcast.broadcast.refresh_status")(
					broadcast.name
				)
		finally:
			frappe.set_user("Administrator")
