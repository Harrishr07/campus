"""M06-03 integration tests: the confidential question paper workflow. Time-window access (System Manager denied
before release too), the Exam Confidential role restriction, the access log, the blueprint check, the print log."""

import io
import os

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime, today
from pypdf import PdfReader, PdfWriter

from campus.examinations import question_papers
from campus.examinations.question_papers import EXAM_CONFIDENTIAL, QPAccessDenied
from campus.examinations.report.question_paper_print_log.question_paper_print_log import execute as print_log
from campus.tests.factories import make_company
from campus.tests.test_results import make_term
from campus.tests.utils import CampusTestCase

COLLEGE = "QP Test College"
COURSE = "QPT Course"
EC_USER = "qp-confidential@example.com"
SM_USER = "qp-sysmanager@example.com"
SM_EC_USER = "qp-sysmanager-ec@example.com"
FACULTY = "qp-faculty@example.com"
QP = "Question Paper"
LOG = "QP Access Log"


def make_login(email, roles, company=COLLEGE):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			"roles": [{"role": r} for r in roles]}).insert()  # fmt: skip
	if not frappe.db.exists("User Permission", {"user": email, "allow": "Company", "for_value": company}):
		frappe.get_doc({"doctype": "User Permission", "user": email, "allow": "Company", "for_value": company}).insert()


def pdf_bytes(title):
	writer, out = PdfWriter(), io.BytesIO()
	writer.add_blank_page(595, 842)
	writer.add_metadata({"/Title": title})
	writer.write(out)
	return out.getvalue()


def pdf_text(content):
	return " ".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


class QuestionPaperFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "QPTC")
		cls.term = make_term("QPT Term", "2022-07-01", "2022-12-31")
		if not frappe.db.exists("Course", COURSE):
			frappe.get_doc({"doctype": "Course", "course_name": COURSE, "oc_company": COLLEGE}).insert()
		make_login(EC_USER, [EXAM_CONFIDENTIAL])
		make_login(SM_USER, ["System Manager"])
		make_login(SM_EC_USER, ["System Manager", EXAM_CONFIDENTIAL])
		make_login(FACULTY, ["Academics User"])
		cls.rooms = [frappe.get_doc({"doctype": "Room", "room_name": f"QPT Hall {n}", "oc_company": COLLEGE}).insert().name for n in (1, 2)]

	def setUp(self):
		frappe.db.savepoint("qp_test")
		frappe.db.set_single_value("Question Paper Settings", {"download_lead_minutes": 30, "slot_minutes": 180,
			"forenoon_starts_at": "10:00:00", "afternoon_starts_at": "14:00:00"})  # fmt: skip
		self.session = frappe.get_doc({"doctype": "Exam Session", "company": COLLEGE, "academic_term": self.term,
			"status": "Draft", "exam_start": add_days(today(), 5), "exam_end": add_days(today(), 20),
			"schedule": [{"course": COURSE, "exam_date": add_days(today(), 10), "slot": "AN"}]}).insert()  # fmt: skip
		self.items = [self.bank_item(co, bloom) for co in ("CO1", "CO2") for bloom in ("Remember", "Apply")]

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.request_ip = None
		frappe.db.rollback(save_point="qp_test")

	def bank_item(self, co, bloom, marks=25):
		return frappe.get_doc({"doctype": "Question Bank Item", "company": COLLEGE, "course": COURSE, "course_outcome": co,
			"bloom_level": bloom, "marks": marks, "difficulty": "Medium", "question": f"Explain {co} {bloom}"}).insert().name  # fmt: skip

	def paper(self, release_in_minutes=120, approve=True, items=None, sets=("A", "B")):
		doc = frappe.get_doc({
			"doctype": QP, "exam_session": self.session.name, "course": COURSE, "total_marks": 100,
			"release_at": add_to_date(now_datetime(), minutes=release_in_minutes),
			"blueprint": [
				{"criterion": "Course Outcome", "value": "CO1", "min_percent": 40, "max_percent": 60},
				{"criterion": "Course Outcome", "value": "CO2", "min_percent": 40, "max_percent": 60},
				{"criterion": "Bloom Level", "value": "Remember", "min_percent": 0, "max_percent": 50},
				{"criterion": "Bloom Level", "value": "Apply", "min_percent": 50, "max_percent": 100},
			],
			"questions": [{"paper_set": s, "question_item": i} for s in ("A", "B") for i in (items or self.items)],
		}).insert()  # fmt: skip
		for paper_set in sets:
			field = f"set_{paper_set.lower()}_file"
			self.attach(doc, field)
			doc.set(field, self.attached_url)
		doc.save()
		for url in (doc.set_a_file, doc.set_b_file):
			if url:
				self.addCleanup(lambda path=frappe.get_site_path(url.strip("/")): os.path.exists(path) and os.remove(path))
		if approve:
			doc.moderation_status = "Approved"
			doc.save()
		return doc

	def attach(self, doc, field):
		file = frappe.get_doc({"doctype": "File", "file_name": f"{doc.name}-{field}.pdf", "content": pdf_bytes(f"{doc.name} {field}"),
			"is_private": 1, "attached_to_doctype": QP, "attached_to_name": doc.name, "attached_to_field": field}).insert()  # fmt: skip
		self.attached_url = file.file_url
		self.addCleanup(lambda path=file.get_full_path(): os.path.exists(path) and os.remove(path))

	def employee(self, first_name):
		if not frappe.db.exists("Gender", "Female"):
			frappe.get_doc({"doctype": "Gender", "gender": "Female"}).insert()
		return frappe.get_doc({"doctype": "Employee", "first_name": first_name, "gender": "Female", "company": COLLEGE,
			"date_of_birth": "1985-01-01", "date_of_joining": "2020-01-01"}).insert().name  # fmt: skip

	def logs(self, paper, **filters):
		return frappe.get_all(LOG, {"question_paper": paper, **filters},
			["user", "action", "result", "reason", "ip_address", "paper_set", "room", "copies"], order_by="creation asc")  # fmt: skip

	def can_read(self, user, paper):
		return frappe.has_permission(QP, "read", doc=frappe.get_doc(QP, paper), user=user)


