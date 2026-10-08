"""M06-02 integration tests: Malpractice Report goes through the approval engine; an approved Debarment debars
the student's Exam Registration (T14 flag, every course "Not eligible (Debarred)"); evidence is a private File
attached to the report; reports are confidential (exam office, Principal, Dean Academics; an invigilator reads
only their own); only a System Manager cancels."""

import os

import frappe
from frappe.utils.file_manager import get_file_path

from campus.campus_platform.approvals import approve, request_approval
from campus.examinations.setup import MALPRACTICE_POLICY, seed_coe_policy
from campus.tests import demo
from campus.tests.approval_fixtures import level
from campus.tests.test_exam_seating import COE_USER, DAY1, SeatingFixture, course

DEBARRED = "Not eligible (Debarred)"
INVIGILATOR, OTHER_INVIGILATOR = demo.email("faculty_1"), demo.email("faculty_2")


class MalpracticeFixture(SeatingFixture):
	test_policy = True

	def setUp(self):
		super().setUp()
		self.student = self.students[0]
		if self.test_policy:
			frappe.db.delete("Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.policies()]})
			frappe.db.delete("Approval Policy", {"document_type": "Malpractice Report"})
			frappe.get_doc(
				{"doctype": "Approval Policy", "policy_name": "Seat Test Malpractice", "document_type": "Malpractice Report",
				"levels": [level("User", COE_USER, title="COE")]}
			).insert()  # fmt: skip

	def policies(self):
		return frappe.get_all("Approval Policy", {"document_type": "Malpractice Report"}, pluck="name") or [""]

	def evidence(self, private=1):
		"""A real File uploaded by the current user, as the form's attach dialog leaves it (not yet attached)."""
		doc = frappe.get_doc({"doctype": "File", "file_name": f"seat-chit-{frappe.generate_hash(length=6)}.txt", "content": "chit", "is_private": private}).insert()
		path = get_file_path(doc.file_url)
		self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
		return doc.file_url

	def report(self, decision="Debarment", evidence=None, course_key="C1"):
		return frappe.get_doc(
			{
				"doctype": "Malpractice Report", "exam_session": self.session, "student": self.student, "course": course(course_key),
				"exam_date": DAY1, "room": self.rooms["Seat Hall A"], "category": "Copying", "description": "Chit found under the desk",
				"evidence": [{"file": evidence or self.evidence(), "note": "Photo of the chit"}], "committee_decision": decision,
			}
		).insert()  # fmt: skip

	def approved(self, report, approver=COE_USER):
		request = request_approval("Malpractice Report", report.name)
		user = frappe.session.user
		frappe.set_user(approver)
		approve(request, None)
		frappe.set_user(user)
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

	def test_only_a_system_manager_cancels_and_cancelling_lifts_the_debarment(self):
		report = self.approved(self.report())
		frappe.set_user(COE_USER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Malpractice Report", report.name).cancel()
		frappe.set_user("Administrator")
		report.reload().cancel()
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

	def test_evidence_must_be_a_private_file_of_this_report(self):
		with self.assertRaisesRegex(frappe.ValidationError, "private"):
			self.report(evidence=self.evidence(private=0))
		with self.assertRaisesRegex(frappe.ValidationError, "private"):
			self.report(evidence="/private/files/not-uploaded.jpg")
		first = self.report()
		url = first.evidence[0].file
		self.assertEqual(
			frappe.db.get_value("File", {"file_url": url}, ["attached_to_doctype", "attached_to_name"]), ("Malpractice Report", first.name)
		)
		with self.assertRaisesRegex(frappe.ValidationError, "another document"):
			self.report(evidence=url)  # a file attached to another report cannot be borrowed

	def test_the_course_must_be_in_the_students_registration(self):
		with self.assertRaisesRegex(frappe.ValidationError, "not registered"):
			self.report(course_key="C2")  # student 0 writes C1, not C2

	def test_a_student_without_a_registration_in_the_session_is_refused(self):
		self.student = self.make_outsider()
		with self.assertRaises(frappe.ValidationError):
			self.report()


class TestConfidentiality(MalpracticeFixture):
	def test_an_invigilator_files_and_reads_only_their_own_report_and_evidence(self):
		frappe.set_user(INVIGILATOR)
		report = self.report()
		file = frappe.get_doc("File", {"file_url": report.evidence[0].file})
		self.assertTrue(frappe.has_permission("Malpractice Report", "read", doc=report.name, user=INVIGILATOR))
		frappe.set_user("Administrator")
		for user in (OTHER_INVIGILATOR, demo.email("student_1")):
			self.assertFalse(frappe.has_permission("Malpractice Report", "read", doc=report.name, user=user), user)
			self.assertFalse(frappe.has_permission("File", "read", doc=file, user=user), user)
		frappe.set_user(OTHER_INVIGILATOR)
		self.assertEqual(frappe.get_list("Malpractice Report", pluck="name"), [])
		frappe.set_user("Administrator")
		for user in (COE_USER, demo.email("principal"), INVIGILATOR):
			self.assertTrue(frappe.has_permission("File", "read", doc=file, user=user), user)


class TestSeededPolicy(MalpracticeFixture):
	test_policy = False

	def test_an_invigilator_files_and_the_coe_position_holder_approves(self):
		if not frappe.db.exists("Approval Policy", {"document_type": "Malpractice Report"}):
			seed_coe_policy(MALPRACTICE_POLICY, "Malpractice Report")
		coe = demo.email("coe")
		frappe.get_doc(
			{"doctype": "Position Holder", "position": "COE", "scope_value": demo.ENGINEERING, "user": coe,
			"employee": demo.employee_of("coe"), "from_date": "2022-06-01"}
		).insert()  # fmt: skip
		frappe.set_user(INVIGILATOR)
		report = self.report()
		report = self.approved(report, approver=coe)
		frappe.set_user("Administrator")
		self.assertEqual(report.docstatus, 1)
		self.assertEqual(self.registration().debarred, 1)
