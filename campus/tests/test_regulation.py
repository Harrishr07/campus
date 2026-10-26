"""M02-04 tests: regulation model, resolution, auto-assignment, edit lock and guarded change."""

import frappe
from frappe.utils import today

from campus.campus_platform.api import get_regulation, get_rule
from campus.campus_platform.doctype.regulation.regulation import (
	amend_as_new_version,
	next_version_code,
	regulation_name,
)
from campus.campus_platform.regulation_rules import change_regulation, resolve_regulation
from campus.tests.factories import make_company, make_user
from campus.tests.utils import CampusTestCase

COLLEGE = "Regulation Test College"
OTHER_COLLEGE = "Regulation Test Other College"
DEAN = "campus-dean@example.com"
PLAIN_USER = "campus-regulation-plain@example.com"
YEARS = {year: f"{year}-06-01" for year in ("2020", "2021", "2022", "2023", "2026")}
RULE_DOCTYPE = "Eligibility Rule"  # a real rule set with a `regulation` link; a test DocType would be DDL


def year_name(year):
	return f"RT-{year}"


def make_year(year):
	name = year_name(year)
	if not frappe.db.exists("Academic Year", name):
		frappe.get_doc(
			{
				"doctype": "Academic Year",
				"academic_year_name": name,
				"year_start_date": YEARS[year],
				"year_end_date": f"{int(year) + 1}-05-31",
			}
		).insert()


def make_program(name, company):
	if not frappe.db.exists("Program", name):
		frappe.get_doc({"doctype": "Program", "program_name": name, "oc_company": company}).insert()
	return name


def make_regulation(code, company, programs, year, status="Effective", **extra):
	name = regulation_name(code, company)
	if frappe.db.exists("Regulation", name):
		frappe.db.delete("Regulation Program", {"parent": name})
		frappe.db.delete("Regulation", {"name": name})
	return frappe.get_doc(
		{
			"doctype": "Regulation",
			"code": code,
			"company": company,
			"effective_from_year": year_name(year),
			"status": status,
			"programs": [{"program": p} for p in programs],
			**extra,
		}
	).insert()


def make_student(first_name, company, batch=None):
	return frappe.get_doc(
		{
			"doctype": "Student",
			"first_name": first_name,
			"student_email_id": f"{first_name.lower()}@regulation-test.example.com",
			"oc_company": company,
			"oc_batch": batch and year_name(batch),
		}
	).insert()


def enroll(student, program, year, submit=False):
	enrollment = frappe.get_doc(
		{
			"doctype": "Program Enrollment",
			"student": student.name,
			"program": program,
			"academic_year": year_name(year),
			"enrollment_date": today(),
		}
	).insert()
	if submit:
		enrollment.submit()
	return enrollment


def make_rule(regulation, program, kind):
	"""An Eligibility Rule of `regulation`; `kind` goes in qualifying_exam, the field the test filters on."""
	return frappe.get_doc(
		{"doctype": RULE_DOCTYPE, "program": program, "regulation": regulation, "qualifying_exam": kind}
	).insert()


def clear_previous_run():
	"""Test data may be committed by an earlier run; remove it so every run starts clean."""
	students = frappe.get_all(
		"Student", filters={"oc_company": ["in", [COLLEGE, OTHER_COLLEGE]]}, pluck="name"
	)
	if students:
		frappe.db.delete("Program Enrollment", {"student": ["in", students]})
		frappe.db.delete("Regulation History", {"parent": ["in", students]})
		frappe.db.delete("Student", {"name": ["in", students]})
	regulations = frappe.get_all("Regulation", filters={"company": COLLEGE}, pluck="name")
	if regulations:
		frappe.db.delete("Regulation Program", {"parent": ["in", regulations]})
		frappe.db.delete("Regulation", {"name": ["in", regulations]})


