"""M06-03 integration tests: the confidential question paper workflow. Time-window access (System Manager denied
before release too), the Exam Confidential role restriction, the access log, the blueprint check, the print log,
approval through the engine, and the attacks of review round 1 (foreign sealed file, settings edit, version leak)."""

import io
import os
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime, today
from pypdf import PdfReader, PdfWriter

from campus.campus_platform import approvals
from campus.examinations import question_paper_files, question_paper_setup, question_papers
from campus.examinations.exam_halls import EXAM_HALL
from campus.examinations.question_papers import EXAM_CONFIDENTIAL, QPAccessDenied
from campus.examinations.report.question_paper_print_log.question_paper_print_log import execute as print_log
from campus.tests.factories import make_company
from campus.tests.test_results import make_term
from campus.tests.utils import CampusTestCase

COLLEGE = "QP Test College"
OTHER_COLLEGE = "QP Other Test College"
COURSE = "QPT Course"
EC_USER = "qp-confidential@example.com"
SM_USER = "qp-sysmanager@example.com"
SM_EC_USER = "qp-sysmanager-ec@example.com"
FACULTY = "qp-faculty@example.com"
QP = "Question Paper"
LOG = "QP Access Log"
SETTINGS = "Question Paper Settings"


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


def remove_file(url):
	path = frappe.get_site_path(url.strip("/"))
	if os.path.exists(path):
		os.remove(path)


class QuestionPaperFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "QPTC")
		make_company(OTHER_COLLEGE, "QPOC")
		cls.term = make_term("QPT Term", "2022-10-01", "2022-12-31")
		cls.term_2 = make_term("QPT Term 2", "2022-07-01", "2022-09-30")
		if not frappe.db.exists("Course", COURSE):
			frappe.get_doc({"doctype": "Course", "course_name": COURSE, "oc_company": COLLEGE}).insert()
		make_login(EC_USER, [EXAM_CONFIDENTIAL])
		make_login(SM_USER, ["System Manager"])
		make_login(SM_EC_USER, ["System Manager", EXAM_CONFIDENTIAL])
		make_login(FACULTY, ["Academics User"])
		cls.rooms = [cls.room(f"QPT Hall {n}") for n in (1, 2)]

	@staticmethod
	def room(name, company=COLLEGE, room_type=EXAM_HALL):
		return frappe.get_doc({"doctype": "Room", "room_name": name, "oc_company": company, "oc_room_type": room_type}).insert().name

	def setUp(self):
		frappe.db.savepoint("qp_test")
		frappe.db.set_single_value(SETTINGS, {"download_lead_minutes": 30, "slot_minutes": 180,
			"forenoon_starts_at": "10:00:00", "afternoon_starts_at": "14:00:00"})  # fmt: skip
		frappe.db.delete("Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.policies()]})
		frappe.db.delete("Approval Policy", {"document_type": QP})
		question_paper_setup.seed_approval_policy()
		self.session = self.exam_session(self.term)
		self.session_2 = self.exam_session(self.term_2)
		self.items = [self.bank_item(co, bloom) for co in ("CO1", "CO2") for bloom in ("Remember", "Apply")]
		frappe.cache.delete_keys("campus-qp-list-denied")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.request_ip = None
		frappe.db.rollback(save_point="qp_test")
		frappe.db.after_rollback.reset()
		frappe.db.after_commit.reset()

	def policies(self):
		return frappe.get_all("Approval Policy", {"document_type": QP}, pluck="name") or [""]

	def exam_session(self, term):
		return frappe.get_doc({"doctype": "Exam Session", "company": COLLEGE, "academic_term": term,
			"status": "Draft", "exam_start": add_days(today(), 5), "exam_end": add_days(today(), 20),
			"schedule": [{"course": COURSE, "exam_date": add_days(today(), 10), "slot": "AN"}]}).insert()  # fmt: skip

	def bank_item(self, co, bloom, marks=25, **extra):
		return frappe.get_doc({"doctype": "Question Bank Item", "company": COLLEGE, "course": COURSE, "course_outcome": co,
			"bloom_level": bloom, "marks": marks, "difficulty": "Medium", "question": f"Explain {co} {bloom}", **extra}).insert().name  # fmt: skip

	def draft(self, release_in_minutes=120, items=None, sets=("A", "B"), session=None):
		doc = frappe.get_doc({
			"doctype": QP, "exam_session": (session or self.session).name, "course": COURSE, "total_marks": 100,
			"release_at": add_to_date(now_datetime(), minutes=release_in_minutes),
			"blueprint": [
				{"criterion": "Course Outcome", "value": "CO1", "min_percent": 40, "max_percent": 60},
				{"criterion": "Course Outcome", "value": "CO2", "min_percent": 40, "max_percent": 60},
				{"criterion": "Bloom Level", "value": "Remember", "min_percent": 0, "max_percent": 50},
				{"criterion": "Bloom Level", "value": "Apply", "min_percent": 50, "max_percent": 100},
			],
			"questions": [{"paper_set": s, "question_item": i} for s in sets for i in (items or self.items)],
		}).insert()  # fmt: skip
		for paper_set in sets:
			field = f"set_{paper_set.lower()}_file"
			doc.set(field, self.attach(doc, field))
		doc.save()
		for url in (doc.set_a_file, doc.set_b_file):
			if url:
				self.addCleanup(remove_file, url)
		return doc

	def paper(self, release_in_minutes=120, approve=True, items=None, sets=("A", "B"), session=None):
		doc = self.draft(release_in_minutes, items, sets, session)
		if approve:
			self.approve(doc)
		return frappe.get_doc(QP, doc.name)

	def approve(self, doc, approver=EC_USER):
		request = approvals.request_approval(QP, doc.name)
		frappe.set_user(approver)
		try:
			approvals.approve(request)
		finally:
			frappe.set_user("Administrator")

	def attach(self, doc, field, content=None, file_name=None):
		file = frappe.get_doc({"doctype": "File", "file_name": file_name or f"{doc.name}-{field}.pdf", "is_private": 1,
			"content": content or pdf_bytes(f"{doc.name} {field} {frappe.generate_hash()}"),
			"attached_to_doctype": QP, "attached_to_name": doc.name, "attached_to_field": field}).insert()  # fmt: skip
		self.addCleanup(remove_file, file.file_url)
		return file.file_url

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
	def test_attachment_is_encrypted_at_rest_with_the_dedicated_key(self):
		doc = self.draft()
		self.assertTrue(doc.set_a_file.endswith(".enc"), doc.set_a_file)
		sealed = frappe.get_doc("File", {"file_url": doc.set_a_file})
		self.assertEqual((sealed.is_private, sealed.attached_to_name, sealed.attached_to_field), (1, doc.name, "set_a_file"))
		with open(sealed.get_full_path(), "rb") as f:
			self.assertNotIn(b"%PDF", f.read())
		self.assertTrue(frappe.conf.get(question_paper_files.KEY_CONFIG))
		self.assertNotEqual(frappe.conf.get(question_paper_files.KEY_CONFIG), frappe.conf.get("encryption_key"))

	def test_the_plain_upload_is_removed_once_the_save_commits(self):
		doc = frappe.get_doc({"doctype": QP, "exam_session": self.session.name, "course": COURSE, "total_marks": 100}).insert()
		url = self.attach(doc, "set_a_file")
		doc.set_a_file = url
		doc.save()
		self.assertTrue(frappe.db.exists("File", {"file_url": url}))  # kept until the commit
		frappe.db.after_commit.run()
		self.assertFalse(frappe.db.exists("File", {"file_url": url}))
		self.assertFalse(os.path.exists(frappe.get_site_path(url.strip("/"))))
		self.addCleanup(remove_file, doc.set_a_file)

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
		self.assertFalse(self.logs(paper, result="Allowed", action="Download"))

	def test_inside_the_window_exam_confidential_downloads_a_watermarked_paper(self):
		paper = self.paper(release_in_minutes=10).name
		frappe.local.request_ip = "10.1.2.3"
		frappe.set_user(SM_EC_USER)
		self.assertTrue(frappe.has_permission(QP, "read", doc=frappe.get_doc(QP, paper)))
		text = pdf_text(question_papers.open_paper(paper, "A"))
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

	def test_the_download_endpoint_is_post_only_answers_403_and_is_never_cached(self):
		paper = self.paper(release_in_minutes=120).name
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[question_papers.download_paper], ["POST"])
		frappe.set_user(EC_USER)
		frappe.local.response = frappe._dict()
		question_papers.download_paper(paper, "A")
		self.assertEqual(frappe.local.response.http_status_code, 403)
		self.assertEqual(frappe.local.response_headers.get("Cache-Control"), "no-store")

	def test_the_download_endpoint_sends_the_pdf_inside_the_window(self):
		paper = self.paper(release_in_minutes=10).name
		frappe.set_user(EC_USER)
		frappe.local.response = frappe._dict()
		question_papers.download_paper(paper, "A")
		self.assertEqual((frappe.local.response.type, frappe.local.response.filename), ("download", f"{paper}-set-a.pdf"))
		self.assertIn(EC_USER, pdf_text(frappe.local.response.filecontent))
		self.assertEqual(frappe.local.response_headers.get("Cache-Control"), "no-store")

	def test_release_at_defaults_to_the_slot_start_of_the_schedule(self):
		doc = frappe.get_doc({"doctype": QP, "exam_session": self.session.name, "course": COURSE, "total_marks": 100}).insert()
		self.assertEqual(get_datetime(doc.release_at), get_datetime(f"{add_days(today(), 10)} 14:00:00"))
		self.assertEqual(doc.company, COLLEGE)

	def test_a_missing_slot_time_gives_no_release_time(self):
		frappe.db.set_single_value(SETTINGS, "afternoon_starts_at", None)
		self.assertIsNone(question_papers.slot_start(self.session.name, COURSE))

	def test_a_sealed_paper_cannot_be_changed(self):
		doc = self.paper(release_in_minutes=10)
		doc.total_marks = 90
		with self.assertRaises(frappe.ValidationError):
			doc.save()


