"""L-01 unit tests (M05-09): the pure lifecycle rules - transition checks and the status a migrated student gets."""

from datetime import date

from frappe.tests import UnitTestCase

from campus.student_services import lifecycle_rules as rules

PERMITTED = {(rules.NEW, rules.ACTIVE), (rules.ACTIVE, rules.ON_BREAK), (rules.ON_BREAK, rules.ACTIVE)}


class TestTransitionRefusal(UnitTestCase):
	def test_a_permitted_transition_on_or_after_the_last_change_passes(self):
		self.assertIsNone(rules.refusal(PERMITTED, rules.ACTIVE, rules.ON_BREAK, date(2026, 6, 1), date(2026, 6, 1)))
		self.assertIsNone(rules.refusal(PERMITTED, rules.ACTIVE, rules.ON_BREAK, date(2026, 6, 2), date(2026, 6, 1)))

	def test_the_first_status_of_a_record_has_no_earlier_date(self):
		self.assertIsNone(rules.refusal(PERMITTED, None, rules.ACTIVE, date(2026, 6, 1), None))
		self.assertIsNone(rules.refusal(PERMITTED, rules.NEW, rules.ACTIVE, date(2026, 6, 1), None))

	def test_an_unknown_status_is_refused(self):
		self.assertEqual(rules.refusal(PERMITTED, rules.ACTIVE, "Detained", date(2026, 6, 1), None), rules.UNKNOWN_STATUS)
		self.assertEqual(rules.refusal(PERMITTED, rules.ACTIVE, "Applicant", date(2026, 6, 1), None), rules.UNKNOWN_STATUS)

	def test_a_move_the_table_does_not_list_is_refused(self):
		self.assertEqual(rules.refusal(PERMITTED, rules.ACTIVE, rules.GRADUATED, date(2026, 6, 1), None), rules.NOT_PERMITTED)
		self.assertEqual(rules.refusal(PERMITTED, rules.NEW, rules.ON_BREAK, date(2026, 6, 1), None), rules.NOT_PERMITTED)

	def test_staying_in_the_same_status_is_refused(self):
		self.assertEqual(rules.refusal(PERMITTED | {(rules.ACTIVE, rules.ACTIVE)}, rules.ACTIVE, rules.ACTIVE, date(2026, 6, 1), None), rules.SAME_STATUS)

	def test_an_effective_date_before_the_last_change_is_refused(self):
		self.assertEqual(
			rules.refusal(PERMITTED, rules.ACTIVE, rules.ON_BREAK, date(2026, 5, 31), date(2026, 6, 1)), rules.BEFORE_LATEST
		)

	def test_the_default_graph_covers_every_status_and_uses_only_known_ones(self):
		reached = {to for _from, to in rules.DEFAULT_TRANSITIONS}
		self.assertEqual(reached, set(rules.STATUSES))
		self.assertTrue(all(f in rules.STATUSES or f == rules.NEW for f, _to in rules.DEFAULT_TRANSITIONS))
		self.assertEqual(len(rules.DEFAULT_TRANSITIONS), len(set(rules.DEFAULT_TRANSITIONS)))

	def test_the_default_graph_has_the_flows_of_the_existing_records(self):
		for move in (
			(rules.NEW, rules.ADMITTED), (rules.ADMITTED, rules.JOINED), (rules.JOINED, rules.ACTIVE),
			(rules.ACTIVE, rules.ON_BREAK), (rules.ON_BREAK, rules.ACTIVE), (rules.ACTIVE, rules.WITHDRAWN),
			(rules.ACTIVE, rules.CANCELLED), (rules.ACTIVE, rules.STUDY_COMPLETED),
			(rules.STUDY_COMPLETED, rules.AWARD_ELIGIBLE), (rules.AWARD_ELIGIBLE, rules.GRADUATED),
			(rules.GRADUATED, rules.ALUMNI), (rules.DISCONTINUED, rules.READMITTED), (rules.READMITTED, rules.ACTIVE),
		):  # fmt: skip
			self.assertIn(move, rules.DEFAULT_TRANSITIONS)
		self.assertNotIn((rules.ACTIVE, rules.GRADUATED), rules.DEFAULT_TRANSITIONS)
		self.assertNotIn((rules.CANCELLED, rules.ACTIVE), rules.DEFAULT_TRANSITIONS)

	def test_every_on_roll_status_can_withdraw_by_the_default_graph(self):
		for status in rules.ON_ROLL:
			self.assertIn((status, rules.WITHDRAWN), rules.DEFAULT_TRANSITIONS, status)
		self.assertNotIn(rules.ADMITTED, rules.ON_ROLL)  # not joined yet: an Admission Cancellation, not a TC
		self.assertNotIn(rules.READMITTED, rules.ON_ROLL)

	def test_applicant_is_not_a_student_status(self):
		self.assertNotIn("Applicant", rules.STATUSES)


class TestMigratedStatus(UnitTestCase):
	def test_a_cancelled_admission_wins(self):
		self.assertEqual(rules.migrated_status("Active", cancelled=True, left=True, convocation=True), rules.CANCELLED)

	def test_a_listed_graduate_is_award_eligible_even_with_a_tc(self):
		self.assertEqual(rules.migrated_status("Discontinued", left=True, convocation=True), rules.AWARD_ELIGIBLE)

	def test_completed_becomes_study_completed(self):
		self.assertEqual(rules.migrated_status("Completed", left=True), rules.STUDY_COMPLETED)

	def test_a_transfer_certificate_means_withdrawn(self):
		self.assertEqual(rules.migrated_status("Discontinued", left=True), rules.WITHDRAWN)
		self.assertEqual(rules.migrated_status("Active", left=True), rules.WITHDRAWN)

	def test_an_open_break_or_the_old_break_status_means_on_break(self):
		self.assertEqual(rules.migrated_status("Break of Study"), rules.ON_BREAK)
		self.assertEqual(rules.migrated_status("Active", open_break=True), rules.ON_BREAK)

	def test_discontinued_without_a_tc_stays_discontinued(self):
		self.assertEqual(rules.migrated_status("Discontinued"), rules.DISCONTINUED)

	def test_detained_long_absent_and_blank_are_active(self):
		for old in ("Detained", "Long Absent", None, "", "Active"):
			self.assertEqual(rules.migrated_status(old), rules.ACTIVE, old)

	def test_a_value_that_is_already_a_lifecycle_status_is_kept(self):
		self.assertEqual(rules.migrated_status(rules.GRADUATED), rules.GRADUATED)
