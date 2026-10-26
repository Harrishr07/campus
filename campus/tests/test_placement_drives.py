"""M14-01, M14-02 tests (P4-T13): the eligibility rules, live eligibility from published results, the registration gate,
round-result shortlists with bulk upload, the portal opt-in and the drive notice.

Fixture: one college with courses PLC1-PLC3 and five students with hand-made published Student Results:
- ace: passes all three courses at the first appearance, CGPA 9.00
- fresh: the same pass but a lower 7.00 CGPA
- stuck: fails PLC3 in S1 and has not cleared it (standing arrear, history)
- cleared: fails PLC3 in S1 (S1 published earlier); the test adds a pass in S2 (history, no standing arrear)
- outsider: a student of another college with the ace results
"""

import csv
import io

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import add_days, now_datetime, today

from campus.placement import api, eligibility, export, portal, round_upload, rules
from campus.tests.factories import make_company
from campus.tests.test_regulation import enroll, make_program, make_student, make_year, year_name
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR, OTHER, OTHER_ABBR = "Placement Test College", "PTC", "Placement Other College", "PTO"
PROGRAM, OTHER_PROGRAM = "Placement Test BE", "Placement Test ME"
COURSES = ("PLC1", "PLC2", "PLC3")


class TestEligibilityRules(UnitTestCase):
	def student(self, **kw):
		return {
			"cgpa": 8,
			"standing_arrears": 0,
			"had_arrears": False,
			"gender": "Male",
			"program": "BE",
			"batch": "B1",
			**kw,
		}

	def test_everything_met_is_eligible(self):
		criteria = {
			"min_cgpa": 7.5,
			"max_standing_arrears": 0,
			"allow_arrear_history": 0,
			"gender": "Male",
			"programs": ["BE"],
			"batches": ["B1"],
		}
		self.assertEqual(rules.reasons(criteria, self.student()), [])

	def test_blank_criteria_restrict_nothing(self):
		self.assertEqual(
			rules.reasons(
				{"allow_arrear_history": 1}, self.student(gender=None, program=None, batch=None, cgpa=0)
			),
			[],
		)

	def test_cgpa_boundary(self):
		self.assertEqual(rules.reasons({"min_cgpa": 8, "allow_arrear_history": 1}, self.student(cgpa=8)), [])
		self.assertEqual(
			len(rules.reasons({"min_cgpa": 8.01, "allow_arrear_history": 1}, self.student(cgpa=8))), 1
		)

	def test_standing_arrear_limit(self):
		base = {"max_standing_arrears": 1, "allow_arrear_history": 1}
		self.assertEqual(rules.reasons(base, self.student(standing_arrears=1)), [])
		self.assertEqual(len(rules.reasons(base, self.student(standing_arrears=2))), 1)

	def test_any_standing_arrears_lifts_the_limit(self):
		criteria = {"any_standing_arrears": 1, "max_standing_arrears": 0, "allow_arrear_history": 1}
		self.assertEqual(rules.reasons(criteria, self.student(standing_arrears=9)), [])

	def test_history_of_arrears_refused_when_not_allowed(self):
		self.assertEqual(len(rules.reasons({"allow_arrear_history": 0}, self.student(had_arrears=True))), 1)
		self.assertEqual(rules.reasons({"allow_arrear_history": 1}, self.student(had_arrears=True)), [])

	def test_gender_program_and_batch(self):
		base = {"allow_arrear_history": 1}
		self.assertEqual(len(rules.reasons({**base, "gender": "Female"}, self.student())), 1)
		self.assertEqual(len(rules.reasons({**base, "programs": ["ME"]}, self.student())), 1)
		self.assertEqual(len(rules.reasons({**base, "batches": ["B2"]}, self.student())), 1)
		self.assertEqual(len(rules.reasons({**base, "programs": ["ME"]}, self.student(program=None))), 1)

	def test_every_failure_is_listed(self):
		criteria = {"min_cgpa": 9, "max_standing_arrears": 0, "allow_arrear_history": 0}
		self.assertEqual(len(rules.reasons(criteria, self.student(standing_arrears=1, had_arrears=True))), 3)


class TestSafeCell(UnitTestCase):
	def test_formula_starts_are_neutralised(self):
		for text in ("=1+1", "+cmd", "-2", "@SUM(A1)", "\tx", "  =1"):
			self.assertTrue(export.safe_cell(text).startswith("'"), text)
		self.assertEqual(export.safe_cell("plain"), "plain")
		self.assertEqual(export.safe_cell(None), "")


class PlacementFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for name, abbr in ((COLLEGE, ABBR), (OTHER, OTHER_ABBR)):
			make_company(name, abbr)
		make_year("2022")
		make_program(PROGRAM, COLLEGE)
		make_program(OTHER_PROGRAM, COLLEGE)
		for gender in ("Male", "Female"):
			if not frappe.db.exists("Gender", gender):
				frappe.get_doc({"doctype": "Gender", "gender": gender}).insert()
		for course in COURSES:
			if not frappe.db.exists("Course", course):
				frappe.get_doc({"doctype": "Course", "course_name": course, "oc_company": COLLEGE}).insert()
		cls.terms = {
			key: cls.make_term(key, start, end)
			for key, start, end in (("S1", "2022-06-01", "2022-11-30"), ("S2", "2022-12-01", "2023-03-31"))
		}
		cls.s1 = cls.make_session(cls.terms["S1"], add_days(now_datetime(), -3))
		cls.s2 = cls.make_session(cls.terms["S2"], add_days(now_datetime(), -1), published=False)
		cls.students = {}
		for key, company, gender, rows in (
			("ace", COLLEGE, "Female", [("PLC1", 9, "Pass"), ("PLC2", 9, "Pass"), ("PLC3", 9, "Pass")]),
			("fresh", COLLEGE, "Male", [("PLC1", 7, "Pass"), ("PLC2", 7, "Pass"), ("PLC3", 7, "Pass")]),
			("stuck", COLLEGE, "Male", [("PLC1", 9, "Pass"), ("PLC2", 9, "Pass"), ("PLC3", 0, "Fail")]),
			("cleared", COLLEGE, "Male", [("PLC1", 9, "Pass"), ("PLC2", 9, "Pass"), ("PLC3", 0, "Fail")]),
			("outsider", OTHER, "Female", [("PLC1", 9, "Pass"), ("PLC2", 9, "Pass"), ("PLC3", 9, "Pass")]),
		):
			student = make_student(f"Pl{key.title()}", company, "2022")
			if company == COLLEGE:
				enroll(student, PROGRAM, "2022", submit=True)
			frappe.db.set_value("Student", student.name, "gender", gender)
			cls.students[key] = student.name
			cls.make_result(student.name, company, cls.s1, rows)

	@classmethod
	def make_term(cls, key, start, end):
		name = f"Pl {key}"
		found = frappe.db.get_value("Academic Term", {"academic_year": year_name("2022"), "term_name": name})
		return found or frappe.get_doc(
			{"doctype": "Academic Term", "academic_year": year_name("2022"), "term_name": name, "term_start_date": start, "term_end_date": end}
		).insert().name  # fmt: skip

	@classmethod
	def make_session(cls, term, publish_at, published=True):
		session = frappe.get_doc(
			{"doctype": "Exam Session", "company": COLLEGE, "academic_term": term, "status": "Marks Entry"}
		).insert()
		frappe.db.set_value(
			"Exam Session",
			session.name,
			{"status": "Published" if published else "Marks Entry", "publish_at": publish_at},
		)
		return session.name

	@classmethod
	def publish(cls, session):
		frappe.db.set_value("Exam Session", session, "status", "Published")

	@classmethod
	def make_result(cls, student, company, session, rows):
		term = frappe.db.get_value("Exam Session", session, "academic_term")
		frappe.get_doc(
			{
				"doctype": "Student Result", "student": student, "exam_session": session, "company": company, "academic_term": term,
				"program": PROGRAM, "version": 1, "is_latest": 1, "result": "Pass" if all(r[2] == "Pass" for r in rows) else "Reappear",
				"courses": [
					{"course": c, "grade_point": gp, "grade": "O" if gp >= 9 else "X" if gp else "U", "result": result, "credits": 3,
					"in_gpa": 1, "kind": "Current", "total": gp * 10}
					for c, gp, result in rows
				],
			}
		).insert(ignore_permissions=True)  # fmt: skip

	def setUp(self):
		frappe.db.savepoint("placement_test")
		self.addCleanup(frappe.db.rollback, save_point="placement_test")
		self.recruiter = frappe.get_doc(
			{"doctype": "Recruiter", "recruiter_name": "Acme Soft", "company": COLLEGE}
		).insert()

	def make_drive(self, status="Open", **kw):
		values = {
			"doctype": "Placement Drive", "drive_title": "Acme Campus Drive", "company": COLLEGE,
			"academic_year": year_name("2022"), "recruiter": self.recruiter.name, "drive_date": add_days(today(), 7),
			"status": status, "roles": [{"role_title": "Engineer", "openings": 5, "ctc": 600000}],
			"rounds": [{"round_no": 1, "round_name": "Aptitude"}, {"round_no": 2, "round_name": "Interview"}],
			"min_cgpa": 8, "max_standing_arrears": 0, "allow_arrear_history": 1, **kw,
		}  # fmt: skip
		return frappe.get_doc(values).insert()

	def register(self, drive, key):
		return frappe.get_doc(
			{"doctype": "Drive Registration", "drive": drive.name, "student": self.students[key]}
		).insert()