class TestForeignSealedFile(QuestionPaperFixture):
	"""Critical 1: a paper must never serve another paper's sealed file."""

	def test_pointing_a_paper_at_another_papers_sealed_file_is_refused(self):
		other = self.paper(release_in_minutes=10, session=self.session_2)
		mine = self.draft(release_in_minutes=10)
		mine.set_a_file = other.set_a_file
		with self.assertRaises(frappe.ValidationError):
			mine.save()

	def test_a_paper_cannot_download_another_papers_file_even_if_its_field_is_forced(self):
		other = self.paper(release_in_minutes=10, session=self.session_2)
		mine = self.paper(release_in_minutes=10)
		frappe.db.set_value(QP, mine.name, "set_a_file", other.set_a_file, update_modified=False)
		frappe.set_user(EC_USER)
		with self.assertRaises(QPAccessDenied):
			question_papers.open_paper(mine.name, "A")
		frappe.set_user("Administrator")
		self.assertEqual(self.logs(mine.name, action="Download")[0].result, "Denied")

	def test_another_papers_ciphertext_copied_into_this_paper_is_refused(self):
		other = self.paper(release_in_minutes=10, session=self.session_2)
		mine = self.paper(release_in_minutes=10)
		with open(frappe.get_site_path(other.set_a_file.strip("/")), "rb") as f:
			stolen = f.read()
		bound = frappe.get_doc({"doctype": "File", "file_name": "copy.pdf.enc", "is_private": 1, "content": stolen,
			"attached_to_doctype": QP, "attached_to_name": mine.name, "attached_to_field": "set_a_file"}).insert()  # fmt: skip
		frappe.db.set_value(QP, mine.name, "set_a_file", bound.file_url, update_modified=False)
		frappe.set_user(EC_USER)
		with self.assertRaises(QPAccessDenied):
			question_papers.open_paper(mine.name, "A")

	def test_a_plain_file_named_enc_is_refused(self):
		doc = self.draft()
		doc.set_b_file = self.attach(doc, "set_b_file", content=pdf_bytes("plain"), file_name="fake.pdf.enc")
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_an_upload_matching_a_file_of_another_document_is_refused(self):
		content = pdf_bytes("shared upload")
		elsewhere = frappe.get_doc({"doctype": "File", "file_name": "elsewhere.pdf", "is_private": 1, "content": content,
			"attached_to_doctype": "Exam Session", "attached_to_name": self.session.name}).insert()  # fmt: skip
		self.addCleanup(remove_file, elsewhere.file_url)
		doc = frappe.get_doc({"doctype": QP, "exam_session": self.session.name, "course": COURSE, "total_marks": 100}).insert()
		doc.set_a_file = self.attach(doc, "set_a_file", content=content)
		with self.assertRaises(frappe.ValidationError):
			doc.save()