class TestReleaseWindowAccess(QuestionPaperFixture):
	def test_attachment_is_encrypted_at_rest_and_the_plain_upload_removed(self):
		doc = self.paper()
		self.assertTrue(doc.set_a_file.endswith(".enc"), doc.set_a_file)
		self.assertFalse(frappe.db.exists("File", {"file_url": self.attached_url}))
		sealed = frappe.get_doc("File", {"file_url": doc.set_a_file})
		self.addCleanup(lambda path=sealed.get_full_path(): os.path.exists(path) and os.remove(path))
		self.assertTrue(sealed.is_private)
		with open(sealed.get_full_path(), "rb") as f:
			self.assertNotIn(b"%PDF", f.read())

	def test_before_the_window_nobody_opens_or_downloads_not_even_a_system_manager(self):
		paper = self.paper(release_in_minutes=120).name
		for user in (EC_USER, SM_EC_USER, SM_USER):
			self.assertFalse(self.can_read(user, paper), user)
			frappe.set_user(user)
			if user != SM_USER:  # no list access at all: covered by TestRoleRestriction
				self.assertEqual(frappe.get_list(QP, {"name": paper}, pluck="name"), [], user)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc(QP, paper).check_permission("read")
			with self.assertRaises(QPAccessDenied):
				question_papers.open_paper(paper, "A")
			frappe.set_user("Administrator")
		denied = self.logs(paper, result="Denied", action="Download")
		self.assertEqual({row.user for row in denied}, {EC_USER, SM_EC_USER, SM_USER})
		self.assertTrue({row.user for row in self.logs(paper, result="Denied", action="View")} >= {EC_USER, SM_EC_USER, SM_USER})
		self.assertFalse(self.logs(paper, result="Allowed"))

	def test_inside_the_window_exam_confidential_downloads_a_watermarked_paper(self):
		paper = self.paper(release_in_minutes=10).name
		frappe.local.request_ip = "10.1.2.3"
		frappe.set_user(SM_EC_USER)
		self.assertTrue(frappe.has_permission(QP, "read", doc=frappe.get_doc(QP, paper)))
		content = question_papers.open_paper(paper, "A")
		text = pdf_text(content)
		self.assertIn(SM_EC_USER, text)
		self.assertIn(now_datetime().strftime("%Y-%m-%d"), text)
		self.assertIn(f"{paper} Set A", text)
		frappe.set_user("Administrator")
		(log,) = self.logs(paper, action="Download")
		self.assertEqual((log.user, log.result, log.ip_address, log.paper_set), (SM_EC_USER, "Allowed", "10.1.2.3", "A"))

	def test_a_system_manager_without_the_role_is_denied_inside_the_window(self):
		paper = self.paper(release_in_minutes=10).name
		self.assertFalse(self.can_read(SM_USER, paper))
		frappe.set_user(SM_USER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(QP, pluck="name")
		with self.assertRaises(QPAccessDenied):
			question_papers.open_paper(paper, "A")
		frappe.set_user("Administrator")
		(log,) = self.logs(paper, action="Download")
		self.assertEqual((log.user, log.result), (SM_USER, "Denied"))

	def test_downloads_close_when_the_slot_ends(self):
		paper = self.paper(release_in_minutes=-181).name
		frappe.set_user(EC_USER)
		with self.assertRaises(QPAccessDenied):
			question_papers.open_paper(paper, "A")
		frappe.set_user("Administrator")
		self.assertEqual(self.logs(paper, action="Download")[0].result, "Denied")

	def test_an_unapproved_paper_is_never_downloadable(self):
		paper = self.paper(release_in_minutes=10, approve=False).name
		frappe.set_user(EC_USER)
		with self.assertRaises(QPAccessDenied):
			question_papers.open_paper(paper, "A")

	def test_a_missing_set_is_denied(self):
		paper = self.paper(release_in_minutes=10, sets=("A",)).name
		frappe.set_user(EC_USER)
		with self.assertRaises(QPAccessDenied):
			question_papers.open_paper(paper, "B")

	def test_the_download_endpoint_answers_403_and_keeps_the_log(self):
		paper = self.paper(release_in_minutes=120).name
		frappe.set_user(EC_USER)
		frappe.local.response = frappe._dict()
		question_papers.download_paper(paper, "A")
		self.assertEqual(frappe.local.response.http_status_code, 403)
		self.assertTrue(frappe.local.flags.commit)
		frappe.local.flags.commit = False
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[question_papers.download_paper], ["GET"])

	def test_the_download_endpoint_sends_the_pdf_inside_the_window(self):
		paper = self.paper(release_in_minutes=10).name
		frappe.set_user(EC_USER)
		frappe.local.response = frappe._dict()
		question_papers.download_paper(paper, "A")
		self.assertEqual((frappe.local.response.type, frappe.local.response.filename), ("download", f"{paper}-set-a.pdf"))
		self.assertIn(EC_USER, pdf_text(frappe.local.response.filecontent))
		frappe.local.flags.commit = False

	def test_release_at_defaults_to_the_slot_start_of_the_schedule(self):
		doc = frappe.get_doc({"doctype": QP, "exam_session": self.session.name, "course": COURSE, "total_marks": 100}).insert()
		self.assertEqual(get_datetime(doc.release_at), get_datetime(f"{add_days(today(), 10)} 14:00:00"))
		self.assertEqual(doc.company, COLLEGE)

	def test_a_sealed_paper_cannot_be_changed(self):
		doc = self.paper(release_in_minutes=10)
		doc.total_marks = 90
		with self.assertRaises(frappe.ValidationError):
			doc.save()