class TestLiveEligibility(PlacementFixture):
	def test_cgpa_and_arrears_come_from_published_results(self):
		drive = self.make_drive()
		ace = eligibility.evaluate(drive, self.students["ace"])
		self.assertTrue(ace["eligible"])
		self.assertEqual(ace["cgpa"], 9)
		fresh = eligibility.evaluate(drive, self.students["fresh"])
		self.assertFalse(fresh["eligible"])
		self.assertEqual(fresh["cgpa"], 7)
		stuck = eligibility.evaluate(drive, self.students["stuck"])
		self.assertEqual(stuck["standing_arrears"], 1)
		self.assertTrue(stuck["had_arrears"])

	def test_clearing_an_arrear_makes_the_student_eligible_without_a_change(self):
		drive = self.make_drive(min_cgpa=0)
		student = self.students["cleared"]
		self.assertFalse(eligibility.evaluate(drive, student)["eligible"])
		self.publish(self.s2)
		self.make_result(student, COLLEGE, self.s2, [("PLC3", 8, "Pass")])
		now = eligibility.evaluate(drive, student)
		self.assertTrue(now["eligible"])
		self.assertEqual(now["standing_arrears"], 0)
		self.assertTrue(now["had_arrears"])  # cleared, but still on record

	def test_history_of_arrears_can_be_excluded(self):
		drive = self.make_drive(min_cgpa=0, allow_arrear_history=0)
		student = self.students["cleared"]
		self.publish(self.s2)
		self.make_result(student, COLLEGE, self.s2, [("PLC3", 8, "Pass")])
		self.assertFalse(eligibility.evaluate(drive, student)["eligible"])

	def test_unpublished_results_do_not_count(self):
		drive = self.make_drive(min_cgpa=0)
		student = self.students["stuck"]
		self.make_result(student, COLLEGE, self.s2, [("PLC3", 8, "Pass")])  # S2 is not published
		self.assertEqual(eligibility.evaluate(drive, student)["standing_arrears"], 1)

	def test_gender_program_and_batch_criteria(self):
		drive = self.make_drive(min_cgpa=0, gender="Female", programs=[{"program": OTHER_PROGRAM}])
		result = eligibility.evaluate(drive, self.students["ace"])
		self.assertEqual(len(result["reasons"]), 1)  # Female passes, the program does not
		drive.set("programs", [{"program": PROGRAM}])
		drive.set("batches", [{"batch": year_name("2022")}])
		self.assertTrue(eligibility.evaluate(drive, self.students["ace"])["eligible"])
		self.assertFalse(eligibility.evaluate(drive, self.students["fresh"])["eligible"])  # male

	def test_template_criteria_are_copied_to_the_drive(self):
		template = frappe.get_doc(
			{"doctype": "Placement Eligibility Template", "template_name": "Tier 1", "company": COLLEGE, "min_cgpa": 8.5,
			"allow_arrear_history": 0, "programs": [{"program": PROGRAM}]}
		).insert()  # fmt: skip
		drive = self.make_drive(
			eligibility_template=template.name,
			min_cgpa=0,
			allow_arrear_history=1,
			rounds=[],
			roles=[],
			status="Draft",
		)
		self.assertEqual(drive.min_cgpa, 8.5)
		self.assertEqual(drive.allow_arrear_history, 0)
		self.assertEqual([row.program for row in drive.programs], [PROGRAM])
		self.assertEqual(eligibility.template_criteria(template.name)["min_cgpa"], 8.5)

	def test_criteria_sent_with_a_drive_are_not_overwritten_by_its_template(self):
		template = frappe.get_doc(
			{"doctype": "Placement Eligibility Template", "template_name": "Tier 2", "company": COLLEGE, "min_cgpa": 8.5}
		).insert()  # fmt: skip
		drive = self.make_drive(eligibility_template=template.name, min_cgpa=6)
		self.assertEqual(drive.min_cgpa, 6)

	def test_a_course_only_withdrawn_from_is_not_history(self):
		student = self.students["ace"]
		self.publish(self.s2)
		self.make_result(student, COLLEGE, self.s2, [("PLC1", 0, "WD")])
		self.assertFalse(eligibility.student_standing(student)["had_arrears"])

	def test_other_college_template_is_refused(self):
		template = frappe.get_doc(
			{"doctype": "Placement Eligibility Template", "template_name": "Other T", "company": OTHER}
		).insert()
		with self.assertRaises(frappe.ValidationError):
			self.make_drive(eligibility_template=template.name)


