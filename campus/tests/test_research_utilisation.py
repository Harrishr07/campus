"""P3-T17 (M08-06, blueprint D9) tests: Utilisation Certificate and Statement of Expenditure.

A UC for a sanction and period is read from the GL: opening unspent, grants received, interest, total available,
expenditure by budget head (the head's accounts on the sanction's cost centre) and closing unspent. It is approved PI ->
Accounts -> Principal through the approval engine, refused while spending on the project sits outside the sanction's
heads, snapshotted on approval and flagged "source changed" when a back-dated entry moves its figures."""

import json
from unittest.mock import patch

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe.utils import add_days, getdate, today

from campus.campus_platform.approvals import approve, request_approval
from campus.research.budget_control import BUDGET_HEAD_FIELD
from campus.research.utilisation import (
	RECHECK_FLAG,
	UC_POLICY,
	forget_queued,
	recheck_queued,
	utilisation_figures,
)
from campus.tests.factories import make_user
from campus.tests.finance_factories import make_account
from campus.tests.research_fixtures import ABBR, COLLEGE, SanctionFixtures

PI_USER = "uc-pi@example.com"
ACCOUNTS_USER = "uc-accounts@example.com"
PRINCIPAL_USER = "uc-principal@example.com"
OUTSIDER = "uc-outsider@example.com"
DOCTYPE = "Utilisation Certificate"


