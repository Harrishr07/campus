"""M06-07, M05-03 integration tests (P2-T22): the graduate record from published results, the verifiable prints
(semester grade sheet, consolidated grade sheet, provisional certificate, degree certificate or degree data sheet,
transcript) through Certificate Requests, the degree_awarding_body switch, the Convocation List export and the
Progression Run.

Fixture: R2022 and R2026 students of one college with hand-made Student Results (3-credit core courses GRD C1-C4,
9-credit Honours courses GRD H1/H2, a 3-credit additional course GRD A1) in published sessions S1 and S2 (final
year) and an unreleased session (publish_at ahead). CGPA values are hand-computed in the comments.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from campus.campus_platform import bulk
from campus.campus_platform.approvals import approve, request_approval
from campus.campus_platform.verification import verify
from campus.examinations import api, convocation, exam_certificates, graduation, progression
from campus.examinations.seed import seed_regulation
from campus.student_services import lifecycle
from campus.tests.approval_fixtures import level
from campus.tests.factories import make_company, make_user
from campus.tests.test_regulation import enroll, make_program, make_regulation, make_student, make_year, year_name
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR, PROGRAM, UNIVERSITY = "Grad Test College", "GRDC", "Grad Test BE", "Grad Test University"
APPROVER, POLICY = "grd-coe-approver@example.com", "GRD Certificate Policy"
NON_COE_USER = "grd-academics@example.com"
DISTINCTION, FIRST, SECOND = "First Class with Distinction", "First Class", "Second Class"
CORE = ("GRD C1", "GRD C2", "GRD C3", "GRD C4")
TRANSCRIPT, CONSOLIDATED, PROVISIONAL, DEGREE, DATA_SHEET = (
	"Transcript", "Consolidated Grade Sheet", "Provisional Certificate", "Degree Certificate", "Degree Data Sheet",
)  # fmt: skip
TERMS = {
	"S1": ("Grd Sem 1", "2022-06-01", "2022-11-30"),
	"S2": ("Grd Sem 2", "2022-12-01", "2023-03-31"),
	"LATE": ("Grd Late", "2023-04-01", "2023-05-31"),
}


def make_term(name, start, end):
	found = frappe.db.get_value("Academic Term", {"academic_year": year_name("2022"), "term_name": name})
	return found or frappe.get_doc(
		{"doctype": "Academic Term", "academic_year": year_name("2022"), "term_name": name, "term_start_date": start,
		"term_end_date": end}
	).insert().name  # fmt: skip


def make_session(term, final_year=0, released=True):
	session = frappe.get_doc({"doctype": "Exam Session", "company": COLLEGE, "academic_term": term, "status": "Marks Entry"}).insert()
	publish_at = add_days(now_datetime(), -1 if released else 3)
	frappe.db.set_value("Exam Session", session.name, {"status": "Published", "publish_at": publish_at, "is_final_year": final_year})
	return session.name


def pass_(course, grade_point, credits=3):
	return (course, grade_point, "Pass", credits)


def fail(course, credits=3):
	return (course, 0, "Fail", credits)


class GraduationFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, ABBR)
		for year in ("2022", "2026"):
			make_year(year)
		make_program(PROGRAM, COLLEGE)
		cls.regs = {}
		for code, year in (("R2022", "2022"), ("R2026", "2026")):
			cls.regs[code] = make_regulation(f"{code}-GRD", COLLEGE, [PROGRAM], year).name
			seed_regulation(cls.regs[code], code)
		frappe.get_doc(
			{"doctype": "Institution Profile", "company": COLLEGE, "institution_status": "Autonomous",
			"affiliating_university": UNIVERSITY, "degree_awarding_body": "University", "provisional_certificate_issuer": "College"}
		).insert()  # fmt: skip
		exam_certificates.seed_certificate_types()
		make_user(APPROVER, [COLLEGE])
		for course in (*CORE, "GRD H1", "GRD H2", "GRD A1"):
			if not frappe.db.exists("Course", course):
				frappe.get_doc({"doctype": "Course", "course_name": course, "oc_company": COLLEGE}).insert()
		cls.terms = {key: make_term(*values) for key, values in TERMS.items()}
		cls.s1 = make_session(cls.terms["S1"])
		cls.s2 = make_session(cls.terms["S2"], final_year=1)
		cls.late = make_session(cls.terms["LATE"], final_year=1, released=False)
		cls.students = {}
		histories = {
			# (9 + 9 + 8 + 9) x 3 / 12 = 8.75, all at the first appearance
			"dist": ("2022", {cls.s1: [pass_("GRD C1", 9), pass_("GRD C2", 9)], cls.s2: [pass_("GRD C3", 8), pass_("GRD C4", 9)]}),
			# GRD C3 failed in S1, cleared in S2: 8.75 but not at the first appearance
			"cleared": ("2022", {cls.s1: [pass_("GRD C1", 9), pass_("GRD C2", 9), fail("GRD C3")],
				cls.s2: [pass_("GRD C3", 8), pass_("GRD C4", 9)]}),  # fmt: skip
			"arrear": ("2022", {cls.s1: [pass_("GRD C1", 9), pass_("GRD C2", 9)], cls.s2: [pass_("GRD C3", 8), fail("GRD C4")]}),
			# with H1 + H2 (18 Honours credits at 10) and A1 at 10: (105 + 180 + 30) / 33 = 9.55
			"honours": ("2022", {cls.s1: [pass_("GRD C1", 9), pass_("GRD C2", 9), pass_("GRD H1", 10, 9)],
				cls.s2: [pass_("GRD C3", 8), pass_("GRD C4", 9), pass_("GRD H2", 10, 9), pass_("GRD A1", 10)]}),  # fmt: skip
			# 9 Honours credits only: no Honours, H1 listed but not in the CGPA (8.75)
			"partial": ("2022", {cls.s1: [pass_("GRD C1", 9), pass_("GRD C2", 9), pass_("GRD H1", 10, 9)],
				cls.s2: [pass_("GRD C3", 8), pass_("GRD C4", 9)]}),  # fmt: skip
			# R2026: (6 + 6 + 7 + 6) x 3 / 12 = 6.25
			"weak26": ("2026", {cls.s1: [pass_("GRD C1", 6), pass_("GRD C2", 6)], cls.s2: [pass_("GRD C3", 7), pass_("GRD C4", 6)]}),
			# its final year is in the unreleased session
			"unreleased": ("2022", {cls.s1: [pass_("GRD C1", 9), pass_("GRD C2", 9)], cls.late: [pass_("GRD C3", 8), pass_("GRD C4", 9)]}),
		}
		for key, (batch, sessions) in histories.items():
			student = make_student(f"Grd{key.title()}", COLLEGE, batch)
			enroll(student, PROGRAM, "2022", submit=True)
			frappe.db.set_value("Student", student.name, {"oc_current_semester": 2, "oc_register_no": f"GRD{key.upper()}"})
			cls.students[key] = student.name
			for session, rows in sessions.items():
				cls.make_result(student.name, session, rows)
		assert frappe.db.get_value("Student", cls.students["weak26"], "oc_regulation") == cls.regs["R2026"]
		for key, courses in (("honours", ("GRD H1", "GRD H2")), ("partial", ("GRD H1",))):
			cls.register_honours(cls.students[key], courses)
		cls.register_additional(cls.students["honours"], "GRD A1")

	@classmethod
	def make_result(cls, student, session, rows):
		term = frappe.db.get_value("Exam Session", session, "academic_term")
		frappe.get_doc(
			{
				"doctype": "Student Result", "student": student, "student_name": frappe.db.get_value("Student", student, "student_name"),
				"exam_session": session, "company": COLLEGE, "academic_term": term, "program": PROGRAM,
				"regulation": frappe.db.get_value("Student", student, "oc_regulation"), "version": 1, "is_latest": 1,
				"result": "Pass" if all(r[2] == "Pass" for r in rows) else "Reappear",
				"courses": [
					{"course": c, "grade_point": gp, "grade": "O" if gp == 10 else "X" if gp else "U", "result": result,
					"credits": credits, "in_gpa": 1, "kind": "Current", "total": gp * 10}
					for c, gp, result, credits in rows
				],
			}
		).insert(ignore_permissions=True)  # fmt: skip

	@classmethod
	def register_honours(cls, student, courses):
		cls.register(student, courses, "Honours")

	@classmethod
	def register_additional(cls, student, course):
		cls.register(student, (course,), "Additional")

	@classmethod
	def register(cls, student, courses, registration_type):
		"""A submitted Course Registration listing `courses` as `registration_type` (written directly: the
		curriculum checks of a real registration are not under test here)."""
		doc = frappe.get_doc(
			{"doctype": "Course Registration", "student": student, "academic_term": cls.terms["S1"], "semester": 1,
			"company": COLLEGE, "docstatus": 1,
			"items": [{"course": c, "registration_type": registration_type, "credits": 9} for c in courses]}
		)  # fmt: skip
		doc.name = frappe.generate_hash(length=12)
		doc.db_insert()
		for row in doc.items:
			row.parent, row.parenttype, row.parentfield = doc.name, "Course Registration", "items"
			row.db_insert()

	def setUp(self):
		frappe.db.savepoint("graduation_test")
		self.addCleanup(frappe.db.rollback, save_point="graduation_test")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		frappe.get_doc(
			{"doctype": "Approval Policy", "policy_name": POLICY, "document_type": "Certificate Request",
			"condition": "doc.needs_approval", "levels": [level("User", APPROVER, title="COE")]}
		).insert()  # fmt: skip

	def awarding(self, body):
		frappe.db.set_value("Institution Profile", COLLEGE, "degree_awarding_body", body)

	def request(self, key, certificate_type, submit=True):
		doc = frappe.get_doc(
			{"doctype": "Certificate Request", "student": self.students[key], "certificate_type": certificate_type, "purpose": "Higher studies"}
		).insert()
		if submit and doc.needs_approval:
			return self.approve(doc)
		if submit:
			doc.submit()
		return doc

	def approve(self, doc):
		"""The graduate documents need approval (fix round 1, I-2): approving submits (issues) the request."""
		request = request_approval("Certificate Request", doc.name)
		frappe.set_user(APPROVER)
		approve(request, None)
		frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual(doc.docstatus, 1)
		return doc

	def printed(self, doc):
		print_format = frappe.db.get_value("Certificate Type", doc.certificate_type, "print_format")
		return frappe.get_print("Certificate Request", doc.name, print_format)


class TestGraduateRecord(GraduationFixture):
	def test_ac1_classes_from_published_results(self):
		dist = graduation.graduate_record(self.students["dist"])
		self.assertEqual((dist.completed, dist.cgpa, dist.percentage, dist.classification), (True, 8.75, 87.5, DISTINCTION))
		self.assertEqual(graduation.graduate_record(self.students["cleared"]).classification, FIRST)
		weak = graduation.graduate_record(self.students["weak26"])
		self.assertEqual((weak.regulation, weak.cgpa, weak.classification), (self.regs["R2026"], 6.25, SECOND))

	def test_an_outstanding_arrear_means_not_completed(self):
		record = graduation.graduate_record(self.students["arrear"])
		self.assertEqual((record.completed, record.arrears, record.classification), (False, ["GRD C4"], None))

	def test_only_released_results_count(self):
		record = graduation.graduate_record(self.students["unreleased"])
		self.assertEqual([s.exam_session for s in record.semesters], [self.s1])
		self.assertFalse(record.completed)
		frappe.db.set_value("Exam Session", self.s1, "publish_at", add_days(now_datetime(), 1))
		self.assertEqual(graduation.graduate_record(self.students["dist"]).semesters[0].exam_session, self.s2)

	def test_entry_type_and_break_years_reach_the_classification(self):
		frappe.db.set_value("Student", self.students["dist"], "oc_lateral_entry", 1)
		with (
			patch.object(graduation, "break_years", return_value=1),
			patch.object(graduation.graduation_rules, "classification", wraps=graduation.graduation_rules.classification) as spy,
		):
			graduation.graduate_record(self.students["dist"])
		_record, _classes, _years, break_years, entry_type = spy.call_args.args
		self.assertEqual((break_years, entry_type), (1, "Lateral"))


	def test_the_patch_gives_existing_rules_their_honours_credits(self):
		from campus.examinations.seed import fill_honours_credits

		frappe.db.set_value("Classification Rule", self.regs["R2022"], "honours_credits", 0)
		frappe.db.set_value("Classification Rule", self.regs["R2026"], "honours_credits", 12)
		fill_honours_credits()  # DML only
		self.assertEqual(frappe.db.get_value("Classification Rule", self.regs["R2022"], "honours_credits"), 18)
		self.assertEqual(frappe.db.get_value("Classification Rule", self.regs["R2026"], "honours_credits"), 12)  # set: kept


class TestPrints(GraduationFixture):
	def assert_verifiable(self, doc, html):
		doc.reload()
		self.assertTrue(doc.verification_code)
		self.assertEqual(verify(doc.verification_code).status, "Valid")
		self.assertIn("oc-qr-block", html)
		self.assertIn(doc.verification_code, html)

	def test_each_print_carries_a_verifiable_qr(self):
		for certificate_type, expected in (
			(TRANSCRIPT, "GRD C3"), (CONSOLIDATED, "87.50"), (PROVISIONAL, DISTINCTION), (DATA_SHEET, UNIVERSITY),
		):  # fmt: skip
			doc = self.request("dist", certificate_type)
			html = self.printed(doc)
			self.assert_verifiable(doc, html)
			self.assertIn(expected, html, certificate_type)
		self.awarding("College")
		doc = self.request("dist", DEGREE)
		html = self.printed(doc)
		self.assert_verifiable(doc, html)
		self.assertIn(DISTINCTION, html)

	def test_the_semester_grade_sheet_carries_a_verifiable_qr(self):
		result = frappe.db.get_value("Student Result", {"student": self.students["dist"], "exam_session": self.s2})
		code = frappe.db.get_value("Verifiable Document", api.issue_grade_sheet(result), "code")
		self.assertEqual(verify(code).status, "Valid")
		self.assertIn(code, frappe.get_print("Student Result", result, "Grade Sheet"))

	def test_ac2_university_awarding_body_hides_the_degree_certificate(self):
		self.assertNotIn(DEGREE, exam_certificates.available_prints(COLLEGE))
		self.assertIn(DATA_SHEET, exam_certificates.available_prints(COLLEGE))
		with self.assertRaisesRegex(frappe.ValidationError, "degree certificate"):
			self.request("dist", DEGREE, submit=False)
		self.awarding("College")
		self.assertIn(DEGREE, exam_certificates.available_prints(COLLEGE))
		with self.assertRaises(frappe.ValidationError):
			self.request("dist", DATA_SHEET, submit=False)

	def test_ac2_an_issued_degree_certificate_stays_printable_after_the_switch_a_draft_does_not(self):
		self.awarding("College")
		issued = self.request("dist", DEGREE)
		draft = self.request("cleared", DEGREE, submit=False)
		self.awarding("University")
		self.assertIn(DISTINCTION, self.printed(issued))  # rendered from its snapshot
		with self.assertRaises(frappe.ValidationError):
			self.printed(draft)

	def test_ac3_consolidated_sheet_lists_honours_courses_per_the_regulation(self):
		html = self.printed(self.request("honours", CONSOLIDATED))
		for text in ("GRD H1", "GRD H2", "GRD A1", "9.55", "95.50", "Honours"):
			self.assertIn(text, html)
		self.assertNotIn("Not counted in CGPA", html)
		html = self.printed(self.request("partial", CONSOLIDATED))
		for text in ("GRD H1", "Not counted in CGPA", "8.75"):
			self.assertIn(text, html)

	def test_graduate_prints_need_a_completed_programme_the_transcript_only_published_results(self):
		for certificate_type in (CONSOLIDATED, PROVISIONAL, DATA_SHEET):
			with self.assertRaisesRegex(frappe.ValidationError, "completed"):
				self.request("arrear", certificate_type, submit=False)
		self.assertIn("GRD C4", self.printed(self.request("arrear", TRANSCRIPT)))
		html = self.printed(self.request("unreleased", TRANSCRIPT))
		self.assertIn("GRD C1", html)
		self.assertNotIn("GRD C3", html)  # its session is not released yet
		frappe.db.set_value("Exam Session", self.s1, "publish_at", add_days(now_datetime(), 1))
		with self.assertRaisesRegex(frappe.ValidationError, "published"):
			self.request("unreleased", TRANSCRIPT, submit=False)

	def test_the_provisional_certificate_names_the_issuer_of_the_setting(self):
		self.assertIn(COLLEGE, self.printed(self.request("dist", PROVISIONAL)))
		frappe.db.set_value("Institution Profile", COLLEGE, "provisional_certificate_issuer", "University")
		self.assertIn(UNIVERSITY, self.printed(self.request("cleared", PROVISIONAL)))

	def test_output_is_escaped(self):
		frappe.db.set_value("Student", self.students["dist"], "student_name", "Grd <i>Tag</i>")
		html = self.printed(self.request("dist", TRANSCRIPT))
		self.assertIn("Grd &lt;i&gt;Tag&lt;/i&gt;", html)
		self.assertNotIn("<i>Tag", html)
		result = frappe.db.get_value("Student Result", {"student": self.students["dist"], "exam_session": self.s2})
		frappe.db.set_value("Student Result", result, "student_name", "Grd <i>Tag</i>")
		self.assertNotIn("<i>Tag", frappe.get_print("Student Result", result, "Grade Sheet"))


class TestTranscriptRequest(GraduationFixture):
	def test_a_student_requests_a_transcript_in_the_portal(self):
		from campus.student_services import portal

		user = "grd-student@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "Grd", "send_welcome_email": 0, "roles": [{"role": "Student"}]}).insert()
		frappe.db.set_value("Student", self.students["dist"], "user", user)
		frappe.db.set_value("Certificate Type", TRANSCRIPT, "fee_amount", 250)
		frappe.set_user(user)
		row = portal.request_certificate(TRANSCRIPT, "Higher studies")
		# no approval on the seeded type: the portal issues it at once (P1-T20) and the fee is invoiced afterwards
		self.assertEqual((row["certificate_type"], row["status"], row["fee_amount"]), (TRANSCRIPT, "Issued", 250))
		self.assertEqual(verify(row["verification_code"]).status, "Valid")
		self.assertEqual(frappe.db.get_value("Certificate Request", row["name"], "student"), self.students["dist"])
		with self.assertRaises(frappe.PermissionError):
			portal.request_certificate(TRANSCRIPT, "Higher studies", student=self.students["cleared"])


class TestConvocation(GraduationFixture):
	def make_list(self):
		doc = frappe.get_doc({"doctype": "Convocation List", "company": COLLEGE, "program": PROGRAM}).insert()
		convocation.fill_graduates(doc.name)
		return frappe.get_doc("Convocation List", doc.name)

	def test_lists_the_eligible_graduates_only(self):
		doc = self.make_list()
		expected = {self.students[k] for k in ("dist", "cleared", "honours", "partial", "weak26")}
		self.assertEqual({g.student for g in doc.graduates}, expected)
		row = next(g for g in doc.graduates if g.student == self.students["honours"])
		self.assertEqual((row.cgpa, row.percentage, row.classification, row.variant), (9.55, 95.5, DISTINCTION, "Honours"))

	def test_ac2_the_export_is_available_with_the_mapped_columns(self):
		self.awarding("University")
		doc = self.make_list()
		rows = convocation.export_rows(doc.name)
		self.assertEqual(rows[0], [heading for heading, _source in convocation.DEFAULT_COLUMNS])
		self.assertEqual(len(rows), 6)
		doc.columns = []
		doc.append("columns", {"heading": "REGNO", "source": "Register Number"})
		doc.append("columns", {"heading": "CLASS", "source": "Classification"})
		doc.save()
		rows = convocation.export_rows(doc.name)
		self.assertEqual(rows[0], ["REGNO", "CLASS"])
		self.assertIn(["GRDDIST", DISTINCTION], rows)

	def test_the_format_is_labelled_a_placeholder(self):
		self.assertIn("placeholder", frappe.get_meta("Convocation List").get_field("columns").description.lower())

	def test_export_cells_cannot_carry_formulas(self):
		frappe.db.set_value("Student", self.students["dist"], "student_name", "=HYPERLINK(1)")
		rows = convocation.export_rows(self.make_list().name)
		self.assertIn("'=HYPERLINK(1)", [cell for row in rows for cell in row])

	def lifecycle(self, key):
		return [
			(row.from_status, row.to_status, row.source_doctype, row.effective_date)
			for row in frappe.get_all(
				"Lifecycle Transition", {"student": self.students[key], "kind": "Transition"},
				["from_status", "to_status", "source_doctype", "effective_date"], order_by="creation asc, name asc",
			)
		]  # fmt: skip

	def test_listing_records_study_completed_and_award_eligible(self):
		doc = self.make_list()
		convocation.fill_graduates(doc.name)  # a refill changes nothing twice
		self.assertEqual(
			self.lifecycle("dist"),
			[("Active", "Study Completed", "Convocation List", getdate(today())), ("Study Completed", "Award Eligible", "Convocation List", getdate(today()))],
		)
		self.assertEqual(frappe.db.get_value("Student", self.students["arrear"], "oc_academic_status"), "Active")  # not listed

	def test_graduates_are_recorded_on_the_convocation_date(self):
		doc = self.make_list()
		with self.assertRaisesRegex(frappe.ValidationError, "convocation date"):
			convocation.graduate(doc.name)
		doc.db_set("convocation_date", add_days(today(), 1))
		with self.assertRaisesRegex(frappe.ValidationError, "convocation date"):
			convocation.graduate(doc.name)
		doc.db_set("convocation_date", add_days(today(), 0))
		self.assertEqual(convocation.graduate(doc.name), {"graduated": 5, "refused": []})
		self.assertEqual(frappe.db.get_value("Student", self.students["dist"], "oc_academic_status"), "Graduated")
		self.assertEqual(self.lifecycle("dist")[-1], ("Award Eligible", "Graduated", "Convocation List", getdate(today())))
		self.assertEqual(convocation.graduate(doc.name), {"graduated": 0, "refused": []})  # once

	def test_a_list_filled_after_its_convocation_is_dated_from_it_and_graduates(self):
		held = getdate(add_days(today(), -20))
		doc = frappe.get_doc({"doctype": "Convocation List", "company": COLLEGE, "program": PROGRAM, "convocation_date": held}).insert()
		convocation.fill_graduates(doc.name)
		self.assertEqual([row[3] for row in self.lifecycle("dist")], [held, held])
		self.assertEqual(convocation.graduate(doc.name)["graduated"], 5)
		self.assertEqual(self.lifecycle("dist")[-1], ("Award Eligible", "Graduated", "Convocation List", held))

	def test_a_legacy_list_with_a_past_convocation_graduates_its_migrated_students(self):
		held = getdate(add_days(today(), -20))
		doc = self.make_list()
		doc.db_set("convocation_date", held)
		student = self.students["dist"]
		frappe.db.delete("Lifecycle Transition", {"student": student})  # as recorded before L-01
		frappe.db.set_value("Student", student, "oc_academic_status", "Active")
		self.assertEqual(lifecycle.migrate_student(student), "Award Eligible")
		migrated = frappe.get_last_doc("Lifecycle Transition", {"student": student})
		self.assertEqual((migrated.kind, migrated.effective_date, migrated.source_name), ("Migrated", held, doc.name))
		result = convocation.graduate(doc.name)
		self.assertNotIn(student, [row["student"] for row in result["refused"]])
		self.assertEqual(frappe.db.get_value("Student", student, "oc_academic_status"), "Graduated")

	def test_a_refused_graduate_does_not_stop_the_others(self):
		doc = self.make_list()  # dated today
		doc.db_set("convocation_date", add_days(today(), -1))
		others = [self.students[k] for k in ("cleared", "honours", "partial", "weak26")]
		frappe.db.set_value("Lifecycle Transition", {"student": ["in", others], "source_name": doc.name}, "effective_date", add_days(today(), -2))
		result = convocation.graduate(doc.name)
		self.assertEqual(result["graduated"], 4)
		self.assertEqual([row["student"] for row in result["refused"]], [self.students["dist"]])
		self.assertIn("before the last status change", result["refused"][0]["reason"])
		self.assertEqual(frappe.db.get_value("Student", self.students["dist"], "oc_academic_status"), "Award Eligible")

	def test_a_refill_that_drops_a_graduate_undoes_award_eligible(self):
		doc = self.make_list()
		frappe.get_doc({"doctype": "Curriculum Rule", "regulation": self.regs["R2022"], "min_total_credits": 15, "max_total_credits": 200}).insert()
		convocation.fill_graduates(doc.name)
		self.assertNotIn(self.students["dist"], {g.student for g in frappe.get_doc("Convocation List", doc.name).graduates})
		self.assertEqual(frappe.db.get_value("Student", self.students["dist"], "oc_academic_status"), "Active")
		kinds = frappe.get_all(
			"Lifecycle Transition", {"student": self.students["dist"], "source_name": doc.name}, ["kind", "to_status"], order_by="creation asc, name asc"
		)
		self.assertEqual(
			[(k.kind, k.to_status) for k in kinds],
			[("Transition", "Study Completed"), ("Transition", "Award Eligible"), ("Reversal", "Study Completed"), ("Reversal", "Active")],
		)

	def test_only_the_coe_records_graduates(self):
		doc = self.make_list()
		doc.db_set("convocation_date", today())
		make_user(NON_COE_USER, [COLLEGE])  # Academics User of the college, write access but not the COE
		frappe.set_user(NON_COE_USER)
		with self.assertRaises(frappe.PermissionError):
			api.graduate_convocation_list(doc.name)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.graduate_convocation_list(doc.name)

	def test_a_graduate_is_listed_once(self):
		self.make_list()
		self.assertEqual(self.make_list().graduates, [])

	def test_the_download_is_a_csv_needing_read_access(self):
		doc = self.make_list()
		api.download_convocation_list(doc.name)
		self.assertEqual(frappe.response["type"], "csv")
		self.assertIn("GRDDIST", frappe.response["result"])
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.download_convocation_list(doc.name)


class TestProgressionRun(GraduationFixture):
	def setUp(self):
		super().setUp()
		frappe.get_doc({"doctype": "Progression Rule", "regulation": self.regs["R2022"], "max_arrears": 0, "probation_below_cgpa": 6}).insert()
		frappe.get_doc({"doctype": "Progression Rule", "regulation": self.regs["R2026"], "max_arrears": 2, "probation_below_cgpa": 6.5}).insert()

	def start(self):
		doc = frappe.get_doc({"doctype": "Progression Run", "company": COLLEGE, "academic_term": self.terms["S2"], "program": PROGRAM})
		doc.insert()
		with patch.object(bulk, "enqueue_run") as enqueue:
			doc.submit()
		self.assertEqual(enqueue.call_count, 1)
		doc.reload()
		return doc

	def process(self, doc):
		run = frappe.get_doc("Bulk Run", doc.bulk_run)
		for student in frappe.parse_json(run.items):
			progression.progress_student(student, run)
		doc.reload()
		return {row.student: row for row in doc.students}

	def test_promote_detain_and_probation_by_the_progression_rule(self):
		doc = self.start()
		self.assertEqual(set(frappe.parse_json(frappe.db.get_value("Bulk Run", doc.bulk_run, "items"))), set(self.students.values()))
		rows = self.process(doc)
		self.assertEqual(rows[self.students["dist"]].outcome, "Promote")
		self.assertEqual(rows[self.students["arrear"]].outcome, "Detain")
		self.assertEqual(rows[self.students["weak26"]].outcome, "Probation")  # 6.25 < 6.5
		student = lambda key: frappe.db.get_value("Student", self.students[key], ["oc_current_semester", "oc_detained", "oc_academic_status"])  # noqa: E731
		self.assertEqual(student("dist"), (3, 0, "Active"))
		self.assertEqual(student("arrear"), (2, 1, "Active"))  # detention is not a lifecycle status (L-01)
		self.assertEqual(student("weak26"), (3, 0, "Active"))

	def test_a_rerun_is_idempotent(self):
		doc = self.start()
		self.process(doc)
		rows = self.process(doc)
		self.assertEqual(len(rows), len(self.students))
		self.assertEqual(len(doc.students), len(self.students))
		self.assertEqual(frappe.db.get_value("Student", self.students["dist"], "oc_current_semester"), 3)

	def test_one_run_per_term_and_program(self):
		self.start()
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({"doctype": "Progression Run", "company": COLLEGE, "academic_term": self.terms["S2"], "program": PROGRAM}).insert()

	def test_the_rule_is_locked_on_an_effective_regulation(self):
		rule = frappe.get_doc("Progression Rule", self.regs["R2022"])
		rule.max_arrears = 5
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be edited"):
			rule.save()


class TestFixRound1(GraduationFixture):
	def s2_result(self, key):
		return frappe.db.get_value("Student Result", {"student": self.students[key], "exam_session": self.s2})

	def test_i1_an_issued_print_keeps_its_issued_values(self):
		doc = self.request("dist", CONSOLIDATED)
		snapshot = frappe.parse_json(frappe.db.get_value("Certificate Request", doc.name, "record_snapshot"))
		self.assertEqual((snapshot["cgpa"], snapshot["classification"]), (8.75, DISTINCTION))
		# a later result (revaluation) lowers GRD C3, and the rule's distinction line moves
		frappe.db.set_value("Student Result Course", {"parent": self.s2_result("dist"), "course": "GRD C3"}, "grade_point", 5)
		frappe.db.set_value("Classification Rule Class", {"parent": self.regs["R2022"], "class_name": DISTINCTION}, "cgpa_min", 9.9)
		self.assertNotEqual(graduation.graduate_record(self.students["dist"]).cgpa, 8.75)
		html = self.printed(doc)
		for text in ("87.50", "8.75", DISTINCTION):
			self.assertIn(text, html)

	def test_i1_a_submitted_request_without_a_snapshot_does_not_render_live(self):
		doc = self.request("dist", TRANSCRIPT)
		frappe.db.set_value("Certificate Request", doc.name, "record_snapshot", None)
		with self.assertRaisesRegex(frappe.ValidationError, "snapshot"):
			self.printed(doc)

	def test_i2_graduate_documents_need_approval_the_transcript_does_not(self):
		for certificate_type in (CONSOLIDATED, PROVISIONAL, DATA_SHEET):
			self.assertEqual(frappe.db.get_value("Certificate Type", certificate_type, "needs_approval"), 1)
			doc = self.request("dist", certificate_type, submit=False)
			with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
				doc.submit()
		self.assertEqual(frappe.db.get_value("Certificate Type", TRANSCRIPT, "needs_approval"), 0)

	def test_i2_one_provisional_and_one_degree_certificate_per_student(self):
		first = self.request("dist", PROVISIONAL)
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.request("dist", PROVISIONAL, submit=False)
		first.cancel()
		self.request("dist", PROVISIONAL)  # allowed again once the first is cancelled
		self.awarding("College")
		self.request("dist", DEGREE)
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.request("dist", DEGREE, submit=False)
		self.request("dist", CONSOLIDATED)
		self.request("dist", CONSOLIDATED)  # a grade sheet copy may be issued again

	def test_i2_the_degree_data_sheet_is_not_requestable_in_the_portal(self):
		from campus.student_services import portal

		user = "grd-student-ds@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "GrdDs", "send_welcome_email": 0, "roles": [{"role": "Student"}]}).insert()
		frappe.db.set_value("Student", self.students["dist"], "user", user)
		frappe.set_user(user)
		self.assertNotIn(DATA_SHEET, [t.name for t in portal.certificate_types()])
		self.assertIn(CONSOLIDATED, [t.name for t in portal.certificate_types()])
		with self.assertRaises(frappe.PermissionError):
			portal.request_certificate(DATA_SHEET, "University")
		frappe.set_user("Administrator")
		self.request("dist", DATA_SHEET)  # the desk can

	def test_pending_ratification_versions_never_count(self):
		name = self.s2_result("dist")
		frappe.db.set_value("Student Result", name, "pending_ratification", 1)
		record = graduation.graduate_record(self.students["dist"])
		self.assertEqual([s.exam_session for s in record.semesters], [self.s1])

	def test_m2_the_regulation_credit_total_must_be_earned(self):
		rule = {"doctype": "Curriculum Rule", "regulation": self.regs["R2022"], "min_total_credits": 12, "max_total_credits": 200}
		frappe.get_doc(rule).insert()
		self.assertTrue(graduation.graduate_record(self.students["dist"]).completed)  # 12 core credits
		frappe.db.set_value("Curriculum Rule", {"regulation": self.regs["R2022"]}, "min_total_credits", 15)
		record = graduation.graduate_record(self.students["dist"])
		self.assertEqual((record.completed, record.classification), (False, None))

	def test_m3_a_rerun_reconsiders_the_runs_detained_students(self):
		frappe.get_doc({"doctype": "Progression Rule", "regulation": self.regs["R2022"], "max_arrears": 0}).insert()
		frappe.get_doc({"doctype": "Progression Rule", "regulation": self.regs["R2026"], "max_arrears": 0}).insert()
		doc = frappe.get_doc({"doctype": "Progression Run", "company": COLLEGE, "academic_term": self.terms["S2"], "program": PROGRAM}).insert()
		with patch.object(bulk, "enqueue_run"):
			doc.submit()
		doc.reload()
		run = frappe.get_doc("Bulk Run", doc.bulk_run)
		progression.progress_student(self.students["arrear"], run)
		self.assertEqual(frappe.db.get_value("Student", self.students["arrear"], ["oc_academic_status", "oc_detained"]), ("Active", 1))
		# a revaluation clears the arrear; the re-run takes the detained student again and promotes
		frappe.db.set_value("Student Result Course", {"parent": self.s2_result("arrear"), "course": "GRD C4"}, {"result": "Pass", "grade_point": 7})
		self.assertIn(self.students["arrear"], progression.active_students(doc))
		self.assertEqual(progression.progress_student(self.students["arrear"], run), "Promote")
		self.assertEqual(
			frappe.db.get_value("Student", self.students["arrear"], ["oc_academic_status", "oc_detained", "oc_current_semester"]), ("Active", 0, 3)
		)


class TestFixRound2(GraduationFixture):
	def student_login(self, key, user):
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "GrdN1", "send_welcome_email": 0, "roles": [{"role": "Student"}]}).insert()
		frappe.db.set_value("Student", self.students[key], "user", user)

	def test_n1_a_student_cannot_print_their_pending_graduate_draft(self):
		from frappe.utils.print_format import download_pdf

		self.student_login("dist", "grd-n1@example.com")
		draft = self.request("dist", PROVISIONAL, submit=False)
		frappe.set_user("grd-n1@example.com")
		self.assertTrue(frappe.has_permission("Certificate Request", "read", draft.name))  # the student does see it
		with self.assertRaisesRegex(Exception, "(?i)draft"):
			frappe.get_print("Certificate Request", draft.name, PROVISIONAL)
		with self.assertRaisesRegex(Exception, "(?i)draft"):
			download_pdf("Certificate Request", draft.name, PROVISIONAL)

	def test_n1_a_staff_draft_preview_is_watermarked_an_issued_print_is_not(self):
		draft = self.request("dist", PROVISIONAL, submit=False)
		self.assertIn("DRAFT - NOT VALID", self.printed(draft))
		issued = self.approve(draft)
		self.assertNotIn("DRAFT - NOT VALID", self.printed(issued))

	def test_any_examination_draft_is_staff_only_the_transcript_too(self):
		self.student_login("dist", "grd-n1t@example.com")
		frappe.db.set_value("Certificate Type", TRANSCRIPT, "needs_approval", 1)  # a college may require it
		draft = self.request("dist", TRANSCRIPT, submit=False)
		frappe.set_user("grd-n1t@example.com")
		with self.assertRaisesRegex(Exception, "(?i)draft"):
			frappe.get_print("Certificate Request", draft.name, TRANSCRIPT)

	def test_a_draft_made_before_approval_was_required_still_needs_it_at_submit(self):
		frappe.db.set_value("Certificate Type", PROVISIONAL, "needs_approval", 0)
		draft = self.request("dist", PROVISIONAL, submit=False)
		self.assertEqual(draft.needs_approval, 0)
		frappe.db.set_value("Certificate Type", PROVISIONAL, "needs_approval", 1)  # the fix round 1 patch
		with self.assertRaisesRegex(frappe.ValidationError, "approval"):
			draft.submit()