class TestSettingsAndVersions(QuestionPaperFixture):
	def test_editing_settings_after_approval_does_not_open_the_paper(self):
		"""Critical 2: the window is snapshotted at approval."""
		doc = self.paper(release_in_minutes=120)
		self.assertTrue(doc.download_opens_at and doc.download_closes_at)
		frappe.db.set_single_value(SETTINGS, {"download_lead_minutes": 600, "slot_minutes": 6000})
		self.assertFalse(self.can_read(EC_USER, doc.name))
		frappe.set_user(EC_USER)
		self.assertEqual(frappe.get_list(QP, {"name": doc.name}, pluck="name"), [])
		with self.assertRaises(QPAccessDenied):
			question_papers.open_paper(doc.name, "A")

	def test_only_a_system_manager_writes_the_settings(self):
		self.assertFalse(frappe.has_permission(SETTINGS, "write", user=EC_USER))
		self.assertTrue(frappe.has_permission(SETTINGS, "read", user=EC_USER))
		self.assertTrue(frappe.has_permission(SETTINGS, "write", user=SM_USER))

	def test_a_fresh_site_gets_the_default_settings(self):
		frappe.db.set_single_value(SETTINGS, {"download_lead_minutes": None, "slot_minutes": None,
			"forenoon_starts_at": None, "afternoon_starts_at": None})  # fmt: skip
		question_paper_setup.seed_settings()
		values = frappe.db.get_singles_dict(SETTINGS)
		self.assertEqual((int(values.download_lead_minutes), int(values.slot_minutes)), (30, 180))
		self.assertEqual((str(values.forenoon_starts_at), str(values.afternoon_starts_at)), ("10:00:00", "14:00:00"))

	def test_confidential_doctypes_keep_no_version_history(self):
		"""Critical 3: versions would copy questions and paper fields to a System Manager readable table."""
		doc = self.draft()
		doc.total_marks = 100
		doc.release_at = add_to_date(doc.release_at, minutes=5)
		doc.save()
		item = frappe.get_doc("Question Bank Item", self.items[0])
		item.question = "Changed"
		item.save()
		for doctype in ("Question Bank Item", QP, "QP Setter Nomination"):
			self.assertFalse(frappe.get_meta(doctype).track_changes, doctype)
			self.assertFalse(frappe.db.exists("Version", {"ref_doctype": doctype}), doctype)

	def test_existing_versions_are_removed(self):
		frappe.get_doc({"doctype": "Version", "ref_doctype": QP, "docname": "QP-LEAK", "data": "{}"}).db_insert()
		question_paper_setup.drop_confidential_versions()
		self.assertFalse(frappe.db.exists("Version", {"ref_doctype": QP}))


