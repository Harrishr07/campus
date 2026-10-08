"""P2-T02 (M02-03, M01-04) tests: quorum rule (unit), and Body Meeting behaviour (integration): AC1 notice timing against
the Governance Settings notice days with an override reason, AC2 quorum Met / Not met from the Body Type rule and no
resolutions without it, AC3 resolution numbers unique per body per year, AC4 weekly reminders for overdue action items."""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import add_days, getdate, today

from campus.academic_governance import actions, esign, quorum
from campus.tests.factories import make_company
from campus.tests.utils import CampusTestCase

COLLEGE = "Meeting Test College"
NOTICE = "body_meeting.notice"
OVERDUE = "meeting_action.overdue"


def person(key, category="Internal"):
	return frappe._dict(employee=key, external_member=None, category=category)


class TestQuorumRule(UnitTestCase):
	def status(self, percent, in_office, present, mandatory=()):
		return quorum.quorum_status(percent, list(mandatory), in_office, present)

	def test_half_of_four_is_two(self):
		members = [person(f"E{i}") for i in range(4)]
		self.assertEqual(self.status(50, members, ["E0", "E1"]).met, True)
		self.assertEqual(self.status(50, members, ["E0"]).met, False)
		self.assertEqual(self.status(50, members, ["E0"]).required, 2)

	def test_required_rounds_up(self):
		members = [person(f"E{i}") for i in range(5)]
		self.assertEqual(self.status(50, members, []).required, 3)

	def test_mandatory_category_must_be_present(self):
		members = [person("E0"), person("E1"), person("E2"), person("N0", "University Nominee")]
		result = self.status(50, members, ["E0", "E1", "E2"], ["University Nominee"])
		self.assertFalse(result.met)
		self.assertEqual(result.missing_categories, ["University Nominee"])
		self.assertTrue(self.status(50, members, ["E0", "N0"], ["University Nominee"]).met)

	def test_present_people_outside_the_members_in_office_do_not_count(self):
		members = [person("E0"), person("E1")]
		self.assertEqual(self.status(50, members, ["E0", "GONE"]).present, 1)

	def test_external_members_are_keyed_apart_from_employees(self):
		nominee = frappe._dict(employee=None, external_member="EXT-1", category="University Nominee")
		self.assertTrue(self.status(0, [nominee], ["EXT-1"], ["University Nominee"]).met)

	def test_a_meeting_always_needs_at_least_one_person(self):
		self.assertFalse(self.status(0, [], []).met)
		self.assertEqual(self.status(0, [], []).required, 1)
		self.assertTrue(self.status(0, [person("E0"), person("E1")], ["E1"]).met)


class TestNoticeRule(UnitTestCase):
	def test_notice_needs_the_full_days(self):
		from campus.academic_governance.notice import notice_is_late

		self.assertFalse(notice_is_late("2026-11-10", "2026-11-03", 7))  # exactly 7 days
		self.assertTrue(notice_is_late("2026-11-10", "2026-11-04", 7))
		self.assertFalse(notice_is_late("2026-11-10", "2026-10-01", 7))
		self.assertFalse(notice_is_late("2026-11-10", "2026-11-10", 0))


class TestESignAdapter(UnitTestCase):
	def test_no_provider_is_a_clear_error(self):
		esign._providers.clear()
		with self.assertRaises(frappe.ValidationError):
			esign.get_provider()

	def test_a_registered_provider_is_returned(self):
		class Fake(esign.ESignProvider):
			def request_signature(self, doctype, name, signers):
				return "ref-1"

			def status(self, reference):
				return "Pending"

		self.addCleanup(esign._providers.clear)
		esign.register_provider("fake", Fake())
		self.assertEqual(esign.get_provider("fake").request_signature("Body Meeting", "M1", []), "ref-1")
		self.assertIs(esign.get_provider(), esign.get_provider("fake"))

	def test_the_interface_cannot_be_used_directly(self):
		with self.assertRaises(TypeError):
			esign.ESignProvider()