class TestRoleRestriction(QuestionPaperFixture):
	def test_only_exam_confidential_reads_bank_items_nominations_and_logs(self):
		item = self.items[0]
		for doctype, name in (("Question Bank Item", item),):
			self.assertTrue(frappe.has_permission(doctype, "read", doc=frappe.get_doc(doctype, name), user=EC_USER))
			for user in (SM_USER, FACULTY):
				self.assertFalse(frappe.has_permission(doctype, "read", doc=frappe.get_doc(doctype, name), user=user), user)
				frappe.set_user(user)
				with self.assertRaises(frappe.PermissionError):
					frappe.get_list(doctype, pluck="name")
				frappe.set_user("Administrator")
		for doctype in ("QP Setter Nomination", LOG, QP):
			self.assertFalse(frappe.has_permission(doctype, "read", user=SM_USER), doctype)

	def test_a_draft_paper_is_open_to_exam_confidential_only(self):
		paper = self.paper(approve=False).name
		self.assertTrue(self.can_read(EC_USER, paper))
		self.assertFalse(self.can_read(SM_USER, paper))
		self.assertFalse(self.can_read(FACULTY, paper))

	def test_confidential_documents_cannot_be_shared(self):
		paper = self.paper(approve=False).name
		for doctype, name in ((QP, paper), ("Question Bank Item", self.items[0])):
			with self.assertRaises(frappe.ValidationError):
				frappe.share.add_docshare(doctype, name, SM_USER, read=1, flags={"ignore_share_permission": True})

	def test_the_paper_file_record_is_not_readable(self):
		doc = self.paper(release_in_minutes=10)
		sealed = frappe.get_doc("File", {"file_url": doc.set_a_file})
		self.addCleanup(lambda path=sealed.get_full_path(): os.path.exists(path) and os.remove(path))
		for user in (EC_USER, SM_USER):
			self.assertFalse(frappe.has_permission("File", "read", doc=sealed, user=user), user)

	def test_a_scrutiniser_cannot_also_be_a_setter(self):
		employee = self.employee("QPT Setter")
		nomination = frappe.get_doc({"doctype": "QP Setter Nomination", "exam_session": self.session.name, "course": COURSE,
			"deadline": add_days(today(), 3), "setters": [{"employee": employee}], "scrutiniser": employee})  # fmt: skip
		with self.assertRaises(frappe.ValidationError):
			nomination.insert()
		nomination.scrutiniser = None
		nomination.insert()
		self.assertEqual(nomination.company, COLLEGE)


