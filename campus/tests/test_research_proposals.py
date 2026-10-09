"""P3-T13 (M08-02) tests: Research Calls and Research Proposals. A proposal's scheme must be usable by its college
(campus.research.api), its budget is by the scheme's heads, internal review runs through the approval engine, and the
proposal can be submitted to the agency only after internal approval. PIs get deadline reminders through messaging.
The Proposal Pipeline report lists a college's proposals by stage."""

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import add_days, getdate, today

from campus.campus_platform.approvals import approve, reject, request_approval
from campus.research import proposals
from campus.research.report.research_proposal_pipeline import research_proposal_pipeline as pipeline
from campus.research.setup import REMINDER_EVENT, seed_research
from campus.tests.factories import make_user
from campus.tests.finance_factories import make_account, make_company_with_accounts
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR = "Research Proposal Test College", "RPTC"
OTHER, OTHER_ABBR = "Research Proposal Other College", "RPTO"
REVIEWER = "rp-reviewer@example.com"
PI_USER = "rp-pi@example.com"
CO_PI_USER = "rp-copi@example.com"


class TestReminderDue(UnitTestCase):
	def test_inside_the_window_and_on_the_deadline_day(self):
		self.assertTrue(proposals.reminder_due("2026-10-20", "2026-10-13", 7))
		self.assertTrue(proposals.reminder_due("2026-10-20", "2026-10-17", 7))
		self.assertTrue(proposals.reminder_due("2026-10-20", "2026-10-20", 7))

	def test_before_the_window_or_after_the_deadline(self):
		self.assertFalse(proposals.reminder_due("2026-10-20", "2026-10-12", 7))
		self.assertFalse(proposals.reminder_due("2026-10-20", "2026-10-21", 7))

	def test_zero_days_reminds_on_the_deadline_day_only(self):
		self.assertTrue(proposals.reminder_due("2026-10-20", "2026-10-20", 0))
		self.assertFalse(proposals.reminder_due("2026-10-20", "2026-10-19", 0))


class TestPipelineStage(UnitTestCase):
	def test_draft_stage_follows_the_approval_request(self):
		self.assertEqual(pipeline.stage("Draft", None), "Draft")
		self.assertEqual(pipeline.stage("Draft", "Pending"), "Under Internal Review")
		self.assertEqual(pipeline.stage("Draft", "Returned"), "Returned for Changes")
		self.assertEqual(pipeline.stage("Draft", "Rejected"), "Rejected Internally")

	def test_later_stages_are_the_status(self):
		for status in ("Approved", "Submitted to Agency", "Sanctioned", "Not Sanctioned", "Cancelled"):
			self.assertEqual(pipeline.stage(status, "Approved"), status)