class TestRegistrationGate(PlacementFixture):
	def test_eligible_student_registers_with_a_snapshot(self):
		registration = self.register(self.make_drive(), "ace")
		self.assertEqual(
			(registration.status, registration.company, registration.cgpa), ("Registered", COLLEGE, 9)
		)
		self.assertEqual(registration.standing_arrears, 0)

	def test_ineligible_students_are_refused_with_reasons(self):
		drive = self.make_drive()
		for key in ("fresh", "stuck"):
			with self.assertRaises(frappe.ValidationError) as caught:
				self.register(drive, key)
			self.assertIn("not eligible", str(caught.exception))

	def test_student_of_another_college_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.register(self.make_drive(min_cgpa=0), "outsider")

	def test_only_students_on_the_roll_may_register(self):
		drive = self.make_drive(min_cgpa=0, max_standing_arrears=1)
		for status in ("Discontinued", "Withdrawn", "Alumni", "Admitted"):
			frappe.db.set_value("Student", self.students["ace"], "oc_academic_status", status)
			with self.assertRaises(frappe.ValidationError, msg=status):
				self.register(drive, "ace")
		for status in ("Joined", "Active", "On Break"):
			frappe.db.set_value("Student", self.students["ace"], "oc_academic_status", status)
			frappe.db.delete("Drive Registration", {"drive": drive.name})
			self.assertEqual(self.register(drive, "ace").status, "Registered", status)

	def test_registration_needs_an_open_drive_before_the_deadline(self):
		with self.assertRaises(frappe.ValidationError):
			self.register(self.make_drive(status="Draft", roles=[]), "ace")
		with self.assertRaises(frappe.ValidationError):
			self.register(self.make_drive(registration_deadline=add_days(now_datetime(), -1)), "ace")

	def test_a_student_registers_once(self):
		drive = self.make_drive()
		self.register(drive, "ace")
		with self.assertRaises(frappe.DuplicateEntryError):
			self.register(drive, "ace")

	def test_withdrawn_student_registers_again_only_while_eligible(self):
		drive = self.make_drive()
		registration = self.register(drive, "ace")
		registration.status = "Withdrawn"
		registration.save()
		self.assertEqual(api.registered_students(drive.name), [])
		registration.status = "Registered"
		registration.save()
		self.assertEqual(api.registered_students(drive.name), [self.students["ace"]])

	def test_snapshot_and_trash(self):
		drive = self.make_drive()
		registration = self.register(drive, "ace")
		registration.cgpa = 10
		registration.save()
		self.assertEqual(registration.reload().cgpa, 9)
		frappe.get_doc(
			{
				"doctype": "Round Result",
				"drive": drive.name,
				"round_no": 1,
				"results": [{"student": self.students["ace"]}],
			}
		).insert()
		with self.assertRaises(frappe.ValidationError):
			registration.delete()

	def test_company_scoped_officer_cannot_register_or_list_for_another_college(self):
		drive = self.make_drive(min_cgpa=0)
		email = "pl-officer@placement-test.example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "PlOfficer",
					"send_welcome_email": 0,
					"roles": [{"role": "Placement Officer"}],
				}
			).insert()
		frappe.get_doc(
			{"doctype": "User Permission", "user": email, "allow": "Company", "for_value": OTHER}
		).insert()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(email)
		with self.assertRaises(frappe.PermissionError):
			self.register(drive, "ace")
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Round Result", "drive": drive.name, "round_no": 1}).insert()

	def test_open_drives_show_live_state_per_student(self):
		drive = self.make_drive()
		rows = {row["drive"].name: row for row in api.open_drives(self.students["fresh"])}
		self.assertFalse(rows[drive.name]["eligible"])
		self.assertTrue(rows[drive.name]["reasons"])
		self.assertEqual(api.open_drives(self.students["outsider"]), [])

	def test_drive_roles_recruiter_and_company_are_checked(self):
		other = frappe.get_doc(
			{"doctype": "Recruiter", "recruiter_name": "Acme Soft", "company": OTHER}
		).insert()
		with self.assertRaises(frappe.ValidationError):
			self.make_drive(recruiter=other.name)
		with self.assertRaises(frappe.ValidationError):
			self.make_drive(roles=[])
		with self.assertRaises(frappe.ValidationError):
			self.make_drive(rounds=[{"round_no": 1, "round_name": "A"}, {"round_no": 1, "round_name": "B"}])