class TestAccessLog(QuestionPaperFixture):
	def test_a_denial_survives_the_rollback_of_its_request(self):
		paper = self.paper(release_in_minutes=120).name
		frappe.db.savepoint("qp_request")
		frappe.set_user(EC_USER)
		with self.assertRaises(QPAccessDenied):
			question_papers.open_paper(paper, "A")
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="qp_request")  # the request fails and rolls back
		self.assertFalse(self.logs(paper, action="Download"))
		with patch.object(frappe.db, "commit"):
			frappe.db.after_rollback.run()
		self.assertEqual([(r.user, r.result) for r in self.logs(paper, action="Download")], [(EC_USER, "Denied")])

	def test_a_list_denial_is_logged_once_a_minute(self):
		self.assertEqual(question_papers.permission_query(user=SM_USER), "1=0")
		self.assertEqual(question_papers.permission_query(user=SM_USER), "1=0")
		rows = frappe.get_all(LOG, {"user": SM_USER, "action": "List"}, ["result"])
		self.assertEqual([r.result for r in rows], ["Denied"])

	def test_the_log_is_append_only(self):
		paper = self.paper(release_in_minutes=10).name
		frappe.set_user(EC_USER)
		question_papers.open_paper(paper, "A")
		frappe.set_user("Administrator")
		log = frappe.get_doc(LOG, frappe.get_all(LOG, {"question_paper": paper}, pluck="name", limit=1)[0])
		log.result = "Denied"
		with self.assertRaises(frappe.ValidationError):
			log.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(LOG, log.name, ignore_permissions=True, force=True)

	def test_administrator_opening_a_sealed_paper_is_logged_and_sees_no_questions(self):
		paper = self.paper(release_in_minutes=120).name
		doc = frappe.get_doc(QP, paper)
		doc.run_method("onload")
		self.assertEqual(doc.questions, [])
		self.assertEqual([r.result for r in self.logs(paper, action="View", user="Administrator")], ["Allowed"])


class TestRoleRestriction(QuestionPaperFixture):
	def test_only_exam_confidential_reads_bank_items_nominations_and_logs(self):
		nomination = frappe.get_doc({"doctype": "QP Setter Nomination", "exam_session": self.session.name, "course": COURSE,
			"deadline": add_days(today(), 3), "setters": [{"employee": self.employee("QPT Setter")}]}).insert().name  # fmt: skip
		paper = self.paper(release_in_minutes=10).name
		frappe.set_user(EC_USER)
		question_papers.open_paper(paper, "A")
		frappe.set_user("Administrator")
		log = frappe.get_all(LOG, {"question_paper": paper}, pluck="name", limit=1)[0]
		for doctype, name in (("Question Bank Item", self.items[0]), ("QP Setter Nomination", nomination), (LOG, log)):
			self.assertTrue(frappe.has_permission(doctype, "read", doc=frappe.get_doc(doctype, name), user=EC_USER), doctype)
			for user in (SM_USER, FACULTY):
				self.assertFalse(frappe.has_permission(doctype, "read", doc=frappe.get_doc(doctype, name), user=user), (doctype, user))
				frappe.set_user(user)
				with self.assertRaises(frappe.PermissionError):
					frappe.get_list(doctype, pluck="name")
				frappe.set_user("Administrator")

	def test_a_draft_paper_is_open_to_exam_confidential_only(self):
		paper = self.paper(approve=False).name
		self.assertTrue(self.can_read(EC_USER, paper))
		self.assertFalse(self.can_read(SM_USER, paper))
		self.assertFalse(self.can_read(FACULTY, paper))

	def test_bank_items_of_a_sealed_paper_are_hidden_until_its_window_and_never_editable(self):
		self.paper(release_in_minutes=120)
		item = frappe.get_doc("Question Bank Item", self.items[0])
		self.assertFalse(frappe.has_permission("Question Bank Item", "read", doc=item, user=EC_USER))
		frappe.set_user(EC_USER)
		self.assertNotIn(item.name, frappe.get_list("Question Bank Item", pluck="name"))
		frappe.set_user("Administrator")
		frappe.db.set_value(QP, {"exam_session": self.session.name}, "download_opens_at", add_to_date(now_datetime(), minutes=-1))
		self.assertTrue(frappe.has_permission("Question Bank Item", "read", doc=item, user=EC_USER))
		self.assertFalse(frappe.has_permission("Question Bank Item", "write", doc=item, user=EC_USER))

	def test_confidential_documents_cannot_be_shared(self):
		paper = self.paper(approve=False).name
		for doctype, name in ((QP, paper), ("Question Bank Item", self.items[0])):
			with self.assertRaises(frappe.ValidationError):
				frappe.share.add_docshare(doctype, name, SM_USER, read=1, flags={"ignore_share_permission": True})

	def test_the_paper_file_record_is_not_readable(self):
		doc = self.paper(release_in_minutes=10)
		sealed = frappe.get_doc("File", {"file_url": doc.set_a_file})
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


