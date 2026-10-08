"""M06-02 integration tests: Malpractice Report goes through the approval engine; an approved Debarment debars
the student's Exam Registration (T14 flag, every course "Not eligible (Debarred)"); evidence must be private."""

import frappe

from campus.campus_platform.approvals import approve, request_approval
from campus.tests import demo
from campus.tests.approval_fixtures import level
from campus.tests.test_exam_seating import COE_USER, DAY1, SeatingFixture, course

DEBARRED = "Not eligible (Debarred)"


class MalpracticeFixture(SeatingFixture):
	def setUp(self):
		super().setUp()
		self.student = self.students[0]
		frappe.db.delete("Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.policies()]})
		frappe.db.delete("Approval Policy", {"document_type": "Malpractice Report"})
		frappe.get_doc(
			{"doctype": "Approval Policy", "policy_name": "Seat Test Malpractice", "document_type": "Malpractice Report",
			"levels": [level("User", COE_USER, title="COE")]}
		).insert()  # fmt: skip

	def policies(self):
		return frappe.get_all("Approval Policy", {"document_type": "Malpractice Report"}, pluck="name") or [""]

	def report(self, decision="Debarment", evidence="/private/files/seat-chit.jpg"):
		return frappe.get_doc(
			{
				"doctype": "Malpractice Report", "exam_session": self.session, "student": self.student, "course": course("C1"),
				"exam_date": DAY1, "room": self.rooms["Seat Hall A"], "category": "Copying", "description": "Chit found under the desk",
				"evidence": [{"file": evidence, "note": "Photo of the chit"}], "committee_decision": decision,
			}
		).insert()  # fmt: skip

	def approved(self, report):
		request = request_approval("Malpractice Report", report.name)
		frappe.set_user(COE_USER)
		approve(request, None)
		frappe.set_user("Administrator")
		return report.reload()

	def make_outsider(self):
		return frappe.get_doc({"doctype": "Student", "first_name": "Seat Outsider", "student_email_id": "seat-outsider@example.com", "oc_company": demo.ENGINEERING}).insert().name

	def registration(self):
		return frappe.get_doc("Exam Registration", f"EXR-{self.session}-{self.student}")


class TestMalpractice(MalpracticeFixture):
	def test_an_approved_debarment_debars_the_exam_registration(self):
		report = self.approved(self.report())
		self.assertEqual(report.docstatus, 1)
		registration = self.registration()
		self.assertEqual((registration.debarred, registration.debarment_reason), (1, f"Malpractice {report.name}: Copying"))
		self.assertEqual({row.eligibility for row in registration.courses}, {DEBARRED})

	def test_cancelling_the_report_lifts_its_debarment(self):
		report = self.approved(self.report())
		report.cancel()
		registration = self.registration()
		self.assertEqual((registration.debarred, registration.debarment_reason), (0, None))
		self.assertNotIn(DEBARRED, {row.eligibility for row in registration.courses})

	def test_a_warning_does_not_debar(self):
		self.approved(self.report(decision="Warning"))
		self.assertEqual(self.registration().debarred, 0)

	def test_the_report_waits_for_approval_and_needs_a_policy_and_a_decision(self):
		report = self.report()
		with self.assertRaises(frappe.ValidationError):
			report.submit()  # a policy exists: only its approval submits
		frappe.db.delete("Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.policies()]})
		frappe.db.delete("Approval Policy", {"document_type": "Malpractice Report"})
		with self.assertRaisesRegex(frappe.ValidationError, "only by its approval"):
			request_approval("Malpractice Report", report.name)
		self.assertEqual(self.registration().debarred, 0)

	def test_approval_without_a_committee_decision_is_refused(self):
		report = self.report(decision="")
		with self.assertRaisesRegex(frappe.ValidationError, "committee decision"):
			self.approved(report)

	def test_evidence_must_be_a_private_file(self):
		with self.assertRaisesRegex(frappe.ValidationError, "private"):
			self.report(evidence="/files/seat-chit.jpg")

	def test_a_student_without_a_registration_in_the_session_is_refused(self):
		self.student = self.make_outsider()
		with self.assertRaises(frappe.ValidationError):
			self.report()