class TestRecruiterMou(PlacementFixture):
	def make_mou(self, company, status="Active"):
		mou = frappe.get_doc(
			{"doctype": "Institutional MoU", "company": company, "partner": "Acme Soft", "partner_type": "Industry",
			"used_for": "Placement", "purpose": "Campus recruitment", "valid_from": add_days(today(), -30), "valid_to": add_days(today(), 300)}
		).insert()  # fmt: skip
		frappe.db.set_value("Institutional MoU", mou.name, "status", status)
		return mou

	def test_mou_links_and_belongs_to_the_company(self):
		self.recruiter.mou = self.make_mou(COLLEGE).name
		self.recruiter.save()
		self.recruiter.mou = self.make_mou(OTHER).name
		with self.assertRaises(frappe.ValidationError):
			self.recruiter.save()

	def test_terminated_mou_is_refused_and_blocks_opening_a_drive(self):
		self.recruiter.mou = self.make_mou(COLLEGE).name
		self.recruiter.save()
		drive = self.make_drive()
		frappe.db.set_value("Institutional MoU", self.recruiter.mou, "status", "Terminated")
		drive.reload()
		drive.drive_title = "Renamed"
		with self.assertRaises(frappe.ValidationError):
			drive.save()
		self.recruiter.mou = self.make_mou(COLLEGE, "Terminated").name
		with self.assertRaises(frappe.ValidationError):
			self.recruiter.save()

	def test_recruiter_name_is_unique_per_company(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Recruiter", "recruiter_name": "Acme Soft", "company": COLLEGE}
			).insert()