class TestRegulation(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		clear_previous_run()
		make_company(COLLEGE, "RTC")
		make_company(OTHER_COLLEGE, "RTO")
		for year in YEARS:
			make_year(year)
		cls.program = make_program("Regulation Test BSc", COLLEGE)
		cls.other_program = make_program("Regulation Test BCom", COLLEGE)
		cls.scratch_program = make_program("Regulation Test Scratch", COLLEGE)
		cls.r2021 = make_regulation("AU-R2021", COLLEGE, [cls.program], "2021").name
		cls.r2022 = make_regulation("R2022", COLLEGE, [cls.program], "2022").name
		cls.r2026 = make_regulation("R2026", COLLEGE, [cls.program], "2026").name
		make_user(DEAN, [COLLEGE])
		make_user(PLAIN_USER, [COLLEGE])
		frappe.get_doc("User", DEAN).add_roles("Dean Academics")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_resolution_by_batch(self):
		cases = {"2021": self.r2021, "2022": self.r2022, "2023": self.r2022, "2026": self.r2026}
		for batch, expected in cases.items():
			with self.subTest(batch=batch):
				self.assertEqual(resolve_regulation(COLLEGE, self.program, year_name(batch)), expected)

	def test_same_code_allowed_in_two_companies_but_not_twice_in_one(self):
		other_program = make_program("Regulation Test Other BSc", OTHER_COLLEGE)
		other = make_regulation("R2022", OTHER_COLLEGE, [other_program], "2022")
		self.assertEqual((other.name, self.r2022), ("R2022-RTO", "R2022-RTC"))
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Regulation",
					"code": "R2022",
					"company": COLLEGE,
					"effective_from_year": year_name("2023"),
					"status": "Draft",
					"programs": [{"program": self.program}],
				}
			).insert()

	def test_resolution_before_first_regulation_is_none(self):
		self.assertIsNone(resolve_regulation(COLLEGE, self.program, year_name("2020")))

	def test_resolution_requires_program_company_and_effective(self):
		self.assertIsNone(resolve_regulation(COLLEGE, self.other_program, year_name("2023")))
		self.assertIsNone(resolve_regulation(OTHER_COLLEGE, self.program, year_name("2023")))
		make_regulation("R2023-DRAFT", COLLEGE, [self.program], "2023", status="Draft")
		self.assertEqual(resolve_regulation(COLLEGE, self.program, year_name("2023")), self.r2022)

	def test_program_of_other_company_rejected(self):
		foreign = make_program("Regulation Test Foreign", OTHER_COLLEGE)
		with self.assertRaises(frappe.ValidationError):
			make_regulation("R-FOREIGN", COLLEGE, [foreign], "2022", status="Draft")

	def test_enrollment_assigns_batch_and_regulation(self):
		student = make_student("RegAssign", COLLEGE)
		enroll(student, self.program, "2023")
		student.reload()
		self.assertEqual(student.oc_batch, year_name("2023"))
		self.assertEqual(student.oc_regulation, self.r2022)
		self.assertEqual(get_regulation(student.name), self.r2022)

	def test_enrollment_keeps_existing_assignment(self):
		student = make_student("RegKeep", COLLEGE, batch="2021")
		enroll(student, self.program, "2026")
		student.reload()
		self.assertEqual(student.oc_batch, year_name("2021"))
		self.assertEqual(student.oc_regulation, self.r2021)

	def test_enrollment_without_regulation_leaves_student_unassigned(self):
		student = make_student("RegNone", COLLEGE)
		enroll(student, self.other_program, "2023")
		student.reload()
		self.assertFalse(student.oc_regulation)
		self.assertIsNone(get_regulation(student.name))

	def test_direct_edit_of_assigned_regulation_blocked(self):
		student = make_student("RegLocked", COLLEGE, batch="2023")
		enroll(student, self.program, "2023")
		student.reload()
		student.oc_regulation = self.r2026
		with self.assertRaises(frappe.ValidationError):
			student.save()

	def test_change_regulation_needs_dean_role(self):
		student = make_student("RegNoDean", COLLEGE, batch="2023")
		enroll(student, self.program, "2023")
		frappe.set_user(PLAIN_USER)
		with self.assertRaises(frappe.PermissionError):
			change_regulation(student.name, self.r2026, "rejoined")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Student", student.name, "oc_regulation"), self.r2022)

	def test_change_regulation_writes_history(self):
		student = make_student("RegChange", COLLEGE, batch="2023")
		enroll(student, self.program, "2023")
		frappe.set_user(DEAN)
		change_regulation(student.name, self.r2026, "Rejoined after break", "Bridge: Maths I")
		frappe.set_user("Administrator")
		student.reload()
		self.assertEqual(student.oc_regulation, self.r2026)
		self.assertEqual(len(student.oc_regulation_history), 1)
		row = student.oc_regulation_history[0]
		self.assertEqual(
			(
				row.from_regulation,
				row.to_regulation,
				str(row.change_date),
				row.reason,
				row.bridge_courses_note,
			),
			(self.r2022, self.r2026, today(), "Rejoined after break", "Bridge: Maths I"),
		)

	def test_change_regulation_validations(self):
		student = make_student("RegBad", COLLEGE, batch="2023")
		enroll(student, self.program, "2023")
		draft = make_regulation("R-BAD-DRAFT", COLLEGE, [self.program], "2026", status="Draft").name
		with self.assertRaises(frappe.ValidationError):
			change_regulation(student.name, draft, "reason")
		with self.assertRaises(frappe.ValidationError):
			change_regulation(student.name, self.r2026, " ")
		with self.assertRaises(frappe.ValidationError):
			change_regulation(student.name, self.r2022, "same")

	def test_effective_regulation_cannot_be_edited(self):
		regulation = frappe.get_doc("Regulation", self.r2022)
		regulation.notes = "tampered"
		with self.assertRaises(frappe.ValidationError):
			regulation.save()
		regulation = frappe.get_doc("Regulation", self.r2022)
		regulation.append("programs", {"program": self.other_program})
		with self.assertRaises(frappe.ValidationError):
			regulation.save()

	def test_change_regulation_respects_company_user_permission(self):
		student = make_student("RegOtherCollege", OTHER_COLLEGE, batch="2023")
		frappe.set_user(DEAN)
		with self.assertRaises(frappe.PermissionError):
			change_regulation(student.name, self.r2026, "rejoined")

	def test_change_regulation_requires_program_coverage(self):
		student = make_student("RegWrongProgram", COLLEGE, batch="2023")
		enroll(student, self.other_program, "2023")
		with self.assertRaises(frappe.ValidationError):
			change_regulation(student.name, self.r2026, "rejoined")

	def test_retired_cannot_be_reinstated(self):
		regulation = make_regulation("R-TERMINAL", COLLEGE, [self.scratch_program], "2023")
		regulation.status = "Retired"
		regulation.save()
		regulation.status = "Effective"
		with self.assertRaises(frappe.ValidationError):
			regulation.save()

	def test_effective_and_retired_cannot_be_deleted(self):
		regulation = make_regulation("R-NODELETE", COLLEGE, [self.scratch_program], "2023")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Regulation", regulation.name)
		regulation.status = "Retired"
		regulation.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Regulation", regulation.name)

	def test_get_regulation_of_missing_student(self):
		with self.assertRaises(frappe.DoesNotExistError):
			get_regulation("EDU-STU-MISSING")

	def test_effective_regulation_can_be_retired(self):
		regulation = make_regulation("R-RETIRE", COLLEGE, [self.scratch_program], "2023")
		regulation.status = "Retired"
		regulation.save()
		self.assertEqual(frappe.db.get_value("Regulation", regulation.name, "status"), "Retired")

	def test_draft_regulation_is_editable(self):
		regulation = make_regulation("R-DRAFT-EDIT", COLLEGE, [self.scratch_program], "2023", status="Draft")
		regulation.notes = "fine"
		regulation.save()

	def test_amend_creates_draft_version_and_retires_previous_when_effective(self):
		original = make_regulation("R-AMEND", COLLEGE, [self.scratch_program], "2023", notes="v1")
		new_name = amend_as_new_version(original.name)
		self.assertEqual(new_name, "R-AMEND-V2-RTC")
		new = frappe.get_doc("Regulation", new_name)
		self.assertEqual((new.status, new.previous_version, new.notes), ("Draft", original.name, "v1"))
		self.assertEqual([r.program for r in new.programs], [self.scratch_program])
		self.assertEqual(next_version_code("R-AMEND-V2", COLLEGE), "R-AMEND-V3")
		new.notes = "v2"
		new.status = "Effective"
		new.save()
		self.assertEqual(frappe.db.get_value("Regulation", original.name, "status"), "Retired")

	def test_amend_rejects_draft(self):
		draft = make_regulation("R-AMEND-DRAFT", COLLEGE, [self.scratch_program], "2023", status="Draft")
		with self.assertRaises(frappe.ValidationError):
			amend_as_new_version(draft.name)

	def test_get_rule(self):
		student = make_student("RegRule", COLLEGE, batch="2023")
		enroll(student, self.program, "2023")
		with self.assertRaises(frappe.ValidationError):
			get_rule(student.name, RULE_DOCTYPE)  # none defined yet
		rule = make_rule(self.r2022, self.program, "attendance")
		make_rule(self.r2026, self.program, "attendance")
		self.assertEqual(get_rule(student.name, RULE_DOCTYPE).name, rule.name)
		other = make_rule(self.r2022, self.other_program, "grading")
		with self.assertRaises(frappe.ValidationError):
			get_rule(student.name, RULE_DOCTYPE)  # ambiguous
		self.assertEqual(get_rule(student.name, RULE_DOCTYPE, qualifying_exam="grading").name, other.name)

	def test_get_rule_without_regulation_or_regulation_field(self):
		student = make_student("RegNoRule", COLLEGE)
		with self.assertRaises(frappe.ValidationError):
			get_rule(student.name, "Program")
