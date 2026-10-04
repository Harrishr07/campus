"""M17-03 unit tests: policy selection, level progression state machine, SLA timing, delegation window."""

from datetime import datetime

from frappe.tests import UnitTestCase

from campus.campus_platform import approval_rules as rules


def policy(name, priority=0, company=None, condition=None):
	return {"name": name, "priority": priority, "company": company, "condition": condition}


def always(condition):
	return True


def never(condition):
	return False


class TestSelectPolicy(UnitTestCase):
	def test_no_policies_selects_nothing(self):
		self.assertIsNone(rules.select_policy([], "C1", always))

	def test_blank_condition_matches_without_evaluation(self):
		self.assertEqual(rules.select_policy([policy("P", condition="  ")], "C1", never)["name"], "P")

	def test_condition_decides_between_policies(self):
		policies = [
			policy("Big", priority=10, condition="big"),
			policy("Small", priority=5, condition="small"),
		]
		self.assertEqual(rules.select_policy(policies, "C1", lambda c: c == "big")["name"], "Big")
		self.assertEqual(rules.select_policy(policies, "C1", lambda c: c == "small")["name"], "Small")
		self.assertIsNone(rules.select_policy(policies, "C1", never))

	def test_higher_priority_wins(self):
		policies = [policy("Low", priority=1), policy("High", priority=9)]
		self.assertEqual(rules.select_policy(policies, "C1", always)["name"], "High")

	def test_other_company_policy_is_ignored(self):
		policies = [policy("Other", priority=9, company="C2"), policy("Generic")]
		self.assertEqual(rules.select_policy(policies, "C1", always)["name"], "Generic")

	def test_company_policy_beats_generic_on_equal_priority(self):
		policies = [policy("Generic", priority=3), policy("Own", priority=3, company="C1")]
		self.assertEqual(rules.select_policy(policies, "C1", always)["name"], "Own")

	def test_name_breaks_remaining_ties(self):
		policies = [policy("B"), policy("A")]
		self.assertEqual(rules.select_policy(policies, "C1", always)["name"], "A")


class TestNextState(UnitTestCase):
	def test_reject_ends_at_current_level(self):
		self.assertEqual(rules.next_state(rules.REJECT, 2, 3, 0, 1), (rules.REJECTED, 2))

	def test_return_ends_at_current_level(self):
		self.assertEqual(rules.next_state(rules.RETURN, 1, 3, 0, 1), (rules.RETURNED, 1))

	def test_approve_below_minimum_stays_on_level(self):
		self.assertEqual(rules.next_state(rules.APPROVE, 1, 3, 1, 2), (rules.PENDING, 1))

	def test_approve_meeting_minimum_moves_to_next_level(self):
		self.assertEqual(rules.next_state(rules.APPROVE, 1, 3, 2, 2), (rules.PENDING, 2))

	def test_approve_on_last_level_approves(self):
		self.assertEqual(rules.next_state(rules.APPROVE, 3, 3, 1, 1), (rules.APPROVED, 3))

	def test_blank_or_zero_minimum_means_one(self):
		self.assertEqual(rules.next_state(rules.APPROVE, 1, 2, 1, 0), (rules.PENDING, 2))
		self.assertEqual(rules.next_state(rules.APPROVE, 1, 2, 1, None), (rules.PENDING, 2))

	def test_unknown_action_raises(self):
		with self.assertRaises(ValueError):
			rules.next_state("Escalate", 1, 2, 0, 1)

	def test_comment_required_for_reject_and_return_only(self):
		self.assertTrue(rules.requires_comment(rules.REJECT))
		self.assertTrue(rules.requires_comment(rules.RETURN))
		self.assertFalse(rules.requires_comment(rules.APPROVE))


class TestApprovingPrincipals(UnitTestCase):
	def test_counts_principal_once_per_level_and_cycle(self):
		actions = [
			{"cycle": 1, "level": 1, "action": "Approve", "approver": "a", "on_behalf_of": None},
			{"cycle": 1, "level": 1, "action": "Approve", "approver": "d", "on_behalf_of": "b"},
			{"cycle": 1, "level": 2, "action": "Approve", "approver": "c", "on_behalf_of": None},
			{"cycle": 0, "level": 1, "action": "Approve", "approver": "x", "on_behalf_of": None},
			{"cycle": 1, "level": 1, "action": "Request", "approver": "o", "on_behalf_of": None},
		]
		self.assertEqual(rules.approving_principals(actions, 1, 1), {"a", "b"})


class TestSla(UnitTestCase):
	def test_due_at_adds_calendar_hours(self):
		self.assertEqual(rules.due_at("2026-10-03 22:00:00", 5), datetime(2026, 10, 4, 3, 0))

	def test_fractional_hours(self):
		self.assertEqual(rules.due_at("2026-10-03 10:00:00", 1.5), datetime(2026, 10, 3, 11, 30))

	def test_no_sla_means_no_due_date(self):
		self.assertIsNone(rules.due_at("2026-10-03 10:00:00", 0))
		self.assertIsNone(rules.due_at("2026-10-03 10:00:00", None))

	def test_needs_escalation_only_when_pending_overdue_and_not_escalated(self):
		due, later, earlier = "2026-10-03 10:00:00", "2026-10-03 10:00:01", "2026-10-03 09:59:59"
		self.assertTrue(rules.needs_escalation(rules.PENDING, due, 0, later))
		self.assertFalse(rules.needs_escalation(rules.PENDING, due, 0, earlier))
		self.assertFalse(rules.needs_escalation(rules.PENDING, due, 1, later))
		self.assertFalse(rules.needs_escalation(rules.APPROVED, due, 0, later))
		self.assertFalse(rules.needs_escalation(rules.PENDING, None, 0, later))


class TestDelegationCovers(UnitTestCase):
	def test_window_is_inclusive(self):
		for day in ("2026-10-01", "2026-10-05", "2026-10-10"):
			self.assertTrue(rules.delegation_covers("2026-10-01", "2026-10-10", [], "Leave", day))

	def test_outside_window(self):
		self.assertFalse(rules.delegation_covers("2026-10-01", "2026-10-10", [], "Leave", "2026-09-30"))
		self.assertFalse(rules.delegation_covers("2026-10-01", "2026-10-10", [], "Leave", "2026-10-11"))

	def test_document_type_scope(self):
		self.assertTrue(rules.delegation_covers("2026-10-01", "2026-10-10", ["Leave"], "Leave", "2026-10-02"))
		self.assertFalse(rules.delegation_covers("2026-10-01", "2026-10-10", ["Fee"], "Leave", "2026-10-02"))


class TestEditableFields(UnitTestCase):
	def test_parse_fieldnames(self):
		self.assertEqual(rules.parse_fieldnames("amount, remarks\nnotes "), ["amount", "remarks", "notes"])
		self.assertEqual(rules.parse_fieldnames(None), [])

	def test_disallowed_changes(self):
		self.assertEqual(rules.disallowed_changes({"amount", "title"}, ["amount"]), ["title"])
		self.assertEqual(rules.disallowed_changes({"amount"}, ["amount"]), [])