class TestBodyMeetings(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "MTC")
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()

	def setUp(self):
		frappe.db.savepoint("meeting_test")
		self.addCleanup(frappe.db.rollback, save_point="meeting_test")
		sendmail = patch("frappe.sendmail", return_value=frappe._dict(name="test-mail"))  # the test site has no outgoing Email Account; a failed attempt would be retried
		sendmail.start()
		self.addCleanup(sendmail.stop)
		from campus.academic_governance.seed import seed_body_types

		seed_body_types()
		frappe.db.set_single_value("Governance Settings", "notice_days", 7)
		self.employees = [self.employee() for _ in range(3)]
		self.nominee = frappe.get_doc({"doctype": "External Member", "member_name": "Nominee N", "email": "nominee.n@example.com"}).insert().name
		self.body = self.make_body("Test Governing Body")

	def employee(self):
		return frappe.get_doc(
			{
				"doctype": "Employee", "first_name": "Mtg", "last_name": frappe.generate_hash(length=6), "gender": "Male",
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": COLLEGE,
				"personal_email": f"{frappe.generate_hash(length=8)}@example.com",
			}
		).insert().name  # fmt: skip

	def make_body(self, name, nominee_to=None):
		start = add_days(today(), -60)
		members = [{"category": "Internal", "employee": e, "from_date": start} for e in self.employees]
		members.append({"category": "University Nominee", "external_member": self.nominee, "from_date": start, "to_date": nominee_to})
		return frappe.get_doc(
			{"doctype": "Body", "body_name": name, "company": COLLEGE, "body_type": "Governing Body", "members": members}
		).insert().name  # fmt: skip

	def meeting(self, days_ahead=30, body=None, **values):
		return frappe.get_doc(
			{"doctype": "Body Meeting", "body": body or self.body, "meeting_date": add_days(today(), days_ahead), "venue": "Board Room", **values}
		).insert()

	def attend(self, meeting, *present):
		"""Mark these people (Employee ids or External Member ids) present, then save."""
		meeting.reload()
		for row in meeting.attendance:
			row.present = int((row.employee or row.external_member) in present)
		meeting.save()
		return meeting

	# attendance and quorum (AC2)
	def test_attendance_is_filled_from_the_members_in_office_on_the_meeting_date(self):
		meeting = self.meeting()
		self.assertEqual(sorted((r.employee or r.external_member) for r in meeting.attendance), sorted([*self.employees, self.nominee]))
		self.assertEqual({r.present for r in meeting.attendance}, {0})
		self.assertEqual((meeting.quorum_status, meeting.in_office_count, meeting.quorum_required), ("Not met", 4, 2))

	def test_quorum_is_met_with_half_and_the_university_nominee(self):
		meeting = self.attend(self.meeting(), self.employees[0], self.nominee)
		self.assertEqual((meeting.quorum_status, meeting.present_count), ("Met", 2))

	def test_quorum_is_not_met_without_the_mandatory_nominee(self):
		meeting = self.attend(self.meeting(), *self.employees)
		self.assertEqual(meeting.quorum_status, "Not met")
		self.assertIn("University Nominee", meeting.quorum_note)

	def test_member_whose_term_ended_before_the_meeting_is_not_counted(self):
		body = self.make_body("Lapsing Body", nominee_to=add_days(today(), 10))
		meeting = self.meeting(30, body=body)
		self.assertEqual(meeting.in_office_count, 3)  # nominee's term ends before the meeting
		self.assertNotIn(self.nominee, [r.external_member for r in meeting.attendance])
		self.assertEqual(self.attend(meeting, *self.employees).quorum_status, "Not met")  # nominee mandatory, none in office

	def test_resolutions_are_refused_without_quorum(self):
		meeting = self.meeting()
		meeting.append("resolutions", {"resolution_text": "Approve the budget", "decision": "Approved"})
		with self.assertRaises(frappe.ValidationError) as caught:
			meeting.save()
		self.assertIn("quorum", str(caught.exception).lower())

	# resolution numbering (AC3)
	def test_resolutions_are_numbered_per_body_and_year(self):
		first = self.attend(self.meeting(30), self.employees[0], self.nominee)
		for text in ("Approve the budget", "Adopt the calendar"):
			first.append("resolutions", {"resolution_text": text, "decision": "Approved"})
		first.save()
		year = getdate(first.meeting_date).year
		self.assertEqual([r.resolution_no for r in first.resolutions], [f"{self.body}/{year}/001", f"{self.body}/{year}/002"])

		second = self.attend(self.meeting(40), self.employees[1], self.nominee)
		second.append("resolutions", {"resolution_text": "Ratify", "decision": "Approved"})
		second.save()
		self.assertEqual(second.resolutions[0].resolution_no, f"{self.body}/{getdate(second.meeting_date).year}/003")

		first.reload()
		first.save()  # saving again keeps the numbers
		self.assertEqual([r.resolution_no for r in first.resolutions][-1], f"{self.body}/{year}/002")

	def test_numbering_restarts_each_year_and_is_independent_per_body(self):
		other = self.make_body("Other Governing Body")
		this_year = self.attend(self.meeting(30), self.employees[0], self.nominee)
		this_year.append("resolutions", {"resolution_text": "A", "decision": "Approved"})
		this_year.save()
		next_year = self.attend(self.meeting(400), self.employees[0], self.nominee)
		next_year.append("resolutions", {"resolution_text": "B", "decision": "Approved"})
		next_year.save()
		elsewhere = self.attend(self.meeting(30, body=other), self.employees[0], self.nominee)
		elsewhere.append("resolutions", {"resolution_text": "C", "decision": "Approved"})
		elsewhere.save()
		self.assertTrue(next_year.resolutions[0].resolution_no.endswith("/001"))
		self.assertTrue(elsewhere.resolutions[0].resolution_no.endswith("/001"))
		self.assertTrue(this_year.resolutions[0].resolution_no.endswith("/001"))
		self.assertEqual(len({m.resolutions[0].resolution_no for m in (this_year, next_year, elsewhere)}), 3)

	def test_a_resolution_can_carry_a_proposal_reference_for_the_proposal_stage(self):
		meeting = self.attend(self.meeting(), self.employees[0], self.nominee)
		meeting.append("resolutions", {"resolution_text": "Adopt syllabus", "decision": "Approved", "proposal": "PROP-0001"})
		meeting.save()
		self.assertEqual(meeting.resolutions[0].proposal, "PROP-0001")

	# notice (AC1)
	def notice_logs(self, meeting, event=NOTICE):
		return frappe.get_all("Message Log", {"event_key": event, "reference_name": meeting.name}, ["recipient", "status"])

	def test_notice_in_time_is_sent_to_every_member(self):
		meeting = self.meeting(10)
		meeting.send_notice()
		meeting.reload()
		self.assertTrue(meeting.notice_sent_on)
		self.assertEqual(len(self.notice_logs(meeting)), len(self.employees) + 1)  # the external nominee too

	def test_late_notice_needs_an_override_reason(self):
		meeting = self.meeting(3)
		with self.assertRaises(frappe.ValidationError):
			meeting.send_notice()
		self.assertFalse(frappe.db.get_value("Body Meeting", meeting.name, "notice_sent_on"))
		meeting.send_notice(override_reason="Urgent: affiliation inspection")
		meeting.reload()
		self.assertEqual(meeting.notice_override_reason, "Urgent: affiliation inspection")
		self.assertTrue(meeting.notice_sent_on)

	def test_the_notice_days_come_from_governance_settings(self):
		meeting = self.meeting(10)
		frappe.db.set_single_value("Governance Settings", "notice_days", 14)
		with self.assertRaises(frappe.ValidationError):
			meeting.send_notice()
		frappe.db.set_single_value("Governance Settings", "notice_days", 10)
		meeting.send_notice()

	def test_notice_is_sent_once_and_not_for_past_or_cancelled_meetings(self):
		meeting = self.meeting(10)
		meeting.send_notice()
		with self.assertRaises(frappe.ValidationError):
			meeting.send_notice()
		past = self.meeting(-1)
		with self.assertRaises(frappe.ValidationError):
			past.send_notice(override_reason="late")

	def test_the_external_nominee_gets_the_notice_by_email_and_consent_is_respected(self):
		meeting = self.meeting(10)
		meeting.send_notice()
		(log,) = [log for log in self.notice_logs(meeting) if log.recipient == f"External Member:{self.nominee}"]
		self.assertNotEqual(log.status, "Skipped")
		other = self.meeting(11, body=self.make_body("Second Body"))
		frappe.get_doc(
			{"doctype": "Communication Consent", "party_type": "External Member", "party": self.nominee, "channel": "email", "purpose": "transactional", "status": "Opted Out"}
		).insert()  # fmt: skip
		other.send_notice()
		(skipped,) = [log for log in self.notice_logs(other) if log.recipient == f"External Member:{self.nominee}"]
		self.assertEqual(skipped.status, "Skipped")

	def test_consent_is_respected(self):
		employee = self.employees[0]
		frappe.get_doc(
			{"doctype": "Communication Consent", "party_type": "Employee", "party": employee, "channel": "email", "purpose": "transactional", "status": "Opted Out"}
		).insert()  # fmt: skip
		meeting = self.meeting(10)
		meeting.send_notice()
		sent = [log for log in self.notice_logs(meeting) if log.status != "Skipped"]
		self.assertEqual(len(sent), len(self.employees))  # two employees and the nominee

	# action items (AC4)
	def action(self, meeting, due_in, status="Open", **values):
		return frappe.get_doc(
			{
				"doctype": "Meeting Action Item", "body_meeting": meeting.name, "action": "Circulate minutes", "responsible": self.employees[0],
				"due_date": add_days(today(), due_in), "status": status, **values,
			}
		).insert()  # fmt: skip

	def test_overdue_open_items_notify_their_owner(self):
		meeting = self.meeting(-5)
		overdue = self.action(meeting, -3)
		self.action(meeting, -3, status="Done", action_taken="Circulated")
		self.action(meeting, 4)
		self.assertEqual(actions.notify_overdue(), 1)
		logs = self.notice_logs(overdue, OVERDUE)
		self.assertEqual(len(logs), 1)
		self.assertIn(self.employees[0], logs[0].recipient)

	def test_the_reminder_goes_out_once_a_week(self):
		meeting = self.meeting(-5)
		overdue = self.action(meeting, -3)
		actions.notify_overdue()
		actions.notify_overdue()  # same week: no second message
		self.assertEqual(len(self.notice_logs(overdue, OVERDUE)), 1)
		actions.notify_overdue(on_date=add_days(today(), 8))  # next week
		self.assertEqual(len(self.notice_logs(overdue, OVERDUE)), 2)

	def test_the_weekly_scheduler_runs_the_reminder(self):
		self.assertIn("campus.academic_governance.actions.notify_overdue", frappe.get_hooks("scheduler_events")["weekly"])

	def test_a_done_item_records_the_action_taken(self):
		meeting = self.meeting(-5)
		with self.assertRaises(frappe.ValidationError):
			self.action(meeting, -3, status="Done")

	# prints
	def render(self, meeting, print_format):
		return frappe.get_print("Body Meeting", meeting.name, print_format=print_format)

	def test_the_five_prints_render_their_content(self):
		meeting = self.attend(self.meeting(10, agenda=[{"item": "Budget 2027", "presenter": self.employees[0]}]), self.employees[0], self.nominee)
		meeting.append("resolutions", {"resolution_text": "Approve the budget", "decision": "Approved"})
		meeting.minutes = "<p>Discussed at length</p>"
		meeting.save()
		self.action(meeting, 5, action="Publish the budget")
		self.assertIn("Budget 2027", self.render(meeting, "Meeting Notice"))
		self.assertIn("Board Room", self.render(meeting, "Meeting Notice"))
		self.assertIn("Budget 2027", self.render(meeting, "Meeting Agenda"))
		minutes = self.render(meeting, "Meeting Minutes")
		self.assertIn("Discussed at length", minutes)
		self.assertIn("Approve the budget", minutes)
		extract = self.render(meeting, "Resolution Extract")
		self.assertIn(meeting.resolutions[0].resolution_no, extract)
		self.assertIn("Approve the budget", extract)
		self.assertIn("Publish the budget", self.render(meeting, "Action Taken Report"))
