"""P1-T12 tests (M03-01): curriculum credits against the regulation rule, locking, versions, print."""

import frappe

from campus.curriculum.doctype.curriculum.curriculum import create_new_version
from campus.curriculum.setup import COURSE_CATEGORIES, seed_course_categories
from campus.tests.factories import make_company, make_user
from campus.tests.test_regulation import make_program, make_regulation, make_year
from campus.tests.utils import CampusTestCase

COLLEGE = "Curriculum Test College"
PROGRAM = "Curriculum Test BE"
ABBR = "CTB"
DEAN = "curriculum-dean@example.com"
PLAIN = "curriculum-plain@example.com"
COURSES = [f"CT Course {n}" for n in range(1, 6)]


def clear_previous_run():
	frappe.db.delete("Elective Group", {"curriculum": ["like", f"{ABBR}-%"]})
	for name in frappe.get_all("Curriculum", filters={"program": PROGRAM}, pluck="name"):
		frappe.db.delete("Curriculum Course", {"parent": name})
		frappe.db.delete("Category Credit Requirement", {"parent": name})
		frappe.db.delete("Curriculum", {"name": name})
	frappe.db.delete("Curriculum Rule", {"regulation": ["like", "%-CTC"]})


def make_course(name):
	if not frappe.db.exists("Course", name):
		frappe.get_doc({"doctype": "Course", "course_name": name, "oc_company": COLLEGE}).insert()
	return name


def row(course, semester=1, category="PCC", l=3, t=0, p=0, **extra):
	return {
		"semester": semester, "course": course, "category": category,
		"lecture_periods": l, "tutorial_periods": t, "practical_periods": p, **extra,
	}  # fmt: skip


def in_range_rows(total=167):
	"""A 3-0-2 course (4 credits) plus an overridden block that brings the total to `total`."""
	return [
		row(COURSES[0], l=3, p=2),
		row(COURSES[1], semester=2, credits_override=1, credits=total - 4, l=0),
	]