class TestRoundResults(PlacementFixture):
	def setUp(self):
		super().setUp()
		self.drive = self.make_drive(min_cgpa=0, max_standing_arrears=1)
		for key in ("ace", "fresh", "stuck"):
			self.register(self.drive, key)

	def result(self, round_no=1, **kw):
		return frappe.get_doc(
			{"doctype": "Round Result", "drive": self.drive.name, "round_no": round_no, **kw}
		)

	def test_shortlist_of_registered_students(self):
		doc = self.result(results=[{"student": self.students["ace"], "result": "Shortlisted"}]).insert()
		self.assertEqual((doc.round_name, doc.company), ("Aptitude", COLLEGE))

	def test_unregistered_student_cannot_be_shortlisted(self):
		with self.assertRaises(frappe.ValidationError):
			self.result(results=[{"student": self.students["cleared"], "result": "Shortlisted"}]).insert()

	def test_withdrawn_student_cannot_be_shortlisted(self):
		registration = frappe.get_doc("Drive Registration", f"{self.drive.name}-{self.students['fresh']}")
		registration.status = "Withdrawn"
		registration.save()
		with self.assertRaises(frappe.ValidationError):
			self.result(results=[{"student": self.students["fresh"], "result": "Shortlisted"}]).insert()

	def test_listed_student_cannot_withdraw_and_duplicates_are_refused(self):
		self.result(results=[{"student": self.students["ace"], "result": "Selected"}]).insert()
		registration = frappe.get_doc("Drive Registration", f"{self.drive.name}-{self.students['ace']}")
		registration.status = "Withdrawn"
		with self.assertRaises(frappe.ValidationError):
			registration.save()
		with self.assertRaises(frappe.ValidationError):
			self.result(
				2, results=[{"student": self.students["ace"]}, {"student": self.students["ace"]}]
			).insert()

	def test_round_must_exist_and_drive_must_be_open(self):
		with self.assertRaises(frappe.ValidationError):
			self.result(5).insert()
		frappe.db.set_value("Placement Drive", self.drive.name, "status", "Draft")
		with self.assertRaises(frappe.ValidationError):
			self.result().insert()

	def test_template_lists_registered_students_safely(self):
		frappe.db.set_value("Student", self.students["ace"], "first_name", "=HYPERLINK(1)")
		frappe.db.set_value(
			"Drive Registration", f"{self.drive.name}-{self.students['ace']}", "student_name", "=HYPERLINK(1)"
		)
		doc = self.result().insert()
		rows = export.template_rows(doc.name)
		self.assertEqual(rows[0], export.HEADER)
		self.assertEqual({row[0] for row in rows[1:]}, {self.students[k] for k in ("ace", "fresh", "stuck")})
		self.assertTrue(any(row[1] == "'=HYPERLINK(1)" for row in rows[1:]))

	def attach(self, doc, text, name="results.csv"):
		file = frappe.get_doc(
			{"doctype": "File", "file_name": name, "content": text, "attached_to_doctype": "Round Result", "attached_to_name": doc.name,
			"is_private": 1}
		).insert(ignore_permissions=True)  # fmt: skip
		doc.db_set("upload_file", file.file_url)

	def csv(self, rows):
		out = io.StringIO()
		csv.writer(out).writerows([["Student", "Result", "Remarks"], *rows])
		return out.getvalue()

	def test_bulk_upload_merges_rows(self):
		doc = self.result(results=[{"student": self.students["ace"], "result": "Shortlisted"}]).insert()
		self.attach(
			doc,
			self.csv(
				[
					[self.students["ace"], "Selected", "Top"],
					[self.students["fresh"], "Not Shortlisted", "=cmd()"],
				]
			),
		)
		self.assertEqual(round_upload.load_results(doc.name), 2)
		doc.reload()
		found = {row.student: (row.result, row.remarks) for row in doc.results}
		self.assertEqual(
			found,
			{
				self.students["ace"]: ("Selected", "Top"),
				self.students["fresh"]: ("Not Shortlisted", "=cmd()"),
			},
		)

	def test_bulk_upload_refuses_the_whole_file_on_a_bad_row(self):
		doc = self.result().insert()
		self.attach(
			doc,
			self.csv(
				[
					[self.students["ace"], "Selected", ""],
					[self.students["cleared"], "Selected", ""],
					[self.students["fresh"], "Maybe", ""],
				]
			),
		)
		with self.assertRaises(frappe.ValidationError) as caught:
			round_upload.load_results(doc.name)
		message = str(caught.exception)
		self.assertIn("Row 3", message)
		self.assertIn("Row 4", message)
		self.assertEqual(frappe.db.count("Round Result Student", {"parent": doc.name}), 0)

	def test_xlsx_and_cp1252_files_are_read(self):
		from openpyxl import Workbook

		book = Workbook()
		book.active.append(["Student", "Result", "Remarks"])
		book.active.append([self.students["ace"], "Selected", "ok"])
		out = io.BytesIO()
		book.save(out)
		doc = self.result().insert()
		file = frappe.get_doc(
			{"doctype": "File", "file_name": "r.xlsx", "content": out.getvalue(), "is_private": 1}
		).insert(ignore_permissions=True)
		self.assertEqual(export.read_rows(file.file_url), [(2, self.students["ace"], "Selected", "ok")])
		self.assertEqual(export.decode("caf\xe9".encode("cp1252")), "caf\xe9")
		self.assertEqual(doc.round_no, 1)

	def test_row_cap(self):
		with self.assertRaises(frappe.ValidationError):
			export.parse_table([["Student", "Result"], *[["S", "Absent"]] * (export.MAX_ROWS + 1)])
		self.assertEqual(
			len(export.parse_table([["Student", "Result"], *[["S", "Absent"]] * export.MAX_ROWS])),
			export.MAX_ROWS,
		)

	def test_bulk_upload_needs_the_columns(self):
		with self.assertRaises(frappe.ValidationError):
			export.parse_table([["Name", "Marks"], ["x", "1"]])
		with self.assertRaises(frappe.ValidationError):
			export.parse_table([])
		self.assertEqual(
			export.parse_table([["student", "RESULT"], ["S1", "Absent"], ["", ""]]), [(2, "S1", "Absent", "")]
		)