class TestBlueprintCheck(QuestionPaperFixture):
	def test_a_paper_off_its_blueprint_cannot_be_approved(self):
		lopsided = [self.bank_item("CO1", "Apply", 50), self.bank_item("CO1", "Remember", 50)]
		doc = self.paper(approve=False, items=lopsided)
		self.assertIn("CO2 is not covered", doc.blueprint_issues)
		doc.moderation_status = "Approved"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_a_paper_on_its_blueprint_is_approved(self):
		doc = self.paper(approve=True)
		self.assertEqual((doc.moderation_status, doc.blueprint_issues or ""), ("Approved", ""))

	def test_questions_must_belong_to_the_course(self):
		other = "QPT Other Course"
		if not frappe.db.exists("Course", other):
			frappe.get_doc({"doctype": "Course", "course_name": other, "oc_company": COLLEGE}).insert()
		item = frappe.get_doc({"doctype": "Question Bank Item", "company": COLLEGE, "course": other, "course_outcome": "CO1",
			"bloom_level": "Apply", "marks": 25, "question": "Other"}).insert().name  # fmt: skip
		with self.assertRaises(frappe.ValidationError):
			self.paper(approve=False, items=self.items[:3] + [item])


class TestPrintLog(QuestionPaperFixture):
	def test_print_log_counts_copies_per_hall_and_logs_every_attempt(self):
		early = self.paper(release_in_minutes=120).name
		paper = self.paper(release_in_minutes=10).name
		hall_1, hall_2 = self.rooms
		frappe.set_user(EC_USER)
		question_papers.print_copies(paper, "A", hall_1, 30)
		question_papers.print_copies(paper, "A", hall_1, 10)
		question_papers.print_copies(paper, "B", hall_2, 25)
		with self.assertRaises(QPAccessDenied):
			question_papers.print_copies(early, "A", hall_1, 5)
		frappe.set_user("Administrator")
		self.assertEqual(self.logs(early, action="Print")[0].result, "Denied")
		frappe.set_user(EC_USER)
		_columns, rows = print_log({"company": COLLEGE, "exam_session": self.session.name})
		frappe.set_user("Administrator")
		self.assertEqual(
			sorted((r["question_paper"], r["paper_set"], r["room"], r["copies"]) for r in rows),
			[(paper, "A", hall_1, 40), (paper, "B", hall_2, 25)],
		)

	def test_copies_must_be_positive(self):
		paper = self.paper(release_in_minutes=10).name
		frappe.set_user(EC_USER)
		with self.assertRaises(frappe.ValidationError):
			question_papers.print_copies(paper, "A", self.rooms[0], 0)
