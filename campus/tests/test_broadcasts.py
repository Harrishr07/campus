"""P1-T11 audience rules and broadcasts: resolution, pre-send count, approval gating, bulk send, schedule."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, now_datetime

from campus.campus_messaging import audience, scope
from campus.campus_messaging.doctype.audience_rule.audience_rule import preview_count
from campus.campus_messaging.doctype.broadcast import broadcast as broadcasting
from campus.campus_platform import bulk
from campus.campus_platform.approvals import approve, request_approval
from campus.tests import broadcast_fixtures as fx
from campus.tests.test_messaging import adapters
from campus.tests.utils import CampusTestCase

NOTICE = "t11.notice"
PROMO = "t11.promo"


class BroadcastTestCase(CampusTestCase):
	@classmethod
	def load_demo_data(cls):
		cls.world = fx.setup_world()
		fx.make_template(NOTICE)
		fx.make_template(PROMO, "promotional")
		cls.previous_year = frappe.db.get_single_value("Education Settings", "current_academic_year")
		frappe.db.set_single_value("Education Settings", "current_academic_year", fx.YEAR)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_single_value("Education Settings", "current_academic_year", cls.previous_year)
		fx.clear_documents()
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		fx.clear_documents()
		frappe.db.set_single_value("Education Settings", "current_academic_year", fx.YEAR)
		patcher = patch.object(bulk, "enqueue_run")
		self.enqueue = patcher.start()
		self.addCleanup(patcher.stop)

	def keys(self, doctype, *names):
		return sorted(f"{doctype}:{self.world[n]}" for n in names)


class TestAudienceRules(BroadcastTestCase):
	def test_student_group_takes_active_enabled_members_only(self):
		rule = fx.make_rule("T11 Group Rule", "Student Group", student_group=self.world["group"])
		self.assertEqual(sorted(audience.resolve(rule)), self.keys("Student", "asha", "bala"))

	def test_program_uses_submitted_enrollments_of_the_current_year(self):
		rule = fx.make_rule("T11 CSE Rule", "Program and Semester", program=fx.CSE)
		self.assertEqual(sorted(audience.resolve(rule)), self.keys("Student", "asha", "bala", "chitra"))
		frappe.db.set_single_value("Education Settings", "current_academic_year", "RT-2020")
		self.assertEqual(audience.resolve(rule), [])

	def test_semester_is_ignored_without_the_student_field_and_applied_with_it(self):
		rule = fx.make_rule("T11 Sem Rule", "Program and Semester", program=fx.CSE, semester="III")
		self.assertEqual(len(audience.resolve(rule)), 3)  # Student has no oc_current_semester yet
		bala_email = frappe.db.get_value("Student", self.world["bala"], "student_email_id")
		rule.semester = bala_email
		with patch.object(audience, "SEMESTER_FIELD", "student_email_id"):
			self.assertEqual(audience.resolve(rule), self.keys("Student", "bala"))

	def test_guardians_of_a_program_are_distinct(self):
		rule = fx.make_rule("T11 Guardians CSE", "Guardians of", guardians_of="Program and Semester", program=fx.CSE)
		self.assertEqual(sorted(audience.resolve(rule)), self.keys("Guardian", "g_asha", "g_chitra"))

	def test_guardians_of_a_group(self):
		rule = fx.make_rule("T11 Guardians Group", "Guardians of", guardians_of="Student Group", student_group=self.world["group"])
		self.assertEqual(audience.resolve(rule), self.keys("Guardian", "g_asha"))

	def test_department_lists_active_employees_of_that_department(self):
		rule = fx.make_rule("T11 Dept Rule", "Department", department=self.world["dept"])
		self.assertEqual(sorted(audience.resolve(rule)), self.keys("Employee", "emp_1", "emp_2"))
		frappe.db.set_value("Employee", self.world["emp_2"], "status", "Left")
		self.addCleanup(frappe.db.set_value, "Employee", self.world["emp_2"], "status", "Active")
		self.assertEqual(audience.resolve(rule), self.keys("Employee", "emp_1"))

	def test_role_lists_enabled_users_permitted_for_the_company(self):
		rule = fx.make_rule("T11 Role Rule", "Role", role="Student")
		users = audience.resolve(rule)
		self.assertIn(f"User:{fx.STUDENT_USER}", users)
		self.assertNotIn(f"User:{fx.OTHER_COLLEGE_USER}", users)  # restricted to another company
		self.assertNotIn("User:Administrator", users)

	def test_hostel_and_route_rules_say_they_arrive_in_phase_4(self):
		for rule in (
			fx.make_rule("T11 Hostel", "Hostel", hostel="Block A"),
			fx.make_rule("T11 Route", "Route", route="R1"),
			fx.make_rule("T11 Hostel Guardians", "Guardians of", guardians_of="Hostel", hostel="Block A"),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "not available until Phase 4"):
				audience.resolve(rule)

	def test_missing_filter_and_foreign_company_are_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "required"):
			fx.make_rule("T11 Bad Group", "Student Group")
		with self.assertRaisesRegex(frappe.ValidationError, "does not belong"):
			frappe.get_doc(
				{"doctype": "Audience Rule", "rule_name": "T11 Foreign", "company": fx.OTHER_COLLEGE,
				 "rule_type": "Program and Semester", "program": fx.CSE}
			).insert()  # fmt: skip

	def test_preview_count_matches_resolution(self):
		rule = fx.make_rule("T11 Guardians CSE", "Guardians of", guardians_of="Program and Semester", program=fx.CSE)
		self.assertEqual(preview_count(rule.name), 2)


class TestMessageCompany(BroadcastTestCase):
	def test_company_of_records_and_guardians(self):
		self.assertEqual(scope.company_of("Student", self.world["asha"]), fx.COLLEGE)
		self.assertEqual(scope.company_of("Employee", self.world["emp_1"]), fx.COLLEGE)
		self.assertEqual(scope.company_of("Guardian", self.world["g_asha"]), fx.COLLEGE)
		self.assertIsNone(scope.company_of("User", fx.STAFF_USER))
		self.assertIsNone(scope.company_of("phone", "+919800000000"))
		self.assertIsNone(scope.company_of("Student", "no-such-student"))


class TestBroadcasts(BroadcastTestCase):
	def setUp(self):
		super().setUp()
		self.rule = fx.make_rule(
			"T11 Guardians CSE", "Guardians of", guardians_of="Program and Semester", program=fx.CSE
		).name

	def broadcast(self, template=NOTICE, **extra):
		return frappe.get_doc(
			{"doctype": "Broadcast", "title": "Fee reminder", "company": fx.COLLEGE, "audience_rule": self.rule,
			 "message_template": template, **extra}
		).insert()  # fmt: skip

	def run_of(self, broadcast):
		broadcast.reload()
		frappe.db.commit()
		with adapters():
			bulk.process_bulk_run(broadcast.bulk_run)
		return frappe.get_doc("Bulk Run", broadcast.bulk_run)

	def logs(self, broadcast):
		return frappe.get_all(
			"Message Log",
			filters={"reference_doctype": "Broadcast", "reference_name": broadcast.name},
			fields=["recipient", "status", "company"],
		)

	def test_count_is_known_before_sending_and_submit_sends_to_that_audience(self):
		self.assertEqual(preview_count(self.rule), 2)
		broadcast = self.broadcast()
		self.assertEqual(broadcast.status, "Draft")
		self.assertEqual(frappe.db.count("Message Log", {"reference_name": broadcast.name}), 0)
		broadcast.submit()
		broadcast.reload()
		self.assertEqual((broadcast.status, broadcast.recipients_count), ("Sending", 2))
		run = self.run_of(broadcast)
		self.assertEqual((run.status, run.total, run.done), ("Completed", 2, 2))
		self.assertEqual(
			sorted(log.recipient for log in self.logs(broadcast)), self.keys("Guardian", "g_asha", "g_chitra")
		)
		self.assertEqual({log.company for log in self.logs(broadcast)}, {fx.COLLEGE})

	def test_status_and_counts_follow_the_bulk_run(self):
		broadcast = self.broadcast()
		broadcast.submit()
		self.run_of(broadcast)
		self.assertEqual(broadcasting.refresh_status(broadcast.name), "Sent")
		broadcast.reload()
		self.assertEqual(
			(broadcast.status, broadcast.recipients_count, broadcast.queued_count, broadcast.skipped_count, broadcast.failed_count),
			("Sent", 2, 2, 0, 0),
		)  # fmt: skip

	def test_promotional_broadcast_skips_recipients_without_consent(self):
		frappe.get_doc(
			{"doctype": "Communication Consent", "party_type": "Guardian", "party": self.world["g_asha"],
			 "channel": "email", "purpose": "promotional", "status": "Opted In"}
		).insert()  # fmt: skip
		self.addCleanup(frappe.delete_doc, "Communication Consent", f"Guardian-{self.world['g_asha']}-email-promotional")
		broadcast = self.broadcast(PROMO)
		broadcast.submit()
		self.run_of(broadcast)
		broadcasting.refresh_status(broadcast.name)
		broadcast.reload()
		self.assertEqual((broadcast.queued_count, broadcast.skipped_count, broadcast.failed_count), (1, 1, 0))

	def test_recipient_whose_send_fails_is_counted_as_failed(self):
		broadcast = self.broadcast()
		broadcast.submit()
		real_send = frappe.get_attr("campus.campus_messaging.bulk_send.send")

		def flaky(event_key, doc, recipients, *args, **kwargs):
			if recipients == [f"Guardian:{self.world['g_chitra']}"]:
				frappe.throw("provider down")
			return real_send(event_key, doc, recipients, *args, **kwargs)

		with patch("campus.campus_messaging.bulk_send.send", flaky):
			run = self.run_of(broadcast)
		self.assertEqual((run.status, run.done, run.failed), ("Completed with errors", 1, 1))
		broadcasting.refresh_status(broadcast.name)
		broadcast.reload()
		self.assertEqual((broadcast.status, broadcast.queued_count, broadcast.failed_count), ("Sent", 1, 1))

	def test_approval_is_required_when_a_policy_matches(self):
		fx.make_policy("Broadcast")
		broadcast = self.broadcast()
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			broadcast.submit()
		request = request_approval("Broadcast", broadcast.name)
		broadcast.reload()
		self.assertEqual((broadcast.status, broadcast.docstatus), ("Pending Approval", 0))
		self.assertEqual(frappe.db.count("Message Log", {"reference_name": broadcast.name, "event_key": NOTICE}), 0)

		frappe.set_user(fx.STAFF_USER)
		approve(request)
		frappe.set_user("Administrator")
		broadcast.reload()
		self.assertEqual((broadcast.docstatus, broadcast.status, broadcast.recipients_count), (1, "Sending", 2))
		self.assertTrue(broadcast.bulk_run)

	def test_returned_broadcast_goes_back_to_draft(self):
		fx.make_policy("Broadcast")
		broadcast = self.broadcast()
		request = request_approval("Broadcast", broadcast.name)
		frappe.set_user(fx.STAFF_USER)
		frappe.get_attr("campus.campus_platform.approvals.return_for_changes")(request, "fix the text")
		frappe.set_user("Administrator")
		broadcast.reload()
		self.assertEqual(broadcast.status, "Draft")

	def test_future_schedule_waits_and_the_scheduler_releases_it_once_due(self):
		broadcast = self.broadcast(schedule_at=add_to_date(now_datetime(), hours=2))
		broadcast.submit()
		broadcast.reload()
		self.assertEqual((broadcast.status, broadcast.bulk_run), ("Scheduled", None))
		broadcasting.release_due()
		broadcast.reload()
		self.assertEqual(broadcast.status, "Scheduled")

		frappe.db.set_value("Broadcast", broadcast.name, "schedule_at", add_to_date(now_datetime(), minutes=-1))
		broadcasting.release_due()
		broadcast.reload()
		self.assertEqual((broadcast.status, broadcast.recipients_count), ("Sending", 2))
		self.run_of(broadcast)
		broadcasting.release_due()  # closes the finished run
		broadcast.reload()
		self.assertEqual(broadcast.status, "Sent")
		self.assertEqual(frappe.db.count("Bulk Run", {"name": broadcast.bulk_run}), 1)

	def test_release_happens_only_once(self):
		broadcast = self.broadcast()
		broadcast.submit()
		broadcast.reload()
		first_run = broadcast.bulk_run
		broadcasting.release(broadcast.name)
		broadcast.reload()
		self.assertEqual(broadcast.bulk_run, first_run)
		self.assertEqual(self.enqueue.call_count, 1)

	def test_scheduler_marks_an_unreleasable_broadcast_failed_and_goes_on(self):
		broadcast = self.broadcast(schedule_at=add_to_date(now_datetime(), hours=1))
		broadcast.submit()
		frappe.db.set_value("Broadcast", broadcast.name, "schedule_at", add_to_date(now_datetime(), minutes=-1))
		frappe.db.commit()
		with patch.object(audience, "resolve", side_effect=frappe.ValidationError("boom")):
			broadcasting.release_due()
		broadcast.reload()
		self.assertEqual(broadcast.status, "Failed")
		frappe.db.delete("Error Log", {"method": ["like", "Broadcast %could not be released"]})

	def test_empty_audience_is_sent_without_a_run(self):
		frappe.db.set_single_value("Education Settings", "current_academic_year", "RT-2020")
		broadcast = self.broadcast()
		broadcast.submit()
		broadcast.reload()
		self.assertEqual((broadcast.status, broadcast.recipients_count, broadcast.bulk_run), ("Sent", 0, None))

	def test_validation(self):
		other_rule = frappe.get_doc(
			{"doctype": "Audience Rule", "rule_name": "T11 Role Other", "company": fx.OTHER_COLLEGE,
			 "rule_type": "Role", "role": "Student"}
		).insert()  # fmt: skip
		with self.assertRaisesRegex(frappe.ValidationError, "belongs to"):
			self.broadcast(audience_rule=other_rule.name)
		with self.assertRaisesRegex(frappe.ValidationError, "valid JSON"):
			self.broadcast(context="{oops")
		with self.assertRaisesRegex(frappe.ValidationError, "JSON object"):
			self.broadcast(context="[1]")
		hostel = fx.make_rule("T11 Hostel", "Hostel", hostel="Block A")
		with self.assertRaisesRegex(frappe.ValidationError, "Phase 4"):
			self.broadcast(audience_rule=hostel.name)
		frappe.db.set_value("Message Template", PROMO, "enabled", 0)
		self.addCleanup(frappe.db.set_value, "Message Template", PROMO, "enabled", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "disabled"):
			self.broadcast(PROMO)

	def test_a_sending_broadcast_cannot_be_cancelled(self):
		broadcast = self.broadcast()
		broadcast.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "being sent"):
			broadcast.cancel()