class TestPortalOptIn(PlacementFixture):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")

	def as_student(self, key):
		email = f"{key}@placement-portal.example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": key,
					"send_welcome_email": 0,
					"roles": [{"role": "Student"}],
				}
			).insert()
		frappe.db.set_value("Student", self.students[key], "user", email)
		frappe.set_user(email)

	def test_student_sees_live_eligibility_and_registers(self):
		drive = self.make_drive()
		self.as_student("fresh")
		row = portal.my_drives()["drives"][0]
		self.assertFalse(row["eligible"])
		self.assertFalse(row["can_register"])
		with self.assertRaises(frappe.ValidationError):
			portal.register(drive.name)
		frappe.set_user("Administrator")
		self.as_student("ace")
		self.assertTrue(portal.my_drives()["drives"][0]["can_register"])
		name = portal.register(drive.name)
		self.assertEqual(frappe.db.get_value("Drive Registration", name, "status"), "Registered")
		self.assertEqual(portal.my_drives()["drives"][0]["registration"], "Registered")
		portal.withdraw(drive.name)
		self.assertEqual(frappe.db.get_value("Drive Registration", name, "status"), "Withdrawn")
		self.assertEqual(portal.register(drive.name), name)  # opting back in reuses the record
		self.assertEqual(frappe.db.get_value("Drive Registration", name, "status"), "Registered")

	def test_only_the_student_registers(self):
		drive = self.make_drive()
		guardian = "pl-guardian@placement-portal.example.com"
		if not frappe.db.exists("User", guardian):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": guardian,
					"first_name": "PlG",
					"send_welcome_email": 0,
					"roles": [{"role": "Guardian"}],
				}
			).insert()
		if not frappe.db.exists("Guardian", {"user": guardian}):
			frappe.get_doc(
				{"doctype": "Guardian", "guardian_name": "PlG", "email_address": guardian, "user": guardian}
			).insert()
		guardian_name = frappe.db.get_value("Guardian", {"user": guardian})
		student = frappe.get_doc("Student", self.students["ace"])
		student.append("guardians", {"guardian": guardian_name, "guardian_name": "PlG", "relation": "Father"})
		student.save()
		frappe.set_user(guardian)
		self.assertTrue(portal.my_drives()["drives"])
		with self.assertRaises(frappe.PermissionError):
			portal.register(drive.name)

	def test_registration_after_the_deadline_is_refused(self):
		drive = self.make_drive(registration_deadline=add_days(now_datetime(), 1))
		self.as_student("ace")
		self.assertTrue(portal.my_drives()["drives"][0]["can_register"])
		frappe.db.set_value(
			"Placement Drive", drive.name, "registration_deadline", add_days(now_datetime(), -1)
		)
		row = portal.my_drives()["drives"][0]
		self.assertTrue(row["closed"])
		self.assertFalse(row["can_register"])
		with self.assertRaises(frappe.ValidationError):
			portal.register(drive.name)

	def test_student_of_another_college_cannot_register_through_the_portal(self):
		drive = self.make_drive(min_cgpa=0)
		self.as_student("outsider")
		self.assertEqual(portal.my_drives()["drives"], [])
		with self.assertRaises(frappe.ValidationError):
			portal.register(drive.name)

	def test_portal_page_context(self):
		self.make_drive()
		self.as_student("ace")
		context = frappe._dict()
		frappe.get_attr("campus.www.campus_portal.placement.get_context")(context)
		self.assertEqual(context.active, "placement")
		self.assertEqual(len(context.placement["drives"]), 1)
		self.assertEqual(context.placement["drives"][0]["drive_title"], "Acme Campus Drive")

	def test_notice_prints_criteria(self):
		drive = self.make_drive(min_cgpa=7.5, programs=[{"program": PROGRAM}])
		html = frappe.get_print("Placement Drive", drive.name, "Placement Drive Notice")
		for text in ("Acme Campus Drive", "Engineer", "7.5", PROGRAM, "Aptitude"):
			self.assertIn(text, html)
