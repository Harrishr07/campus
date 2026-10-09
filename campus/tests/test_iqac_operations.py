"""P3-T08 (M01-04, M01-06, M01-07) tests: due rule and reminder schedule (unit); committee compliance, IQAC calendar,
ATR, Regulator Submission reminders with Principal escalation, and Institutional MoU (integration)."""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import add_days, today

from campus.iqac import committees, regulator
from campus.iqac.report.committee_compliance import committee_compliance
from campus.iqac.report.iqac_action_taken_report import iqac_action_taken_report
from campus.iqac.report.iqac_calendar import iqac_calendar
from campus.tests.factories import make_company
from campus.tests.utils import CampusTestCase

COLLEGE = "IQAC Ops College"


class TestDueRule(UnitTestCase):
	def test_fixed_date_takes_the_next_occurrence_on_or_after_period_end(self):
		due = lambda end: str(regulator.due_date("Fixed Date Each Year", end, 6, 30, 0))  # noqa: E731
		self.assertEqual(due("2026-03-31"), "2026-06-30")
		self.assertEqual(due("2026-06-30"), "2026-06-30")
		self.assertEqual(due("2026-07-01"), "2027-06-30")

	def test_days_after_period_end(self):
		self.assertEqual(str(regulator.due_date("Days After Period End", "2026-03-31", 0, 0, 45)), "2026-05-15")

	def test_unknown_basis_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			regulator.due_date("Whenever", "2026-03-31", 1, 1, 1)


class TestReminderSchedule(UnitTestCase):
	def test_offsets_are_parsed_and_sorted(self):
		self.assertEqual(regulator.reminder_offsets("1, 30,7"), [30, 7, 1])
		self.assertEqual(regulator.reminder_offsets(""), [])

	def test_bad_offsets_are_refused(self):
		for text in ("30,x", "-1"):
			with self.assertRaises(frappe.ValidationError):
				regulator.reminder_offsets(text)

	def test_stage_before_on_and_after_the_due_date(self):
		offsets = [30, 7, 1]
		stage = lambda on: regulator.stage("2026-11-30", on, offsets)  # noqa: E731
		self.assertEqual(stage("2026-10-31"), ("reminder", 30))
		self.assertEqual(stage("2026-11-23"), ("reminder", 7))
		self.assertEqual(stage("2026-11-29"), ("reminder", 1))
		self.assertIsNone(stage("2026-11-10"))
		self.assertIsNone(stage("2026-11-30"))  # due today: nothing new, not yet late
		self.assertEqual(stage("2026-12-01"), ("overdue", 1))
		self.assertEqual(stage("2026-12-10"), ("overdue", 10))


class TestCompliance(UnitTestCase):
	def test_below_minimum_is_flagged(self):
		self.assertEqual(committees.meeting_status(2, 1), "Below minimum")
		self.assertEqual(committees.meeting_status(2, 2), "Compliant")
		self.assertEqual(committees.meeting_status(2, 3), "Compliant")
		self.assertEqual(committees.meeting_status(0, 0), "No minimum set")


