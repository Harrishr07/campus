"""X-03 unit tests (M05-15): the pure completion rules - credits per category and in total, mandatory courses, credit
recognitions counted once, the degree authority's document cover and the alumni date."""

from datetime import date

from frappe.tests import UnitTestCase

from campus.examinations import completion_rules as rules

CURRICULUM = [
	{"course": "C1", "category": "PCC", "credits": 4, "is_elective": 0},
	{"course": "C2", "category": "PCC", "credits": 4, "is_elective": 0},
	{"course": "E1", "category": "PEC", "credits": 3, "is_elective": 1},
	{"course": "E2", "category": "PEC", "credits": 3, "is_elective": 1},
	{"course": "M1", "category": "MC", "credits": 0, "is_elective": 0},
]
MINIMUMS = {"PCC": 8, "PEC": 3}
COUNTING = {"PCC": 1, "PEC": 1, "MC": 0}


def evaluate(passed, recognised=None, total=11, specialisations=()):
	return rules.evaluate(CURRICULUM, MINIMUMS, COUNTING, total, passed, recognised or {}, specialisations)


def row(outcome, category):
	return next(r for r in outcome["categories"] if r["category"] == category)


class TestEvaluate(UnitTestCase):
	def test_every_requirement_met_is_complete(self):
		outcome = evaluate({"C1": 4, "C2": 4, "E1": 3, "M1": 0})
		self.assertEqual(outcome["result"], rules.COMPLETE)
		self.assertEqual(outcome["missing_courses"], [])
		self.assertEqual((row(outcome, "PCC")["earned"], row(outcome, "PEC")["earned"]), (8, 3))
		self.assertEqual(
			(row(outcome, rules.TOTAL)["required"], row(outcome, rules.TOTAL)["earned"]), (11, 11)
		)
		self.assertTrue(all(r["status"] == rules.MET for r in outcome["categories"]))

	def test_a_category_short_of_its_minimum_is_incomplete(self):
		outcome = evaluate({"C1": 4, "C2": 4, "M1": 0}, total=0)
		self.assertEqual(outcome["result"], rules.INCOMPLETE)
		self.assertEqual((row(outcome, "PEC")["earned"], row(outcome, "PEC")["status"]), (0, rules.SHORT))
		self.assertEqual(outcome["missing_courses"], [])  # electives are not mandatory courses

	def test_the_total_counts_only_categories_that_count_toward_credits(self):
		outcome = evaluate({"C1": 4, "C2": 4, "E1": 3, "M1": 0}, total=12)
		self.assertEqual(
			(row(outcome, rules.TOTAL)["earned"], row(outcome, rules.TOTAL)["status"]), (11, rules.SHORT)
		)
		self.assertEqual(outcome["result"], rules.INCOMPLETE)

	def test_no_total_on_record_is_not_checked(self):
		outcome = evaluate({"C1": 4, "C2": 4, "E1": 3, "M1": 0}, total=0)
		self.assertNotIn(rules.TOTAL, [r["category"] for r in outcome["categories"]])
		self.assertEqual(outcome["result"], rules.COMPLETE)

	def test_a_mandatory_course_not_passed_is_missing_even_with_the_credits(self):
		outcome = evaluate(
			{"C1": 4, "C2": 4, "E1": 3, "E2": 3}, total=0
		)  # the non-credit mandatory course M1 not passed
		self.assertEqual(outcome["missing_courses"], ["M1"])
		self.assertEqual(outcome["result"], rules.INCOMPLETE)

	def test_a_recognised_course_satisfies_its_requirement(self):
		outcome = evaluate({"C1": 4, "E1": 3, "M1": 0}, recognised={"C2": 4})
		self.assertEqual(outcome["result"], rules.COMPLETE)
		self.assertEqual(row(outcome, "PCC")["earned"], 8)

	def test_a_course_passed_and_recognised_counts_once(self):
		outcome = evaluate({"C1": 4, "C2": 4, "E1": 3, "M1": 0}, recognised={"C2": 4, "E1": 3})
		self.assertEqual((row(outcome, "PCC")["earned"], row(outcome, "PEC")["earned"]), (8, 3))
		self.assertEqual(row(outcome, rules.TOTAL)["earned"], 11)

	def test_a_waiver_without_credit_clears_the_course_but_earns_nothing(self):
		outcome = evaluate({"C1": 4, "E1": 3, "M1": 0}, recognised={"C2": 0}, total=0)
		self.assertEqual(outcome["missing_courses"], [])
		self.assertEqual((row(outcome, "PCC")["earned"], row(outcome, "PCC")["status"]), (4, rules.SHORT))

	def test_recognised_credits_never_exceed_the_curriculum_credits(self):
		outcome = evaluate({"C1": 4, "E1": 3, "M1": 0}, recognised={"C2": 10})
		self.assertEqual(row(outcome, "PCC")["earned"], 8)

	def test_a_course_outside_the_curriculum_earns_nothing(self):
		outcome = evaluate({"C1": 4, "C2": 4, "X9": 30, "M1": 0}, total=0)
		self.assertEqual(row(outcome, "PEC")["earned"], 0)
		self.assertEqual(outcome["result"], rules.INCOMPLETE)

	def test_a_specialisation_is_shown_and_does_not_block_the_degree(self):
		outcome = evaluate({"C1": 4, "C2": 4, "E1": 3, "M1": 0}, specialisations=[("Honours", 18, 9)])
		honours = row(outcome, "Honours")
		self.assertEqual(
			(honours["required"], honours["earned"], honours["status"]), (18, 9, rules.NOT_REQUIRED)
		)
		self.assertEqual(outcome["result"], rules.COMPLETE)

	def test_no_curriculum_is_incomplete(self):
		outcome = rules.evaluate([], {}, {}, 0, {"C1": 4}, {}, ())
		self.assertEqual(outcome["result"], rules.INCOMPLETE)

	def test_the_fingerprint_follows_the_outcome(self):
		first = rules.fingerprint("CUR-1", evaluate({"C1": 4, "C2": 4, "E1": 3, "M1": 0}))
		self.assertEqual(first, rules.fingerprint("CUR-1", evaluate({"C1": 4, "C2": 4, "E1": 3, "M1": 0})))
		self.assertNotEqual(first, rules.fingerprint("CUR-1", evaluate({"C1": 4, "C2": 4, "M1": 0})))
		self.assertNotEqual(first, rules.fingerprint("CUR-2", evaluate({"C1": 4, "C2": 4, "E1": 3, "M1": 0})))


