"""M06-05, M05-03 integration tests (P2-T12): rule seeds for AU-R2021, R2022 and R2026 are idempotent, rule
records lock once their regulation is Effective, and the Grading Scheme refuses invalid grading methods."""

import frappe

from campus.examinations.seed import seed_regulation
from campus.tests.factories import make_company
from campus.tests.test_regulation import make_program, make_regulation, make_year
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR = "Exam Rule Test College", "ERTC"
PROGRAM = "Exam Rule Test BE"
CODES = ("AU-R2021", "R2022", "R2026")
RULE_DOCTYPES = ("Grading Scheme", "Exam Rule Set", "Classification Rule")


def clear_rules():
	for doctype in RULE_DOCTYPES:
		frappe.db.delete(doctype, {"regulation": ["like", f"%-{ABBR}"]})


class TestExamRuleRecords(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		clear_rules()
		make_company(COLLEGE, ABBR)
		for year in ("2021", "2022", "2026"):
			make_year(year)
		make_program(PROGRAM, COLLEGE)
		cls.regs = {}
		for code, year in zip(CODES, ("2021", "2022", "2026"), strict=True):
			cls.regs[code] = make_regulation(f"T12-{code}", COLLEGE, [PROGRAM], year).name
			seed_regulation(cls.regs[code], code)
		cls.draft = make_regulation("T12-DRAFT", COLLEGE, [PROGRAM], "2022", status="Draft").name
		seed_regulation(cls.draft, "R2022")

	def setUp(self):
		frappe.db.savepoint("exam_rule_test")
		self.addCleanup(frappe.db.rollback, save_point="exam_rule_test")

	def test_each_regulation_gets_one_record_of_each_rule(self):
		for code, regulation in self.regs.items():
			for doctype in RULE_DOCTYPES:
				with self.subTest(code=code, doctype=doctype):
					self.assertEqual(frappe.db.count(doctype, {"regulation": regulation}), 1)

	def test_seeding_again_changes_nothing(self):
		before = {
			d: frappe.db.get_value(d, {"regulation": self.regs["R2022"]}, "modified") for d in RULE_DOCTYPES
		}
		seed_regulation(self.regs["R2022"], "R2022")
		for doctype in RULE_DOCTYPES:
			self.assertEqual(frappe.db.count(doctype, {"regulation": self.regs["R2022"]}), 1)
			self.assertEqual(
				frappe.db.get_value(doctype, {"regulation": self.regs["R2022"]}, "modified"), before[doctype]
			)

	def test_seeded_values_differ_by_regulation(self):
		r2022 = frappe.get_doc("Grading Scheme", self.regs["R2022"])
		r2026 = frappe.get_doc("Grading Scheme", self.regs["R2026"])
		self.assertEqual(
			{m.course_type: m.method for m in r2022.methods},
			{"Theory": "Relative Box-Cox", "Theory with Lab": "Relative Box-Cox"},
		)
		self.assertEqual({m.min_cohort for m in r2022.methods}, {30})
		self.assertFalse(r2026.methods)
		self.assertEqual({g.letter: g.grade_point for g in r2026.grades}["B"], 6.5)
		self.assertIn("WC", {c.code for c in r2026.codes})
		self.assertEqual([c.course_category for c in r2022.gpa_excluded_categories], ["MC"])
		rules = frappe.get_doc("Exam Rule Set", self.regs["R2022"])
		self.assertEqual(rules.cia_carry_forward, 1)
		self.assertEqual(
			{
				(t.course_type, t.ese_only_from_attempt, t.ese_only_min_pct)
				for t in rules.types
				if t.course_type == "Theory"
			},
			{("Theory", 3, 50)},
		)
		self.assertEqual(len(frappe.get_doc("Classification Rule", self.regs["AU-R2021"]).classes), 3)

	def test_rule_records_of_an_effective_regulation_cannot_be_edited(self):
		for doctype in RULE_DOCTYPES:
			with self.subTest(doctype=doctype):
				doc = frappe.get_doc(doctype, self.regs["R2026"])
				if doctype == "Exam Rule Set":
					doc.types[0].ese_min_pct = 40
				elif doctype == "Grading Scheme":
					doc.grades[0].grade_point = 9.5
				else:
					doc.classes[0].cgpa_min = 8
				self.assertRaisesRegex(frappe.ValidationError, "cannot be edited", doc.save)

	def test_rule_records_of_an_effective_regulation_cannot_be_deleted(self):
		for doctype in RULE_DOCTYPES:
			with self.subTest(doctype=doctype):
				self.assertRaisesRegex(
					frappe.ValidationError,
					"cannot be deleted",
					frappe.delete_doc,
					doctype,
					self.regs["R2026"],
				)

	def test_rule_records_of_a_draft_regulation_stay_editable(self):
		doc = frappe.get_doc("Exam Rule Set", self.draft)
		doc.types[0].ese_min_pct = 40
		doc.save()
		self.assertEqual(
			frappe.db.get_value("Exam Rule Set Type", {"parent": self.draft, "idx": 1}, "ese_min_pct"), 40
		)

	def test_a_draft_rule_cannot_be_moved_onto_an_effective_regulation(self):
		doc = frappe.get_doc("Classification Rule", self.draft)
		frappe.db.delete("Classification Rule", {"name": self.regs["R2026"]})
		doc.regulation = self.regs["R2026"]
		self.assertRaisesRegex(frappe.ValidationError, "cannot be edited", doc.save)

	def scheme(self):
		return frappe.get_doc("Grading Scheme", self.draft)

	def test_labs_and_projects_cannot_be_graded_relatively(self):
		for course_type in ("Lab", "Project"):
			with self.subTest(course_type=course_type):
				doc = self.scheme()
				doc.append(
					"methods", {"course_type": course_type, "method": "Relative Box-Cox", "min_cohort": 30}
				)
				self.assertRaisesRegex(frappe.ValidationError, "always graded absolutely", doc.save)

	def test_online_table_method_needs_online_grades(self):
		doc = self.scheme()
		doc.append("methods", {"course_type": "Online", "method": "Online Table"})
		self.assertRaisesRegex(frappe.ValidationError, "online course grades", doc.save)
		doc = self.scheme()
		doc.append("methods", {"course_type": "Online", "method": "Online Table"})
		doc.append(
			"online_grades", {"letter": "S", "grade_point": 10, "min_mark": 91, "max_mark": 100, "is_pass": 1}
		)
		doc.append(
			"online_grades", {"letter": "U", "grade_point": 0, "min_mark": 0, "max_mark": 39, "is_pass": 0}
		)
		doc.save()
		self.assertEqual(len(self.scheme().online_grades), 2)

	def test_relative_bounds_must_fall_with_the_grades(self):
		doc = self.scheme()
		doc.grades[1].relative_min_z = 2  # A+ above O's 1.5
		self.assertRaisesRegex(frappe.ValidationError, "must fall", doc.save)

	def test_one_method_per_course_type(self):
		doc = self.scheme()
		doc.append("methods", {"course_type": "Theory", "method": "Absolute"})
		self.assertRaisesRegex(frappe.ValidationError, "one grading method", doc.save)