class TestIQACOperations(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "IOC")
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()

	def setUp(self):
		frappe.db.savepoint("iqac_ops")
		self.addCleanup(frappe.db.rollback, save_point="iqac_ops")
		sendmail = patch("frappe.sendmail", return_value=frappe._dict(name="test-mail"))
		sendmail.start()
		self.addCleanup(sendmail.stop)
		from campus.academic_governance.seed import seed_body_types, seed_message_templates
		from campus.iqac.regulator_seed import seed_regulator_templates

		seed_body_types()
		seed_message_templates()
		seed_regulator_templates()
		self.employee = self.make_employee()
		self.start, self.end = add_days(today(), -300), add_days(today(), 30)

	def make_employee(self):
		return frappe.get_doc(
			{
				"doctype": "Employee", "first_name": "Iqac", "last_name": frappe.generate_hash(length=6), "gender": "Male",
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": COLLEGE,
				"personal_email": f"{frappe.generate_hash(length=8)}@example.com",
			}
		).insert().name  # fmt: skip

	def make_body(self, body_type="IQAC", minimum=2):
		frappe.db.set_value("Body Type", body_type, "min_meetings_per_year", minimum)
		return frappe.get_doc(
			{
				"doctype": "Body", "body_name": f"Ops {body_type} {frappe.generate_hash(length=4)}", "company": COLLEGE, "body_type": body_type,
				"members": [{"category": "Internal", "employee": self.employee, "from_date": add_days(today(), -500)}],
			}
		).insert().name  # fmt: skip

	def make_meeting(self, body, days=-10, status="Held"):
		meeting = frappe.get_doc(
			{"doctype": "Body Meeting", "body": body, "meeting_date": add_days(today(), 30), "venue": "Room 1"}
		).insert()
		frappe.db.set_value("Body Meeting", meeting.name, {"meeting_date": add_days(today(), days), "status": status})
		return meeting.name

	def filters(self, **extra):
		return {"company": COLLEGE, "from_date": self.start, "to_date": self.end, **extra}

	# AC1
	def test_committee_below_minimum_is_flagged_on_the_report(self):
		body = self.make_body(minimum=2)
		self.make_meeting(body, -20)
		self.make_meeting(body, -5, status="Cancelled")  # a cancelled meeting is not a meeting held
		self.make_meeting(body, -400)  # outside the year
		rows = committee_compliance.execute(self.filters())[1]
		row = next(r for r in rows if r["body"] == body)
		self.assertEqual((row["required"], row["held"], row["status"]), (2, 1, "Below minimum"))
		self.make_meeting(body, -3)
		row = next(r for r in committee_compliance.execute(self.filters())[1] if r["body"] == body)
		self.assertEqual((row["held"], row["status"]), (2, "Compliant"))

	def test_composition_shortfall_is_listed(self):
		body = self.make_body("IQAC", minimum=0)
		with patch("campus.academic_governance.api.composition_shortfalls", return_value=[frappe._dict(rule="at least 1 University Nominee")]):
			row = next(r for r in committee_compliance.execute(self.filters())[1] if r["body"] == body)
		self.assertIn("University Nominee", row["composition"])

	# calendar
	def test_calendar_lists_iqac_meetings_and_regulator_due_dates_only(self):
		iqac = self.make_body("IQAC")
		other = self.make_body("Library Committee", minimum=0)
		meeting, other_meeting = self.make_meeting(iqac, 10, "Scheduled"), self.make_meeting(other, 10, "Scheduled")
		submission = self.make_submission(due_in=15)
		refs = {r["reference"] for r in iqac_calendar.execute(self.filters(to_date=add_days(today(), 60)))[1]}
		self.assertIn(meeting, refs)
		self.assertIn(submission.name, refs)
		self.assertNotIn(other_meeting, refs)

	# ATR
	def test_atr_comes_from_action_items(self):
		body = self.make_body("IQAC", 0)
		meeting = self.make_meeting(body, -20)
		open_item = self.make_item(body, meeting, due=add_days(today(), -2))
		done_item = self.make_item(body, meeting, due=add_days(today(), -2), status="Done", action_taken="Circular issued")
		rows = {r["action_item"]: r for r in iqac_action_taken_report.execute(self.filters())[1]}
		self.assertEqual(rows[open_item]["state"], "Overdue")
		self.assertEqual(rows[done_item]["state"], "Done")
		self.assertEqual(rows[done_item]["action_taken"], "Circular issued")

	def make_item(self, body, meeting, due, status="Open", action_taken=None):
		return frappe.get_doc(
			{
				"doctype": "Meeting Action Item", "body_meeting": meeting, "body": body, "responsible": self.employee,
				"due_date": due, "status": status, "action": "Follow up", "action_taken": action_taken,
			}
		).insert().name  # fmt: skip

	# regulator submissions
	def make_type(self, **values):
		return frappe.get_doc(
			{
				"doctype": "Regulator Submission Type", "type_name": f"Test Return {frappe.generate_hash(length=5)}", "regulator": "Test Regulator",
				"due_basis": "Days After Period End", "days_after": 30, "reminder_days": "30,7,1", **values,
			}
		).insert()  # fmt: skip

	def make_submission(self, due_in=None, **values):
		kind = self.make_type()
		period_end = add_days(today(), (due_in or 30) - 30)  # due = period end + 30
		return frappe.get_doc(
			{"doctype": "Regulator Submission", "submission_type": kind.name, "company": COLLEGE, "period_end": period_end, "owner_employee": self.employee, **values}
		).insert()

	def test_due_date_is_computed_from_the_type_rule(self):
		submission = self.make_submission(due_in=20)
		self.assertEqual(str(submission.due_date), str(add_days(today(), 20)))
		self.assertEqual(submission.status, "Pending")

	def test_submitted_needs_a_date_and_stops_reminders(self):
		submission = self.make_submission(due_in=7)
		submission.status = "Submitted"
		with self.assertRaises(frappe.ValidationError):
			submission.save()
		submission.reload()
		submission.status = "Submitted"
		submission.submitted_on = today()
		submission.save()
		self.assertEqual(regulator.send_reminders(today()), 0)

	def logs(self, submission):
		return frappe.get_all("Message Log", {"reference_doctype": "Regulator Submission", "reference_name": submission.name}, ["event_key", "recipient"])

	def test_owner_is_reminded_at_the_offsets_once(self):
		submission = self.make_submission(due_in=7)
		self.assertEqual(regulator.send_reminders(today()), 1)
		self.assertEqual(regulator.send_reminders(today()), 1)  # a repeat run does not message twice
		logs = self.logs(submission)
		self.assertEqual([l.event_key for l in logs], ["regulator_submission.reminder"])
		self.assertTrue(logs[0].recipient.endswith(self.employee))

	def test_no_reminder_between_offsets(self):
		self.make_submission(due_in=15)
		self.assertEqual(regulator.send_reminders(today()), 0)

	# AC2
	def test_overdue_goes_to_owner_and_escalates_to_the_principal(self):
		principal = "principal.ops@example.com"
		if not frappe.db.exists("User", principal):
			frappe.get_doc({"doctype": "User", "email": principal, "first_name": "Principal", "send_welcome_email": 0}).insert()
		submission = self.make_submission(due_in=-3)
		with patch("campus.iqac.regulator.principals", return_value=[principal]):
			self.assertEqual(regulator.send_reminders(today()), 1)
		keys = {(l.event_key, l.recipient.split(":")[-1]) for l in self.logs(submission)}
		self.assertIn(("regulator_submission.overdue", self.employee), keys)
		self.assertIn(("regulator_submission.escalation", principal), keys)

	# MoU
	def test_mou_period_and_activities(self):
		mou = frappe.get_doc(
			{
				"doctype": "Institutional MoU", "company": COLLEGE, "partner": "Acme Industries", "partner_type": "Industry", "purpose": "Internships",
				"valid_from": "2026-01-01", "valid_to": "2028-12-31", "used_for": "Placement",
				"activities": [{"activity_date": "2026-03-01", "activity": "Industry talk"}],
			}
		).insert()  # fmt: skip
		self.assertEqual(mou.status, "Active")
		mou.valid_to = "2025-12-31"
		with self.assertRaises(frappe.ValidationError):
			mou.save()

	def test_mou_activity_outside_period_is_refused(self):
		doc = frappe.get_doc(
			{
				"doctype": "Institutional MoU", "company": COLLEGE, "partner": "Acme", "partner_type": "Industry", "purpose": "x",
				"valid_from": "2026-01-01", "valid_to": "2026-12-31", "activities": [{"activity_date": "2027-02-01", "activity": "Late"}],
			}
		)  # fmt: skip
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