class TestResearchProposal(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company_with_accounts(COLLEGE, ABBR)
		make_company_with_accounts(OTHER, OTHER_ABBR)
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
		make_user(REVIEWER, [COLLEGE])
		make_user(PI_USER, [COLLEGE])
		make_user(CO_PI_USER, [COLLEGE])
		for user in (REVIEWER, PI_USER, CO_PI_USER):
			frappe.get_doc("User", user).add_roles("Principal")

	def setUp(self):
		frappe.db.savepoint("research_proposal_test")
		self.addCleanup(frappe.db.rollback, save_point="research_proposal_test")
		self.addCleanup(frappe.set_user, "Administrator")
		seed_research()
		self.make_settings(COLLEGE, ABBR)
		consumables = make_account(COLLEGE, ABBR, "RP Consumables", "Indirect Expenses")
		travel = make_account(COLLEGE, ABBR, "RP Travel", "Indirect Expenses")
		self.consumables = self.make_head("RPT Consumables", [(COLLEGE, consumables)])
		self.travel = self.make_head("RPT Travel", [(COLLEGE, travel)])
		self.outside_head = self.make_head("RPT Outside Head", [(COLLEGE, consumables)])
		self.agency = frappe.get_doc({"doctype": "Funding Agency", "agency_name": "RPT Science Board"}).insert().name
		self.scheme = self.make_scheme("RPT Core Grant", [self.consumables, self.travel])
		self.call = self.make_call(add_days(today(), 3))
		self.pi = self.make_employee("Pi", COLLEGE, user=PI_USER)
		self.co_pi = self.make_employee("CoPi", COLLEGE, user=CO_PI_USER)

	# fixtures
	def make_settings(self, company, abbr):
		frappe.get_doc(
			{
				"doctype": "Research Settings", "company": company,
				"grant_liability_parent": f"Current Liabilities - {abbr}",
				"grant_income_account": make_account(company, abbr, "Grant Income", "Indirect Income"),
				"deferred_capital_grant_account": make_account(company, abbr, "Deferred Capital Grant", "Non-Current Liabilities"),
			}  # fmt: skip
		).insert()

	def make_head(self, name, accounts):
		return frappe.get_doc(
			{"doctype": "Grant Budget Head", "head_name": name, "accounts": [{"company": c, "account": a} for c, a in accounts]}
		).insert().name  # fmt: skip

	def make_scheme(self, name, heads):
		return frappe.get_doc(
			{"doctype": "Funding Scheme", "scheme_name": name, "funding_agency": self.agency, "heads": [{"budget_head": h} for h in heads]}
		).insert().name  # fmt: skip

	def make_call(self, deadline, reminder_days=7, scheme=None):
		return frappe.get_doc(
			{
				"doctype": "Research Call", "call_title": f"RPT Call {frappe.generate_hash(length=6)}", "funding_agency": self.agency,
				"funding_scheme": scheme or self.scheme, "deadline": deadline, "reminder_days": reminder_days,
			}  # fmt: skip
		).insert().name

	def make_employee(self, first_name, company, user=None):
		return frappe.get_doc(
			{
				"doctype": "Employee", "first_name": first_name, "last_name": frappe.generate_hash(length=6), "gender": "Male",
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": company, "user_id": user,
				"personal_email": f"{first_name.lower()}-{frappe.generate_hash(length=6)}@example.com",
			}  # fmt: skip
		).insert().name

	def proposal(self, budget=None, company=COLLEGE, call=None, **values):
		budget = budget or [(self.consumables, 300000), (self.travel, 50000)]
		return frappe.get_doc(
			{
				"doctype": "Research Proposal", "title": "Low-cost water sensors", "company": company,
				"research_call": call or self.call, "principal_investigator": self.pi,
				"co_investigators": [{"employee": self.co_pi}],
				"budget": [{"budget_head": head, "amount": amount} for head, amount in budget], **values,
			}  # fmt: skip
		).insert()

	def approved(self, proposal):
		request = request_approval("Research Proposal", proposal.name)
		frappe.set_user(REVIEWER)
		approve(request, None)
		frappe.set_user("Administrator")
		return frappe.get_doc("Research Proposal", proposal.name)

	# call and proposal set-up
	def test_call_scheme_must_belong_to_the_agency(self):
		other_agency = frappe.get_doc({"doctype": "Funding Agency", "agency_name": "RPT Other Board"}).insert().name
		with self.assertRaisesRegex(frappe.ValidationError, "RPT Other Board"):
			frappe.get_doc(
				{"doctype": "Research Call", "call_title": "RPT Mismatch", "funding_agency": other_agency,
				 "funding_scheme": self.scheme, "deadline": today()}
			).insert()  # fmt: skip

	def test_proposal_takes_agency_scheme_and_deadline_from_the_call_and_totals_the_budget(self):
		other_agency = frappe.get_doc({"doctype": "Funding Agency", "agency_name": "RPT Other Board"}).insert().name
		proposal = self.proposal(funding_agency=other_agency, deadline="2000-01-01")
		self.assertEqual((proposal.funding_agency, proposal.funding_scheme), (self.agency, self.scheme))
		self.assertEqual(getdate(proposal.deadline), getdate(add_days(today(), 3)))
		self.assertEqual(proposal.total_budget, 350000)
		self.assertEqual(proposal.status, "Draft")

	def test_proposal_scheme_must_be_usable_by_the_college(self):
		self.make_settings(OTHER, OTHER_ABBR)
		with self.assertRaisesRegex(frappe.ValidationError, "no account mapped"):
			self.proposal(company=OTHER, co_investigators=[])

	def test_budget_heads_must_come_from_the_scheme_once_each_with_an_amount(self):
		with self.assertRaisesRegex(frappe.ValidationError, "RPT Outside Head"):
			self.proposal(budget=[(self.outside_head, 1000)])
		with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
			self.proposal(budget=[(self.consumables, 1000), (self.consumables, 2000)])
		with self.assertRaisesRegex(frappe.ValidationError, "amount"):
			self.proposal(budget=[(self.consumables, 0)])

	def test_investigators_belong_to_the_college_and_the_pi_is_not_a_co_pi(self):
		with self.assertRaisesRegex(frappe.ValidationError, "co-investigator"):
			self.proposal(co_investigators=[{"employee": self.pi}])
		outsider = self.make_employee("Outsider", OTHER)
		with self.assertRaisesRegex(frappe.ValidationError, COLLEGE):
			self.proposal(principal_investigator=outsider, co_investigators=[])

	# acceptance 1: submission to the agency only after internal approval
	def test_draft_cannot_be_submitted_to_the_agency(self):
		proposal = self.proposal()
		with self.assertRaisesRegex(frappe.ValidationError, "internal approval"):
			proposal.submit_to_agency()

	def test_proposal_under_review_cannot_be_submitted_to_the_agency(self):
		proposal = self.proposal()
		request_approval("Research Proposal", proposal.name)
		with self.assertRaisesRegex(frappe.ValidationError, "internal approval"):
			frappe.get_doc("Research Proposal", proposal.name).submit_to_agency()

	def test_internal_review_cannot_be_skipped_by_submitting(self):
		proposal = self.proposal()
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			proposal.submit()

	def test_internal_review_is_required_even_without_a_policy(self):
		frappe.db.delete("Approval Policy", {"document_type": "Research Proposal"})
		proposal = self.proposal()
		with self.assertRaisesRegex(frappe.ValidationError, "Approval Policy"):
			request_approval("Research Proposal", proposal.name)
		self.assertEqual(frappe.db.get_value("Research Proposal", proposal.name, "docstatus"), 0)

	def test_investigators_cannot_review_their_own_proposal(self):
		proposal = self.proposal()
		request = request_approval("Research Proposal", proposal.name)
		self.assertNotIn(PI_USER, frappe.get_all("Approval Request Approver", {"parent": request}, pluck="user"))
		frappe.set_user(PI_USER)  # a Principal, but the proposal's PI
		with self.assertRaisesRegex(frappe.PermissionError, "own approval request"):
			approve(request, None)

	def test_approved_proposal_is_submitted_to_the_agency(self):
		proposal = self.approved(self.proposal())
		self.assertEqual((proposal.docstatus, proposal.status), (1, "Approved"))
		proposal.submit_to_agency(agency_reference="DST/RPT/2026/17")
		proposal.reload()
		self.assertEqual(proposal.status, "Submitted to Agency")
		self.assertEqual(getdate(proposal.submission_date), getdate(today()))
		self.assertEqual(proposal.agency_reference, "DST/RPT/2026/17")
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			proposal.submit_to_agency()

	def test_submission_date_cannot_be_in_the_future(self):
		proposal = self.approved(self.proposal())
		with self.assertRaisesRegex(frappe.ValidationError, "future"):
			proposal.submit_to_agency(submission_date=add_days(today(), 1))

	def test_outcome_only_after_submission_to_the_agency(self):
		proposal = self.approved(self.proposal())
		with self.assertRaisesRegex(frappe.ValidationError, "submitted to the agency"):
			proposal.record_outcome("Sanctioned")
		proposal.submit_to_agency()
		proposal.reload()
		with self.assertRaisesRegex(frappe.ValidationError, "outcome"):
			proposal.record_outcome("Maybe")
		proposal.record_outcome("Sanctioned")
		proposal.reload()
		self.assertEqual((proposal.status, proposal.outcome), ("Sanctioned", "Sanctioned"))
		self.assertEqual(getdate(proposal.outcome_date), getdate(today()))

	# acceptance 1: deadline reminders go to the PI
	def reminder_logs(self, proposal):
		return frappe.get_all("Message Log", {"event_key": REMINDER_EVENT, "reference_name": proposal.name}, pluck="recipient")

	def test_reminder_goes_to_the_pi_only_once_a_day(self):
		proposal = self.proposal()
		proposals.send_deadline_reminders()
		logs = frappe.get_all(
			"Message Log", {"event_key": REMINDER_EVENT, "reference_name": proposal.name}, ["name", "recipient", "dedupe_token"]
		)
		self.assertEqual({(log.recipient, log.dedupe_token) for log in logs}, {(f"Employee:{self.pi}", today())})
		for log in logs:  # the test site has no outgoing mail account: treat the attempt as delivered
			frappe.db.set_value("Message Log", log.name, "status", "Sent")
		proposals.send_deadline_reminders()
		self.assertEqual(len(self.reminder_logs(proposal)), len(logs))  # same day: no second reminder

	def test_reminder_uses_the_calls_current_deadline(self):
		proposal = self.proposal()
		frappe.db.set_value("Research Call", self.call, "deadline", add_days(today(), 20))
		proposals.send_deadline_reminders()
		self.assertEqual(self.reminder_logs(proposal), [])

	def test_no_reminder_outside_the_window_or_once_submitted(self):
		early = self.proposal(call=self.make_call(add_days(today(), 10)))
		past = self.proposal(call=self.make_call(add_days(today(), -1)))
		submitted = self.approved(self.proposal())
		submitted.submit_to_agency()
		proposals.send_deadline_reminders()
		for proposal in (early, past, submitted):
			self.assertEqual(self.reminder_logs(proposal), [], proposal.name)

	def test_approved_proposal_not_yet_submitted_still_gets_reminders(self):
		proposal = self.approved(self.proposal())
		proposals.send_deadline_reminders()
		self.assertIn(f"Employee:{self.pi}", self.reminder_logs(proposal))

	# report
	def test_pipeline_lists_the_colleges_proposals_by_stage(self):
		draft = self.proposal()
		under_review = self.proposal()
		request_approval("Research Proposal", under_review.name)
		submitted = self.approved(self.proposal())
		submitted.submit_to_agency()
		_columns, rows = pipeline.execute({"company": COLLEGE})
		stages = {row["proposal"]: row["stage"] for row in rows}
		self.assertEqual(stages[draft.name], "Draft")
		self.assertEqual(stages[under_review.name], "Under Internal Review")
		self.assertEqual(stages[submitted.name], "Submitted to Agency")
		self.assertEqual(pipeline.execute({"company": OTHER})[1], [])
		self.assertEqual(pipeline.execute({})[1], [])

	# T13 review carry-overs (P3-T14)
	def test_principal_reads_only_own_college_and_pi_reads_a_colleague_named_proposal(self):
		other_consumables = make_account(OTHER, OTHER_ABBR, "RP Consumables", "Indirect Expenses")
		shared = self.make_head("RPT Shared Head", [(COLLEGE, frappe.db.get_value("Grant Budget Head Account", {"parent": self.consumables}, "account")), (OTHER, other_consumables)])
		self.make_settings(OTHER, OTHER_ABBR)
		other_call = self.make_call(add_days(today(), 3), scheme=self.make_scheme("RPT Shared Grant", [shared]))
		elsewhere = self.proposal(
			company=OTHER, call=other_call, principal_investigator=self.make_employee("Far", OTHER), co_investigators=[],
			budget=[(shared, 1000)],
		)  # fmt: skip
		colleague = self.make_employee("Colleague", COLLEGE)
		named = self.proposal(co_investigators=[{"employee": colleague}])  # PI_USER's employee is the PI
		colleagues_own = self.proposal(principal_investigator=colleague, co_investigators=[])
		if not frappe.db.exists("User Permission", {"user": PI_USER, "allow": "Employee"}):
			frappe.get_doc({"doctype": "User Permission", "user": PI_USER, "allow": "Employee", "for_value": self.pi}).insert()

		for user in (REVIEWER, PI_USER):
			frappe.set_user(user)
			visible = set(frappe.get_list("Research Proposal", pluck="name"))
			self.assertNotIn(elsewhere.name, visible, user)
			self.assertFalse(frappe.has_permission("Research Proposal", "read", elsewhere.name), user)
			self.assertTrue({named.name, colleagues_own.name} <= visible, user)
			self.assertTrue(frappe.has_permission("Research Proposal", "read", named.name), user)
			frappe.set_user("Administrator")

	def test_co_investigator_cannot_review_the_proposal(self):
		proposal = self.proposal()
		request = request_approval("Research Proposal", proposal.name)
		self.assertNotIn(CO_PI_USER, frappe.get_all("Approval Request Approver", {"parent": request}, pluck="user"))
		frappe.set_user(CO_PI_USER)  # a Principal, but a co-PI of the proposal
		with self.assertRaisesRegex(frappe.PermissionError, "own approval request"):
			approve(request, None)

	def test_no_reminder_once_internal_review_rejected_it(self):
		proposal = self.proposal()
		request = request_approval("Research Proposal", proposal.name)
		frappe.set_user(REVIEWER)
		reject(request, "Out of scope")
		frappe.set_user("Administrator")
		proposals.send_deadline_reminders()
		self.assertEqual(self.reminder_logs(proposal), [])

	def test_agency_submission_and_outcome_leave_an_audit_comment(self):
		proposal = self.approved(self.proposal())
		proposal.submit_to_agency(agency_reference="DST/RPT/9")
		proposal.reload().record_outcome("Not Sanctioned")
		comments = frappe.get_all(
			"Comment", {"reference_doctype": "Research Proposal", "reference_name": proposal.name, "comment_type": "Info"},
			pluck="content",
		)  # fmt: skip
		self.assertTrue(any("DST/RPT/9" in c for c in comments), comments)
		self.assertTrue(any("Not Sanctioned" in c for c in comments), comments)

	def test_agency_fields_cannot_be_edited_after_submit(self):
		proposal = self.approved(self.proposal())
		proposal.status = "Sanctioned"
		with self.assertRaisesRegex(frappe.ValidationError, "Submit to Agency"):
			proposal.save()
		proposal.reload()
		proposal.outcome = "Sanctioned"
		with self.assertRaisesRegex(frappe.ValidationError, "Submit to Agency"):
			proposal.save()