class TestApproval(QuestionPaperFixture):
	def test_the_setter_cannot_approve_their_own_paper(self):
		frappe.set_user(EC_USER)
		doc = self.draft()
		request = approvals.request_approval(QP, doc.name)
		with self.assertRaises(frappe.PermissionError):
			approvals.approve(request)
		frappe.set_user(SM_EC_USER)
		approvals.approve(request)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(QP, doc.name, ["docstatus", "moderation_status"]), (1, "Approved"))

	def test_a_paper_is_not_sealed_without_the_approval_engine(self):
		doc = self.draft()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		frappe.db.delete("Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.policies()]})
		frappe.db.delete("Approval Policy", {"document_type": QP})
		with self.assertRaises(frappe.ValidationError):
			approvals.request_approval(QP, doc.name)  # no policy: refused, never submitted directly
		self.assertEqual(frappe.db.get_value(QP, doc.name, "docstatus"), 0)

	def test_a_request_moves_the_paper_under_moderation(self):
		doc = self.draft()
		approvals.request_approval(QP, doc.name)
		self.assertEqual(frappe.db.get_value(QP, doc.name, "moderation_status"), "Under Moderation")

	def test_one_approved_paper_per_session_and_course(self):
		self.paper()
		second = self.draft()
		with self.assertRaises(frappe.ValidationError):
			self.approve(second)

	def test_a_paper_off_its_blueprint_cannot_be_sent_for_approval(self):
		lopsided = [self.bank_item("CO1", "Apply", 50), self.bank_item("CO1", "Remember", 50)]
		doc = self.draft(items=lopsided)
		self.assertIn("CO2 is not covered", doc.blueprint_issues)
		with self.assertRaises(frappe.ValidationError):
			approvals.request_approval(QP, doc.name)

	def test_a_paper_on_its_blueprint_is_approved_with_its_window_snapshotted(self):
		doc = self.paper(release_in_minutes=120)
		self.assertEqual((doc.docstatus, doc.moderation_status, doc.blueprint_issues or ""), (1, "Approved", ""))
		self.assertEqual(get_datetime(doc.download_opens_at), add_to_date(get_datetime(doc.release_at), minutes=-30))
		self.assertEqual(get_datetime(doc.download_closes_at), add_to_date(get_datetime(doc.release_at), minutes=180))

	def test_a_withdrawn_paper_is_never_downloadable(self):
		paper = self.paper(release_in_minutes=10).name
		frappe.set_user(EC_USER)
		question_papers.withdraw(paper)
		with self.assertRaises(QPAccessDenied):
			question_papers.open_paper(paper, "A")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(QP, paper, ["docstatus", "moderation_status"]), (2, "Withdrawn"))

	def test_a_withdrawn_draft_stays_withdrawn(self):
		doc = self.draft()
		frappe.set_user(EC_USER)
		question_papers.withdraw(doc.name)
		frappe.set_user("Administrator")
		doc = frappe.get_doc(QP, doc.name)
		self.assertEqual(doc.moderation_status, "Withdrawn")
		doc.total_marks = 90
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		with self.assertRaises(frappe.ValidationError):
			approvals.request_approval(QP, doc.name)

	def test_only_exam_confidential_withdraws(self):
		paper = self.paper(release_in_minutes=120).name
		frappe.set_user(SM_USER)
		with self.assertRaises(frappe.PermissionError):
			question_papers.withdraw(paper)

	def test_the_approval_policy_is_seeded(self):
		frappe.db.delete("Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.policies()]})
		frappe.db.delete("Approval Policy", {"document_type": QP})
		question_paper_setup.seed_approval_policy()
		(policy,) = frappe.get_all("Approval Policy", {"document_type": QP}, pluck="name")
		(level,) = frappe.get_doc("Approval Policy", policy).levels
		self.assertEqual((level.approver_type, level.approver, level.limit_to_company), ("Role", EXAM_CONFIDENTIAL, 1))


class TestBlueprintCheck(QuestionPaperFixture):
	def test_questions_must_belong_to_the_course(self):
		other = "QPT Other Course"
		if not frappe.db.exists("Course", other):
			frappe.get_doc({"doctype": "Course", "course_name": other, "oc_company": COLLEGE}).insert()
		item = frappe.get_doc({"doctype": "Question Bank Item", "company": COLLEGE, "course": other, "course_outcome": "CO1",
			"bloom_level": "Apply", "marks": 25, "question": "Other"}).insert().name  # fmt: skip
		with self.assertRaises(frappe.ValidationError):
			self.draft(items=self.items[:3] + [item])

	def test_a_disabled_or_repeated_question_is_refused(self):
		disabled = self.bank_item("CO2", "Apply", disabled=1)
		with self.assertRaises(frappe.ValidationError):
			self.draft(items=self.items[:3] + [disabled])
		with self.assertRaises(frappe.ValidationError):
			self.draft(items=self.items + [self.items[0]])

	def test_a_set_with_a_file_needs_questions(self):
		doc = self.draft(sets=("A",))
		doc.set_b_file = self.attach(doc, "set_b_file")
		doc.save()
		self.addCleanup(remove_file, doc.set_b_file)
		self.assertIn("Set B has a paper file but no questions.", doc.blueprint_issues)


class TestPrintLog(QuestionPaperFixture):
	def test_print_log_counts_copies_per_hall_and_logs_every_attempt(self):
		early = self.paper(release_in_minutes=120, session=self.session_2).name
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

	def test_paper_and_session_filters_combine(self):
		paper = self.paper(release_in_minutes=10).name
		frappe.set_user(EC_USER)
		question_papers.print_copies(paper, "A", self.rooms[0], 30)
		_columns, mismatch = print_log({"company": COLLEGE, "exam_session": self.session_2.name, "question_paper": paper})
		_columns, match = print_log({"company": COLLEGE, "exam_session": self.session.name, "question_paper": paper})
		frappe.set_user("Administrator")
		self.assertEqual((mismatch, [r["copies"] for r in match]), ([], [30]))

	def test_copies_must_be_positive(self):
		paper = self.paper(release_in_minutes=10).name
		frappe.set_user(EC_USER)
		with self.assertRaises(frappe.ValidationError):
			question_papers.print_copies(paper, "A", self.rooms[0], 0)

	def test_the_hall_must_be_an_exam_hall_of_the_papers_college(self):
		paper = self.paper(release_in_minutes=10).name
		classroom = self.room("QPT Classroom", room_type="Classroom")
		elsewhere = self.room("QPT Other Hall", company=OTHER_COLLEGE)
		frappe.set_user(EC_USER)
		for room in (classroom, elsewhere):
			with self.assertRaises(frappe.ValidationError):
				question_papers.print_copies(paper, "A", room, 5)