class TestAuthorityCover(UnitTestCase):
	def documents(self, *rows):
		return [{"name": n, "valid_from": date(*f), "valid_to": date(*t), "status": s} for n, f, t, s in rows]

	def test_an_active_document_covering_the_date_is_found(self):
		docs = self.documents(("A", (2024, 1, 1), (2026, 12, 31), "Active"))
		self.assertEqual(rules.covering_document(docs, date(2026, 10, 22))["name"], "A")

	def test_a_document_that_ended_before_the_date_does_not_cover_it(self):
		docs = self.documents(("A", (2020, 1, 1), (2025, 12, 31), "Expired"))
		self.assertIsNone(rules.covering_document(docs, date(2026, 10, 22)))

	def test_a_superseded_document_does_not_cover(self):
		docs = self.documents(("A", (2024, 1, 1), (2026, 12, 31), "Superseded"))
		self.assertIsNone(rules.covering_document(docs, date(2026, 10, 22)))

	def test_a_document_not_yet_valid_does_not_cover(self):
		docs = self.documents(("A", (2027, 1, 1), (2029, 12, 31), "Active"))
		self.assertIsNone(rules.covering_document(docs, date(2026, 10, 22)))


class TestAlumniDate(UnitTestCase):
	def test_after_days_counts_from_the_graduation_date(self):
		self.assertEqual(rules.alumni_date(date(2026, 9, 1), 30), date(2026, 10, 1))
		self.assertEqual(rules.alumni_date(date(2026, 9, 1), 0), date(2026, 9, 1))

	def test_due_only_once_the_date_is_reached(self):
		self.assertTrue(rules.alumni_due(date(2026, 9, 1), 30, date(2026, 10, 1)))
		self.assertFalse(rules.alumni_due(date(2026, 9, 1), 30, date(2026, 9, 30)))