class TestCurriculum(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		clear_previous_run()
		make_company(COLLEGE, "CTC")
		make_year("2022")
		program = make_program(PROGRAM, COLLEGE)
		frappe.db.set_value("Program", program, {"program_abbreviation": ABBR, "oc_total_semesters": 8})
		cls.regulation = make_regulation("R2022", COLLEGE, [PROGRAM], "2022").name
		cls.rule = frappe.get_doc(
			{
				"doctype": "Curriculum Rule", "regulation": cls.regulation,
				"lecture_credit_per_period": 1, "tutorial_credit_per_period": 1, "practical_credit_per_period": 0.5,
				"min_total_credits": 165, "max_total_credits": 170,
			}
		).insert()  # fmt: skip
		for course in COURSES:
			make_course(course)
		make_user(DEAN, [COLLEGE])
		frappe.get_doc("User", DEAN).add_roles("Dean Academics")
		make_user(PLAIN, [COLLEGE])
		frappe.get_doc("User", PLAIN).add_roles("System Manager")  # may edit, but is not the Dean

	def setUp(self):
		frappe.set_user("Administrator")
		clear_previous_run()
		frappe.db.delete("Curriculum Rule", {"regulation": self.regulation})
		self.rule = frappe.get_doc(self.rule.as_dict(no_nulls=True) | {"__islocal": 1, "name": None}).insert()

	def tearDown(self):
		frappe.set_user("Administrator")

	def make(self, rows=None, requirements=None, status="Draft", **extra):
		return frappe.get_doc(
			{
				"doctype": "Curriculum", "program": PROGRAM, "regulation": self.regulation,
				"status": status, "courses": rows if rows is not None else in_range_rows(),
				"category_requirements": requirements or [], **extra,
			}
		).insert()  # fmt: skip

	def advance(self, doc, status):
		doc.status = status
		doc.save()
		return doc

	def assert_save_fails(self, doc, pattern):
		"""A rejected save leaves the in-memory timestamp ahead of the database; restore it."""
		with self.assertRaisesRegex(frappe.ValidationError, pattern):
			doc.save()
		doc.modified = frappe.db.get_value(doc.doctype, doc.name, "modified")

	def make_effective(self, **kwargs):
		doc = self.make(**kwargs)
		self.advance(doc, "Approved")
		return self.advance(doc, "Effective")

	# seed and fields
	def test_categories_seeded_idempotently_with_counting_flags(self):
		seed_course_categories()
		seed_course_categories()
		self.assertEqual(frappe.db.count("Course Category", {"name": ["in", list(COURSE_CATEGORIES)]}), 10)
		for code in ("MC", "AC", "VAC"):
			self.assertEqual(frappe.db.get_value("Course Category", code, "counts_toward_credits"), 0)
		for code in ("HSMC", "BSC", "ESC", "PCC", "PEC", "OEC", "EEC"):
			self.assertEqual(frappe.db.get_value("Course Category", code, "counts_toward_credits"), 1)

	def test_program_and_course_custom_fields_exist(self):
		for fieldname in ("oc_level", "oc_degree", "oc_discipline", "oc_duration_years", "oc_total_semesters",
				"oc_sanctioned_intake", "oc_lateral_entry_allowed", "oc_nba_accredited_until"):  # fmt: skip
			self.assertTrue(frappe.get_meta("Program").has_field(fieldname), fieldname)
		for fieldname in ("oc_course_code", "oc_course_type", "oc_lecture_hours", "oc_tutorial_hours",
				"oc_practical_hours", "oc_credits"):  # fmt: skip
			self.assertTrue(frappe.get_meta("Course").has_field(fieldname), fieldname)

	# credits
	def test_three_zero_two_derives_four_credits_under_r2022(self):
		doc = self.make(in_range_rows())
		self.assertEqual(doc.courses[0].credits, 4)

	def test_override_keeps_manual_credits(self):
		doc = self.make(in_range_rows())
		self.assertEqual(doc.courses[1].credits, 163)

	def test_rates_are_read_from_the_rule_record(self):
		frappe.db.set_value("Curriculum Rule", self.rule.name, "practical_credit_per_period", 1)
		self.assertEqual(self.make([row(COURSES[0], l=3, p=2)]).courses[0].credits, 5)

	def test_total_and_category_credits_exclude_uncounted_categories(self):
		doc = self.make(
			[row(COURSES[0], l=3, p=2), row(COURSES[1], category="BSC", l=3, t=1),
			 row(COURSES[2], category="AC", l=3)],
			requirements=[{"category": "PCC", "min_credits": 2}, {"category": "AC", "min_credits": 1}],
		)  # fmt: skip
		self.assertEqual(doc.total_credits, 8)  # PCC 4 + BSC 4; the audit course earns 3 but is not counted
		self.assertEqual([r.actual_credits for r in doc.category_requirements], [4, 3])

	def test_without_a_rule_credits_stay_manual_and_range_is_skipped(self):
		frappe.db.delete("Curriculum Rule", {"regulation": self.regulation})
		doc = self.make([row(COURSES[0], l=3, p=2, credits=9)])
		self.assertEqual(doc.courses[0].credits, 9)
		self.assertEqual(doc.total_credits, 9)
		doc.status = "Approved"
		self.assert_save_fails(doc, "no Curriculum Rule")  # only a Draft may lack a rule

	# range and minimums
	def test_range_165_to_170_enforced_once_approved(self):
		for total in (165, 167, 170):
			frappe.db.delete("Curriculum", {"program": PROGRAM})
			frappe.db.delete(
				"Curriculum Course", {"parenttype": "Curriculum", "parent": ["like", f"{ABBR}-%"]}
			)
			self.advance(self.make(in_range_rows(total)), "Approved")
		for total, word in ((164, "below"), (171, "above")):
			frappe.db.delete("Curriculum", {"program": PROGRAM})
			doc = self.make(in_range_rows(total))  # a Draft is allowed out of range
			doc.status = "Approved"
			with self.assertRaisesRegex(frappe.ValidationError, word):
				doc.save()
			frappe.db.delete("Curriculum", {"program": PROGRAM})

	def test_draft_out_of_range_only_warns(self):
		frappe.clear_messages()
		doc = self.make(in_range_rows(100))
		self.assertEqual(doc.status, "Draft")
		self.assertTrue(any("below" in message.get("message", "") for message in frappe.get_message_log()))

	def test_category_shortfalls_listed_when_approving(self):
		doc = self.make(
			in_range_rows(167),
			requirements=[{"category": "PCC", "min_credits": 200}, {"category": "HSMC", "min_credits": 10}],
		)
		doc.status = "Approved"
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save()
		self.assertIn("PCC", str(ctx.exception))
		self.assertIn("HSMC", str(ctx.exception))

	def test_max_courses_per_semester(self):
		frappe.db.set_value("Curriculum Rule", self.rule.name, "max_courses_per_semester", 1)
		doc = self.make([row(COURSES[0], l=3, p=2, credits_override=1, credits=100),
			row(COURSES[1], credits_override=1, credits=67)])  # fmt: skip
		doc.status = "Approved"
		self.assert_save_fails(doc, "maximum is 1")

	# course rows
	def test_course_appears_once_unless_repeatable(self):
		with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
			self.make([row(COURSES[0]), row(COURSES[0], semester=2)])
		with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
			self.make([row(COURSES[0]), row(COURSES[0], semester=2, repeatable=1)])
		doc = self.make([row(COURSES[0], repeatable=1), row(COURSES[0], semester=2, repeatable=1)])
		self.assertEqual(len(doc.courses), 2)

	def test_prerequisites_must_be_courses(self):
		with self.assertRaisesRegex(frappe.ValidationError, "not a Course"):
			self.make([row(COURSES[0], prerequisites="No Such Course")])
		with self.assertRaisesRegex(frappe.ValidationError, "own prerequisite"):
			self.make([row(COURSES[0], prerequisites=COURSES[0])])
		self.make([row(COURSES[1], semester=2, prerequisites=f"{COURSES[0]}, ")])

	def test_semester_outside_programme_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "outside the programme"):
			self.make([row(COURSES[0], semester=9)])

	def test_regulation_must_cover_the_program(self):
		other = make_program("Curriculum Test Other", COLLEGE)
		with self.assertRaisesRegex(frappe.ValidationError, "does not cover"):
			frappe.get_doc({"doctype": "Curriculum", "program": other, "regulation": self.regulation,
				"courses": [row(COURSES[0])]}).insert()  # fmt: skip

	def test_new_curriculum_without_a_status_is_a_draft(self):
		doc = frappe.get_doc({"doctype": "Curriculum", "program": PROGRAM, "regulation": self.regulation,
			"courses": in_range_rows(100)}).insert()  # fmt: skip
		self.assertEqual(doc.status, "Draft")

	def test_name_and_duplicate_version(self):
		doc = self.make()
		self.assertEqual(doc.name, f"{ABBR}-{self.regulation}-v1")
		with self.assertRaisesRegex(frappe.ValidationError, "already exists"):
			self.make()

	# elective groups
	def make_group(self, curriculum, semester=1, name="Basket"):
		return frappe.get_doc({"doctype": "Elective Group", "curriculum": curriculum.name, "semester": semester,
			"group_name": name, "choose_n": 1, "seat_cap_per_course": 60}).insert()  # fmt: skip

	def test_elective_group_must_match_curriculum_and_semester(self):
		doc = self.make()
		group = self.make_group(doc, semester=1)
		doc.append(
			"courses",
			row(
				COURSES[2],
				semester=2,
				is_elective=1,
				elective_group=group.name,
				credits_override=1,
				credits=0,
			),
		)
		self.assert_save_fails(doc, "another curriculum or semester")
		doc.courses[-1].semester = 1
		doc.courses[-1].is_elective = 0
		self.assert_save_fails(doc, "only an elective")

	# lock and versions
	def test_effective_curriculum_is_read_only(self):
		doc = self.make_effective()
		doc.courses[0].lecture_periods = 4
		self.assert_save_fails(doc, "cannot be edited")
		doc.reload()
		doc.append("courses", row(COURSES[3], semester=3))
		self.assert_save_fails(doc, "cannot be edited")
		doc.reload()
		doc.status = "Draft"
		self.assert_save_fails(doc, "cannot be edited")
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be deleted"):
			frappe.delete_doc("Curriculum", doc.name)

	def test_effective_curriculum_locks_its_elective_groups(self):
		doc = self.make()
		group = self.make_group(doc)
		self.advance(doc, "Approved")
		self.advance(doc, "Effective")
		group.choose_n = 2
		self.assert_save_fails(group, "locked")

	def test_status_flow_and_dean_only_effective(self):
		doc = self.make()
		doc.status = "Effective"
		self.assert_save_fails(doc, "cannot move")
		doc.status = "Approved"
		doc.save()
		frappe.set_user(PLAIN)
		doc.status = "Effective"
		self.assert_save_fails(doc, "Dean Academics")
		frappe.set_user(DEAN)
		doc.save()
		self.assertEqual(frappe.db.get_value("Curriculum", doc.name, "status"), "Effective")

	def test_new_version_copies_into_a_draft_and_remaps_groups(self):
		doc = self.make()
		group = self.make_group(doc)
		doc.append(
			"courses",
			row(COURSES[2], is_elective=1, elective_group=group.name, credits_override=1, credits=0),
		)
		doc.save()
		self.advance(doc, "Approved")
		self.advance(doc, "Effective")
		new = frappe.get_doc("Curriculum", create_new_version(doc.name))
		self.assertEqual((new.version, new.status, new.previous_version), (2, "Draft", doc.name))
		self.assertEqual(new.name, f"{ABBR}-{self.regulation}-v2")
		self.assertEqual([r.course for r in new.courses], [r.course for r in doc.courses])
		self.assertEqual(new.total_credits, doc.total_credits)
		copied = new.courses[-1].elective_group
		self.assertEqual(copied, f"{new.name}-S1-Basket")
		self.assertEqual(frappe.db.get_value("Elective Group", copied, "curriculum"), new.name)
		new.courses[0].lecture_periods = 4  # the Draft is editable
		new.save()

	def test_only_approved_or_effective_can_be_versioned(self):
		doc = self.make()
		with self.assertRaisesRegex(frappe.ValidationError, "Only an Approved or Effective"):
			create_new_version(doc.name)

	def test_new_effective_version_supersedes_the_old_one(self):
		v1 = self.make_effective()
		v2 = frappe.get_doc("Curriculum", create_new_version(v1.name))
		self.advance(v2, "Approved")
		self.advance(v2, "Effective")
		statuses = frappe.get_all(
			"Curriculum", filters={"program": PROGRAM}, fields=["version", "status"], order_by="version"
		)
		self.assertEqual([(s.version, s.status) for s in statuses], [(1, "Superseded"), (2, "Effective")])
		v1.reload()
		v1.courses[0].lecture_periods = 1
		self.assert_save_fails(v1, "cannot be edited")

	def test_only_one_effective_per_program_and_regulation(self):
		v1 = self.make_effective()
		v2 = frappe.get_doc("Curriculum", create_new_version(v1.name))
		self.advance(v2, "Approved")
		self.advance(v2, "Effective")
		v3 = frappe.get_doc("Curriculum", create_new_version(v2.name))
		self.advance(v3, "Approved")
		self.advance(v3, "Effective")
		effective = frappe.get_all("Curriculum", {"program": PROGRAM, "status": "Effective"}, pluck="name")
		self.assertEqual(effective, [v3.name])
		self.assertEqual(frappe.db.get_value("Curriculum", v1.name, "status"), "Superseded")
		self.assertEqual(frappe.db.get_value("Curriculum", v2.name, "status"), "Superseded")

	def test_older_version_cannot_become_effective_over_a_newer_one(self):
		v1 = self.make()
		self.advance(v1, "Approved")
		v2 = frappe.get_doc("Curriculum", create_new_version(v1.name))
		self.advance(v2, "Approved")
		self.advance(v2, "Effective")
		v1.reload()
		v1.status = "Effective"
		self.assert_save_fails(v1, "newer version")
		self.assertEqual(frappe.db.get_value("Curriculum", v2.name, "status"), "Effective")

	def test_cannot_insert_directly_as_effective(self):
		with self.assertRaisesRegex(frappe.ValidationError, "cannot move"):
			self.make(status="Effective")

	def test_approving_without_a_rule_is_rejected_but_draft_is_fine(self):
		frappe.db.delete("Curriculum Rule", {"regulation": self.regulation})
		doc = self.make(in_range_rows(167))
		self.advance(doc, "Draft")
		doc.status = "Approved"
		self.assert_save_fails(doc, "no Curriculum Rule")

	# print
	def test_structure_print_renders_semesters_and_category_totals(self):
		doc = self.make(
			[row(COURSES[0], l=3, p=2), row(COURSES[1], semester=2, category="BSC", l=3, t=1),
			 row(COURSES[2], semester=2, category="AC", l=2)],
			requirements=[{"category": "PCC", "min_credits": 2}],
		)  # fmt: skip
		html = frappe.get_print("Curriculum", doc.name, "Curriculum Structure")
		for text in (
			"Semester 1",
			"Semester 2",
			COURSES[0],
			"Semester total",
			"Category-wise credits",
			"PCC",
			"BSC",
			"AC",
		):
			self.assertIn(text, html)
		self.assertIn("Total credits (counted)", html)
		self.assertRegex(html, r"Total credits \(counted\)</th>\s*<th class=\"text-right\">8")

	# rule record
	def test_get_rule_style_lookup_is_one_rule_per_regulation(self):
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({"doctype": "Curriculum Rule", "regulation": self.regulation}).insert()