class TestUtilisationCertificate(SanctionFixtures):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for user, role in (
			(PI_USER, None),
			(ACCOUNTS_USER, "Accounts Manager"),
			(PRINCIPAL_USER, "Principal"),
			(OUTSIDER, None),
		):
			make_user(user, [COLLEGE])
			if role:
				frappe.get_doc("User", user).add_roles(role)

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(forget_queued)  # no queued recheck leaks into the next test
		self.link_user(self.pi, PI_USER)  # an employee's user gets the Employee role
		self.link_user(self.make_employee("Outsider", COLLEGE), OUTSIDER)
		self.equipment_account = f"Capital Equipment - {ABBR}"
		self.depreciation_account = f"Depreciation - {ABBR}"
		self.accumulated_account = f"Accumulated Depreciation - {ABBR}"
		self.period_start = add_days(today(), -60)

	def link_user(self, employee, user):
		employee = frappe.get_doc("Employee", employee)
		employee.user_id = user
		employee.save()

	def submitted_sanction(self, **values):
		sanction = self.sanction(**values)
		sanction.submit()
		return sanction.reload()

	# vouchers
	def spend(self, sanction, account, amount, head, posting_date=None):
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COLLEGE,
				"posting_date": posting_date or today(),
				"accounts": [
					{
						"account": account,
						"debit_in_account_currency": max(amount, 0),
						"credit_in_account_currency": max(-amount, 0),
						"cost_center": sanction.cost_center,
						"project": sanction.project,
						BUDGET_HEAD_FIELD: head,
					},
					{
						"account": self.bank,
						"credit_in_account_currency": max(amount, 0),
						"debit_in_account_currency": max(-amount, 0),
						"cost_center": sanction.cost_center,
					},
				],
			}  # fmt: skip
		).insert()
		entry.submit()
		return entry

	def untagged_spend(self, sanction, amount, posting_date=None):
		"""Spending on the project outside its heads, as a voucher Campus does not tag (e.g. a Stock Entry) posts it."""
		hospitality = make_account(COLLEGE, ABBR, "RSA Hospitality", "Indirect Expenses")
		with patch("campus.research.budget_control.validate_lines"):
			entry = frappe.get_doc(
				{
					"doctype": "Journal Entry",
					"company": COLLEGE,
					"posting_date": posting_date or today(),
					"accounts": [
						{
							"account": hospitality,
							"debit_in_account_currency": amount,
							"cost_center": sanction.cost_center,
							"project": sanction.project,
						},
						{
							"account": self.bank,
							"credit_in_account_currency": amount,
							"cost_center": sanction.cost_center,
						},
					],
				}  # fmt: skip
			).insert()
			entry.submit()
		return entry

	def depreciate(self, sanction, amount, posting_date=None):
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COLLEGE,
				"posting_date": posting_date or today(),
				"voucher_type": "Depreciation Entry",
				"accounts": [
					{
						"account": self.depreciation_account,
						"debit_in_account_currency": amount,
						"cost_center": sanction.cost_center,
					},
					{
						"account": self.accumulated_account,
						"credit_in_account_currency": amount,
						"cost_center": sanction.cost_center,
					},
				],
			}  # fmt: skip
		).insert()
		entry.submit()

	def interest(self, sanction, amount, posting_date=None):
		doc = frappe.get_doc(
			{
				"doctype": "Grant Interest",
				"sanction": sanction.name,
				"posting_date": posting_date or today(),
				"amount": amount,
				"received_in": self.bank,
				"reference_no": "INT0001",
			}  # fmt: skip
		).insert()
		doc.submit()

	def recognise(self, sanction, to_date):
		doc = frappe.get_doc(
			{
				"doctype": "Grant Income Recognition",
				"company": COLLEGE,
				"from_date": sanction.start_date,
				"to_date": to_date,
				"sanctions": [{"sanction": sanction.name}],
			}  # fmt: skip
		).insert()
		doc.submit()

	def funded(self, sanction):
		"""Before the period: 510,000 received, 10,000 spent and recognised. In it: 340,000 received, 1,000 interest,
		20,000 + 5,000 revenue spent, a 300,000 asset bought and depreciated by 5,000."""
		before = add_days(self.period_start, -20)
		self.receipt(sanction, posting_date=before).submit()
		self.spend(sanction, self.consumables_account, 10000, self.consumables, posting_date=before)
		self.recognise(sanction, add_days(self.period_start, -1))
		self.receipt(sanction, "Second", posting_date=add_days(self.period_start, 5)).submit()
		self.interest(sanction, 1000, posting_date=add_days(self.period_start, 6))
		self.spend(
			sanction,
			self.consumables_account,
			20000,
			self.consumables,
			posting_date=add_days(self.period_start, 7),
		)
		self.spend(
			sanction, self.travel_account, 5000, self.travel, posting_date=add_days(self.period_start, 8)
		)
		self.spend(
			sanction,
			self.equipment_account,
			300000,
			self.equipment,
			posting_date=add_days(self.period_start, 9),
		)
		self.depreciate(sanction, 5000, posting_date=add_days(self.period_start, 10))

	def certificate(self, sanction, from_date=None, to_date=None, **values):
		return frappe.get_doc(
			{"doctype": DOCTYPE, "sanction": sanction.name, "from_date": from_date or self.period_start, "to_date": to_date or today(), **values}
		).insert()  # fmt: skip

	def approve_all(self, uc, levels=(PI_USER, ACCOUNTS_USER, PRINCIPAL_USER)):
		request = request_approval(DOCTYPE, uc.name)
		for user in levels:
			frappe.set_user(user)
			try:
				approve(request, None)
			finally:
				frappe.set_user("Administrator")
		return request

	def approved(self, sanction, **values):
		uc = self.certificate(sanction, **values)
		self.approve_all(uc)
		return uc.reload()

	def heads_of(self, uc):
		return {row.budget_head: row for row in uc.heads}

	def flagged(self, uc):
		"""The UC's Source Changed flag once the transaction commits (the recheck runs before the commit). A UC that
		ends up flagged must have been queued by the posting."""
		queued = set(frappe.flags.get(RECHECK_FLAG) or ())
		recheck_queued()
		flag = frappe.db.get_value(DOCTYPE, uc.name, "source_changed")
		if flag:
			self.assertIn(uc.name, queued)
		return flag

	# acceptance 1: UC figures equal GL figures for the period
	def test_figures_equal_the_ledger_for_the_period(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.certificate(sanction)
		self.assertEqual(
			(
				uc.opening_unspent,
				uc.grants_received,
				uc.interest_earned,
				uc.other_adjustments,
				uc.total_available,
			),
			(500000, 340000, 1000, 0, 841000),
		)
		self.assertEqual((uc.total_expenditure, uc.closing_unspent), (325000, 516000))
		heads = self.heads_of(uc)
		consumables = heads[self.consumables]
		self.assertEqual(
			(
				consumables.sanctioned_amount,
				consumables.spent_before,
				consumables.spent_in_period,
				consumables.spent_to_date,
				consumables.balance,
			),
			(300000, 10000, 20000, 30000, 270000),
		)
		self.assertEqual(
			(heads[self.equipment].is_capital, heads[self.equipment].spent_in_period), (1, 300000)
		)
		self.assertEqual(heads[self.travel].spent_in_period, 5000)

	def test_closing_unspent_is_received_and_interest_less_spending_on_the_ledger(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		self.spend(
			sanction, self.consumables_account, 7000, self.consumables, posting_date=add_days(today(), 1)
		)  # after the period
		figures = utilisation_figures(sanction.name, self.period_start, today())
		inflow = frappe.db.sql(
			"""select coalesce(sum(credit - debit), 0) from `tabGL Entry` where account = %s and is_cancelled = 0
			and posting_date <= %s and voucher_no not in (select journal_entry from `tabGrant Income Recognition` where docstatus = 1)""",
			(sanction.liability_account, today()),
		)[0][0]
		spent = frappe.db.sql(
			"""select coalesce(sum(debit - credit), 0) from `tabGL Entry` where cost_center = %s and is_cancelled = 0
			and posting_date <= %s and account in %s""",
			(
				sanction.cost_center,
				today(),
				(self.consumables_account, self.travel_account, self.equipment_account),
			),
		)[0][0]
		self.assertEqual(figures.closing_unspent, inflow - spent)
		self.assertEqual(figures.closing_unspent, 851000 - 335000)

	def test_a_credit_to_a_head_in_the_period_reduces_its_expenditure(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		self.spend(
			sanction,
			self.consumables_account,
			-4000,
			self.consumables,
			posting_date=add_days(self.period_start, 12),
		)
		uc = self.certificate(sanction)
		self.assertEqual(self.heads_of(uc)[self.consumables].spent_in_period, 16000)
		self.assertEqual(uc.closing_unspent, 520000)

	def test_a_refund_to_the_agency_is_shown_as_an_adjustment(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COLLEGE,
				"posting_date": today(),
				"accounts": [
					{
						"account": sanction.liability_account,
						"debit_in_account_currency": 2500,
						"cost_center": sanction.cost_center,
						"project": sanction.project,
					},
					{
						"account": self.bank,
						"credit_in_account_currency": 2500,
						"cost_center": sanction.cost_center,
					},
				],
			}  # fmt: skip
		).insert().submit()
		uc = self.certificate(sanction)
		self.assertEqual(
			(uc.other_adjustments, uc.total_available, uc.closing_unspent), (-2500, 838500, 513500)
		)

	def test_period_must_be_inside_the_sanction_and_heads_must_not_share_accounts(self):
		sanction = self.submitted_sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "From Date"):
			self.certificate(sanction, from_date=today(), to_date=add_days(today(), -1))
		with self.assertRaisesRegex(frappe.ValidationError, "sanction period"):
			self.certificate(sanction, from_date=add_days(sanction.start_date, -1))
		lab = self.make_head("RSA Lab Equipment", [(COLLEGE, self.equipment_account)], is_capital=1)
		scheme = frappe.get_doc("Funding Scheme", self.scheme)
		scheme.append("heads", {"budget_head": lab})
		scheme.save()
		row = frappe.get_doc("Sanction", sanction.name).append(
			"heads", {"budget_head": lab, "fiscal_year": self.year1.name, "amount": 1, "is_capital": 1}
		)
		row.db_insert()  # a second capital head on the same Fixed Asset ledger
		with self.assertRaisesRegex(frappe.ValidationError, "share"):
			self.certificate(sanction)

	# approval PI -> Accounts -> Principal
	def test_approval_runs_pi_accounts_principal_and_issues_the_certificate(self):
		self.assertTrue(frappe.db.exists("Approval Policy", UC_POLICY))
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.certificate(sanction)
		self.assertEqual(uc.pi_user, PI_USER)
		request = request_approval(DOCTYPE, uc.name)
		frappe.set_user(ACCOUNTS_USER)  # the PI certifies first
		with self.assertRaises(frappe.PermissionError):
			approve(request, None)
		frappe.set_user("Administrator")
		for user in (PI_USER, ACCOUNTS_USER, PRINCIPAL_USER):
			frappe.set_user(user)
			approve(request, None)
			frappe.set_user("Administrator")
		uc.reload()
		self.assertEqual(uc.docstatus, 1)
		self.assertEqual(
			(uc.pi_certified_by, uc.accounts_certified_by, uc.principal_certified_by),
			(PI_USER, ACCOUNTS_USER, PRINCIPAL_USER),
		)
		self.assertEqual(uc.version, 1)
		snapshot = json.loads(uc.snapshot)
		self.assertEqual(snapshot["figures"]["closing_unspent"], 516000)
		self.assertEqual(uc.source_changed, 0)
		record = frappe.db.get_value(
			"Verifiable Document",
			{"code": uc.verification_code},
			["reference_name", "status", "print_format"],
			as_dict=True,
		)
		self.assertEqual((record.reference_name, record.status), (uc.name, "Valid"))
		self.assertEqual(record.print_format, "Utilisation Certificate")

	def test_one_user_cannot_certify_at_two_levels(self):
		pi = frappe.get_doc("User", PI_USER)
		pi.add_roles("Accounts Manager")  # the PI is also in Accounts
		self.addCleanup(lambda: frappe.get_doc("User", PI_USER).remove_roles("Accounts Manager"))
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.certificate(sanction)
		request = request_approval(DOCTYPE, uc.name)
		frappe.set_user(PI_USER)
		approve(request, None)  # level 1, as the PI
		with self.assertRaises(frappe.PermissionError):
			approve(request, None)  # level 2, as Accounts
		frappe.set_user("Administrator")
		for user in (ACCOUNTS_USER, PRINCIPAL_USER):
			frappe.set_user(user)
			approve(request, None)
			frappe.set_user("Administrator")
		uc.reload()
		self.assertEqual(
			(uc.docstatus, uc.pi_certified_by, uc.accounts_certified_by), (1, PI_USER, ACCOUNTS_USER)
		)

	def test_the_certifiers_must_be_different_users(self):
		uc = self.certificate(self.submitted_sanction())
		uc.pi_certified_by, uc.accounts_certified_by, uc.principal_certified_by = (
			PI_USER,
			ACCOUNTS_USER,
			PI_USER,
		)
		with self.assertRaisesRegex(frappe.ValidationError, PI_USER):
			uc.check_distinct_certifiers()
		uc.principal_certified_by = PRINCIPAL_USER
		uc.check_distinct_certifiers()

	def test_a_direct_submit_without_approval_is_refused(self):
		sanction = self.submitted_sanction()
		uc = self.certificate(sanction)
		with self.assertRaisesRegex(frappe.ValidationError, "approval"):
			uc.submit()

	def test_the_pi_reads_only_their_own_certificates(self):
		sanction = self.submitted_sanction()
		uc = self.certificate(sanction)
		frappe.set_user(PI_USER)
		self.assertTrue(frappe.has_permission(DOCTYPE, "read", uc.name))
		self.assertFalse(frappe.has_permission(DOCTYPE, "write", uc.name))
		self.assertIn(uc.name, frappe.get_list(DOCTYPE, pluck="name"))
		frappe.set_user(OUTSIDER)
		self.assertFalse(frappe.has_permission(DOCTYPE, "read", uc.name))
		self.assertNotIn(uc.name, frappe.get_list(DOCTYPE, pluck="name"))

	# acceptance 2: no approval while spending on the project sits outside its heads
	def test_unreconciled_entries_block_approval(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		entry = self.untagged_spend(sanction, 1200, posting_date=add_days(self.period_start, 3))
		uc = self.certificate(sanction)
		self.assertEqual((uc.unreconciled_entries, uc.unreconciled_amount), (1, 1200))
		self.assertEqual(uc.closing_unspent, 516000)  # kept out of the heads
		request = request_approval(DOCTYPE, uc.name)
		for user in (PI_USER, ACCOUNTS_USER):
			frappe.set_user(user)
			approve(request, None)
			frappe.set_user("Administrator")
		frappe.db.savepoint("uc_gate")
		frappe.set_user(PRINCIPAL_USER)
		with self.assertRaisesRegex(frappe.ValidationError, entry.name):
			approve(request, None)
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="uc_gate")
		self.assertEqual(frappe.db.get_value(DOCTYPE, uc.name, "docstatus"), 0)

	def test_untagged_spending_on_the_project_under_another_cost_centre_is_unreconciled(self):
		sanction = self.submitted_sanction()
		main = frappe.db.get_value("Company", COLLEGE, "cost_center")
		hospitality = make_account(COLLEGE, ABBR, "RSA Hospitality", "Indirect Expenses")
		with patch("campus.research.budget_control.validate_lines"):
			frappe.get_doc(
				{
					"doctype": "Journal Entry",
					"company": COLLEGE,
					"posting_date": today(),
					"accounts": [
						{
							"account": hospitality,
							"debit_in_account_currency": 300,
							"cost_center": main,
							"project": sanction.project,
						},
						{"account": self.bank, "credit_in_account_currency": 300, "cost_center": main},
					],
				}  # fmt: skip
			).insert().submit()
		self.depreciate(sanction, 100)  # depreciation on the cost centre is not spending
		uc = self.certificate(sanction)
		self.assertEqual((uc.unreconciled_entries, uc.unreconciled_amount), (1, 300))

	def test_the_final_unreconciled_read_locks_only_the_cost_centre_branch(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
			utilisation_figures(sanction.name, self.period_start, today(), lock=True)
		unreconciled = [
			str(c.args[0])
			for c in sql.call_args_list
			if "`tabGL Entry`" in str(c.args[0]) and "`tabAccount`" in str(c.args[0])
		]
		by_project = [q for q in unreconciled if "`project`" in q]
		self.assertEqual(len(by_project), 1)
		self.assertNotIn("FOR UPDATE", by_project[0].upper())  # no index on project: never a locking scan
		by_cost_center = [q for q in unreconciled if "`project`" not in q]
		self.assertEqual(len(by_cost_center), 1)
		self.assertIn("FOR UPDATE", by_cost_center[0].upper())

	def test_figures_moved_during_approval_refuse_the_final_approval(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.certificate(sanction)
		request = request_approval(DOCTYPE, uc.name)
		for user in (PI_USER, ACCOUNTS_USER):
			frappe.set_user(user)
			approve(request, None)
			frappe.set_user("Administrator")
		self.spend(
			sanction, self.travel_account, 900, self.travel, posting_date=add_days(self.period_start, 20)
		)
		frappe.set_user(PRINCIPAL_USER)
		with self.assertRaisesRegex(frappe.ValidationError, "changed"):
			approve(request, None)

	# change detection
	def test_backdated_entry_after_approval_flags_source_changed(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		self.spend(
			sanction, self.consumables_account, 800, self.consumables, posting_date=add_days(today(), 1)
		)  # later period
		self.assertEqual(self.flagged(uc), 0)
		entry = self.spend(
			sanction,
			self.consumables_account,
			800,
			self.consumables,
			posting_date=add_days(self.period_start, 15),
		)
		self.assertEqual(self.flagged(uc), 1)
		uc.reload()
		self.assertEqual(uc.source_changed, 1)
		self.assertTrue(uc.source_changed_on)
		self.assertEqual(
			json.loads(uc.snapshot)["figures"]["closing_unspent"], 516000
		)  # the approved figures stay
		self.assertEqual(uc.closing_unspent, 516000)
		entry.cancel()
		self.assertTrue(uc.recheck_source() is False)  # back to the approved figures
		self.assertEqual(frappe.db.get_value(DOCTYPE, uc.name, "source_changed"), 0)

	def test_cancelling_an_in_period_voucher_after_approval_flags_source_changed(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		entry = self.spend(
			sanction, self.travel_account, 600, self.travel, posting_date=add_days(self.period_start, 11)
		)
		uc = self.approved(sanction)
		self.assertEqual(uc.source_changed, 0)
		entry.cancel()
		self.assertEqual(self.flagged(uc), 1)

	def test_entry_before_the_period_moves_the_opening_and_flags_too(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		self.interest(sanction, 1, posting_date=add_days(self.period_start, -30))
		self.assertEqual(self.flagged(uc), 1)

	def test_unrelated_and_reconciling_entries_do_not_flag(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		other = self.submitted_sanction()
		self.spend(
			other,
			self.consumables_account,
			500,
			self.consumables,
			posting_date=add_days(self.period_start, 15),
		)
		self.depreciate(
			sanction, 100, posting_date=add_days(self.period_start, 15)
		)  # on the cost centre, not spending
		self.assertEqual(self.flagged(uc), 0)

	def test_a_voucher_that_nets_to_zero_on_the_cost_centre_does_not_flag(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		row = {"account": self.consumables_account, "cost_center": sanction.cost_center, "project": sanction.project,
			BUDGET_HEAD_FIELD: self.consumables}  # fmt: skip
		frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COLLEGE,
				"posting_date": add_days(self.period_start, 15),
				"accounts": [
					row | {"debit_in_account_currency": 300},
					row | {"credit_in_account_currency": 300},
				],
			}  # fmt: skip
		).insert().submit()
		self.assertEqual(self.flagged(uc), 0)

	def test_a_recognition_run_up_to_the_period_end_does_not_flag(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		self.recognise(sanction, uc.to_date)
		self.assertEqual(self.flagged(uc), 0)

	def test_a_posting_queues_the_uc_and_registers_the_recheck_before_commit(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		forget_queued()
		self.spend(
			sanction, self.travel_account, 250, self.travel, posting_date=add_days(self.period_start, 15)
		)
		self.assertIn(uc.name, frappe.flags.get(RECHECK_FLAG))
		self.assertIn(recheck_queued, frappe.db.before_commit._functions)

	def test_a_failing_recheck_is_logged_and_never_breaks_the_commit(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		self.spend(
			sanction, self.travel_account, 250, self.travel, posting_date=add_days(self.period_start, 15)
		)
		logged = frappe.db.count("Error Log", {"reference_name": uc.name})
		with patch("campus.research.utilisation.mark_source", side_effect=RuntimeError("db_set failed")):
			recheck_queued()  # returns normally
		self.assertIsNone(frappe.flags.get(RECHECK_FLAG))
		self.assertEqual(frappe.db.count("Error Log", {"reference_name": uc.name}), logged + 1)

	def test_a_real_change_in_the_period_still_flags_once_committed(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		self.spend(
			sanction, self.travel_account, 250, self.travel, posting_date=add_days(self.period_start, 15)
		)
		self.assertEqual(self.flagged(uc), 1)
		self.assertEqual(
			frappe.db.get_value(DOCTYPE, uc.name, "closing_unspent"), 516000
		)  # approved figures kept

	def test_backdated_untagged_spending_flags_too(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		self.untagged_spend(sanction, 50, posting_date=add_days(self.period_start, 15))
		self.assertEqual(self.flagged(uc), 1)

	def test_a_ledger_entry_is_never_blocked_by_a_certificate_that_cannot_be_recomputed(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		self.spend(
			sanction,
			self.consumables_account,
			10,
			self.consumables,
			posting_date=add_days(self.period_start, 15),
		)
		with patch(
			"campus.research.utilisation.utilisation_figures",
			side_effect=frappe.ValidationError("broken mapping"),
		):
			self.assertEqual(self.flagged(uc), 1)

	def test_a_ledger_entry_is_never_blocked_by_an_unexpected_recompute_error(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.approved(sanction)
		self.spend(
			sanction,
			self.consumables_account,
			10,
			self.consumables,
			posting_date=add_days(self.period_start, 15),
		)
		with patch(
			"campus.research.utilisation.utilisation_figures", side_effect=KeyError("corrupt snapshot")
		):
			self.assertEqual(self.flagged(uc), 1)

	# versions
	def test_a_revised_certificate_is_a_new_version_and_periods_do_not_overlap(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		first = self.approved(sanction)
		frappe.db.savepoint("uc_overlap")
		with self.assertRaisesRegex(frappe.ValidationError, first.name):
			self.approved(sanction, from_date=add_days(self.period_start, 10))
		frappe.db.rollback(save_point="uc_overlap")
		first.cancel()
		self.assertEqual(
			frappe.db.get_value("Verifiable Document", {"code": first.verification_code}, "status"), "Revoked"
		)
		self.assertFalse(
			frappe.copy_doc(first, ignore_no_copy=False).pi_certified_by
		)  # an amendment starts uncertified
		revised = frappe.copy_doc(first)
		revised.amended_from, revised.docstatus = first.name, 0
		revised.insert()
		self.assertEqual(revised.version, 2)
		self.approve_all(revised)
		self.assertEqual(revised.reload().docstatus, 1)

	def test_uc_format_of_the_scheme_picks_the_print_format(self):
		frappe.db.set_value("Funding Scheme", self.scheme, "uc_format", "Statement of Expenditure")
		sanction = self.submitted_sanction()
		uc = self.approved(sanction)
		self.assertEqual(
			frappe.db.get_value("Verifiable Document", {"code": uc.verification_code}, "print_format"),
			"Statement of Expenditure",
		)
		frappe.db.set_value("Funding Scheme", self.scheme, "uc_format", "No Such Format")
		with self.assertRaisesRegex(frappe.ValidationError, "No Such Format"):
			self.certificate(sanction, from_date=add_days(today(), 1), to_date=add_days(today(), 2))

	# prints and reports
	def test_prints_render_the_placeholder_uc_and_the_soe(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.certificate(sanction)
		html = frappe.get_print(DOCTYPE, uc.name, print_format="Utilisation Certificate")
		self.assertIn("GFR 12-A", html)
		self.assertIn("placeholder", html.lower())
		self.assertRegex(html, r"5,?16,000")  # western or lakh grouping, as the currency formats it
		soe = frappe.get_print(DOCTYPE, uc.name, print_format="Statement of Expenditure")
		self.assertIn(self.consumables, soe)
		self.assertRegex(soe, r"2,?70,000")

	def test_grant_ledger_by_head_matches_the_certificate(self):
		from campus.research.report.grant_ledger_by_head.grant_ledger_by_head import execute

		sanction = self.submitted_sanction()
		self.funded(sanction)
		uc = self.certificate(sanction)
		_columns, rows = execute(
			{
				"company": COLLEGE,
				"sanction": sanction.name,
				"from_date": self.period_start,
				"to_date": today(),
			}
		)
		totals = {row["budget_head"]: row["net"] for row in rows if row.get("is_total")}
		self.assertEqual(totals, {row.budget_head: row.spent_in_period for row in uc.heads})
		opening = [row for row in rows if row.get("is_opening")]
		self.assertEqual({row["budget_head"]: row["balance"] for row in opening}[self.consumables], 10000)
		self.assertEqual(execute({"company": COLLEGE})[1], [])

	def test_uc_status_report_shows_due_overdue_and_submitted_periods(self):
		from campus.research.report.utilisation_certificate_status.utilisation_certificate_status import (
			execute,
		)

		frappe.db.set_value("Research Settings", COLLEGE, "uc_due_days", 90)
		year0 = frappe._dict(
			zip(
				("name", "start", "end"),
				get_fiscal_year(add_days(self.year1.start, -1), company=COLLEGE)[:3],
				strict=True,
			)
		)
		sanction = self.submitted_sanction(
			start_date=year0.start, sanction_order_date=year0.start, end_date=self.year1.end,
			heads=[(self.consumables, year0.name, 1000), (self.consumables, self.year1.name, 1000)], instalments=[("First", 2000)],
		)  # fmt: skip
		rows = {
			getdate(row["to_date"]): row
			for row in execute({"company": COLLEGE, "sanction": sanction.name})[1]
		}
		self.assertEqual(rows[getdate(year0.end)]["status"], "Overdue")
		self.assertEqual(getdate(rows[getdate(year0.end)]["due_date"]), getdate(add_days(year0.end, 90)))
		self.assertEqual(rows[getdate(self.year1.end)]["status"], "Not Yet Due")
		uc = self.approved(sanction, from_date=year0.start, to_date=year0.end)
		rows = {
			getdate(row["to_date"]): row
			for row in execute({"company": COLLEGE, "sanction": sanction.name})[1]
		}
		self.assertEqual(
			(rows[getdate(year0.end)]["status"], rows[getdate(year0.end)]["certificate"]),
			("Submitted", uc.name),
		)
		frappe.db.set_value(DOCTYPE, uc.name, "source_changed", 1)
		rows = {
			getdate(row["to_date"]): row
			for row in execute({"company": COLLEGE, "sanction": sanction.name})[1]
		}
		self.assertEqual(rows[getdate(year0.end)]["status"], "Source Changed")
		self.assertEqual(execute({})[1], [])
