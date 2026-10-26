"""L-03 tests (M04-10): reporting deadlines, late joining approval, temporary clearance, no-show referral and the
cancellation (with the advance refund) of an admitted student who never joined; the joining key repairs (M04-09)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, today

from campus.admissions import admit as admit_module
from campus.admissions import documents, reporting
from campus.admissions.api import grant_temporary_clearance
from campus.admissions.report.admission_no_shows import admission_no_shows
from campus.campus_messaging.setup import DOCUMENT_PENDING_EN
from campus.campus_platform import bulk
from campus.campus_platform.approvals import approve, request_approval
from campus.patches import (
	clear_legacy_attendance_start_dates,
	document_reminder_due_date,
	repair_joining_keys,
)
from campus.student_services.api import attendance_start, student_window
from campus.tests.approval_fixtures import drop_policies
from campus.tests.factories import make_user
from campus.tests.test_admission_flow import (
	COLLEGE,
	OC,
	OFFICER,
	PLAIN,
	PROGRAM,
	QUOTA,
	YEAR,
	AdmitTestCase,
	ensure_customer_party_type,
)

PRINCIPAL = "late-principal@example.com"
LATE = "Late Joining Request"
TC = "Transfer Certificate"


class ReportingTestCase(AdmitTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Role", "Principal"):
			frappe.get_doc({"doctype": "Role", "role_name": "Principal", "desk_access": 1}).insert()
		make_user(PRINCIPAL, [COLLEGE])
		frappe.get_doc("User", PRINCIPAL).add_roles("Principal")

	def setUp(self):
		super().setUp()
		self.settings(reporting_deadline=None, no_show_grace_days=0, program_reporting_deadlines=[])

	def admitted(self, **kwargs):
		applicant = self.applicant(**kwargs)
		return applicant, self.admit_as_officer(applicant)["student"]

	def as_officer(self, function, *args, **kwargs):
		frappe.set_user(OFFICER)
		try:
			return function(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def advance(self, student, amount):
		"""Pre-joining money: a Payment Entry (Receive) against the student's customer, settling no invoice."""
		ensure_customer_party_type()
		payment = frappe.get_doc(
			{
				"doctype": "Payment Entry", "payment_type": "Receive", "company": COLLEGE, "posting_date": today(),
				"party_type": "Customer", "party": frappe.db.get_value("Student", student, "customer"),
				"paid_from": self.structure.receivable_account, "paid_to": self.accounts["bank"], "paid_amount": amount,
				"received_amount": amount, "reference_no": "ADV-UTR", "reference_date": today(),
			}
		)  # fmt: skip
		return payment.insert().submit().name


class TestReportingDeadline(ReportingTestCase):
	def test_admit_stamps_the_deadline_in_force_and_leaves_the_joining_date_to_the_joining(self):
		self.settings(reporting_deadline=add_days(today(), 5))
		_applicant, round_student = self.admitted()
		self.settings(
			program_reporting_deadlines=[{"program": PROGRAM, "reporting_deadline": add_days(today(), 9)}]
		)
		_applicant, program_student = self.admitted()
		self.settings(
			reporting_deadline=add_days(today(), 20), program_reporting_deadlines=[]
		)  # the next round
		stamped = lambda s: str(frappe.db.get_value("Student", s, "oc_reporting_deadline"))  # noqa: E731
		self.assertEqual(
			(stamped(round_student), stamped(program_student)), (add_days(today(), 5), add_days(today(), 9))
		)
		self.assertIsNone(frappe.db.get_value("Student", round_student, "joining_date"))

	def test_joining_by_the_deadline_needs_no_approval(self):
		self.settings(reporting_deadline=today())
		applicant, student = self.admitted()
		self.join_as_officer(applicant)
		self.assertEqual(frappe.db.get_value("Student", student, "oc_academic_status"), "Active")
		self.assertEqual(str(frappe.db.get_value("Student", student, "joining_date")), today())


class TestLateJoining(ReportingTestCase):
	def setUp(self):
		super().setUp()
		drop_policies(LATE)
		frappe.get_doc(
			{
				"doctype": "Approval Policy", "policy_name": "Late Joining Test", "document_type": LATE,
				"enabled": 1, "on_final_action": "Submit", "levels": [{"title": "Principal approval", "approver_type": "User", "approver": PRINCIPAL}],
			}
		).insert()  # fmt: skip
		self.settings(reporting_deadline=add_days(today(), -10))
		self.applicant_name, self.student = self.admitted()  # stamped with the past deadline
		frappe.db.set_value(
			"Lifecycle Transition", {"student": self.student}, "effective_date", add_days(today(), -12)
		)  # admitted then

	def request(self, joining_date, reason="Hospitalised during the reporting week"):
		doc = frappe.get_doc(
			{
				"doctype": LATE,
				"applicant": self.applicant_name,
				"joining_date": joining_date,
				"reason": reason,
			}
		)
		return self.as_officer(doc.insert)

	def approve_fully(self, doc):
		request = self.as_officer(request_approval, LATE, doc.name)
		frappe.set_user(PRINCIPAL)
		try:
			approve(request)
		finally:
			frappe.set_user("Administrator")
		return frappe.get_doc(LATE, doc.name)

	def test_a_late_joining_needs_an_approved_request_for_that_date(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Late Joining Request"):
			self.join_as_officer(self.applicant_name)
		effective = add_days(today(), -2)
		doc = self.request(effective)
		self.assertEqual((doc.student, str(doc.reporting_deadline)), (self.student, add_days(today(), -10)))
		with self.assertRaisesRegex(frappe.ValidationError, "Late Joining Request"):
			self.join_as_officer(self.applicant_name, joining_date=effective)  # requested, not approved yet
		doc = self.approve_fully(doc)
		self.assertEqual(doc.docstatus, 1)
		with self.assertRaisesRegex(frappe.ValidationError, "is for joining on"):
			self.join_as_officer(self.applicant_name)  # today, not the approved date
		result = self.join_as_officer(self.applicant_name, joining_date=effective)
		self.assertEqual(
			str(frappe.db.get_value("Program Enrollment", result["program_enrollment"], "enrollment_date")),
			effective,
		)
		self.assertEqual(frappe.db.get_value("Student", self.student, "oc_academic_status"), "Active")

	def test_a_request_is_only_for_a_late_date_one_at_a_time_and_needs_a_reason(self):
		with self.assertRaisesRegex(frappe.ValidationError, "no approval is needed"):
			self.request(add_days(today(), -10))
		with self.assertRaises(frappe.MandatoryError):
			self.request(today(), reason="")
		self.request(today())
		with self.assertRaisesRegex(frappe.ValidationError, "already has a Late Joining Request"):
			self.request(add_days(today(), -1))

	def test_a_pending_request_cannot_be_submitted_directly(self):
		doc = self.request(today())
		self.as_officer(request_approval, LATE, doc.name)
		with self.assertRaisesRegex(frappe.ValidationError, "awaiting approval"):
			self.as_officer(frappe.get_doc(LATE, doc.name).submit)
		self.assertEqual(frappe.db.get_value(LATE, doc.name, "docstatus"), 0)

	def test_an_approved_late_joining_is_not_a_no_show(self):
		listed = lambda: self.student in [row.student for row in reporting.no_shows(company=COLLEGE)]  # noqa: E731
		self.assertTrue(listed())  # deadline -10, no grace
		self.approve_fully(self.request(today()))
		self.assertFalse(listed())
		self.assertTrue(
			self.student
			in [row.student for row in reporting.no_shows(as_of=add_days(today(), 1), company=COLLEGE)]
		)

	def test_without_a_policy_a_request_is_never_submitted(self):
		doc = self.request(today())
		drop_policies(LATE)
		with self.assertRaisesRegex(frappe.ValidationError, "No Approval Policy"):
			self.as_officer(request_approval, LATE, doc.name)
		self.assertEqual(frappe.db.get_value(LATE, doc.name, "docstatus"), 0)


class TestTemporaryClearance(ReportingTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Admission Document Rule")
		frappe.get_doc(
			{
				"doctype": "Admission Document Rule",
				"document_type": TC,
				"mandatory": 1,
				"verification_needed": 1,
			}
		).insert()

	def applicant_with_mobile(self):
		applicant = self.applicant()
		frappe.db.set_value("Student Applicant", applicant, "student_mobile_number", "+919876511111")
		return applicant

	def clear(self, applicant, due, documents_=(TC,), reason="Original with the previous college"):
		return self.as_officer(grant_temporary_clearance, applicant, list(documents_), due, reason)

	def test_a_cleared_student_is_admitted_and_joins_with_the_document_pending_and_is_reminded(self):
		applicant = self.applicant_with_mobile()
		with self.assertRaisesRegex(frappe.ValidationError, "incomplete mandatory documents"):
			self.admit_as_officer(applicant)
		due = add_days(today(), 15)
		self.assertEqual(self.clear(applicant, due), {"cleared_until": due, "documents": [TC]})
		student = self.admit_as_officer(applicant)["student"]
		self.join_as_officer(applicant)
		self.assertEqual(frappe.db.get_value("Student", student, "oc_academic_status"), "Active")
		item = next(i for i in documents.reminder_items() if i["applicant"] == applicant)
		self.assertEqual((item["documents"], item["due_date"]), ([TC], due))
		run = frappe._dict(get_parameters=lambda: {"day": today()})
		with patch.object(documents, "send") as send:
			documents.send_reminder(item, run)
		self.assertEqual(
			send.call_args.kwargs["context"], {"documents": TC, "dedupe_token": today(), "due_date": due}
		)
		frappe.db.set_value("Applicant Document", {"parent": applicant}, "status", "Verified")
		self.assertFalse([i for i in documents.reminder_items() if i["applicant"] == applicant])

	def test_the_reminder_prints_the_due_date_and_the_patch_updates_the_seeded_text(self):
		body = lambda language: frappe.db.get_value(  # noqa: E731
			"Message Template Body", {"parent": documents.REMINDER_EVENT, "language": language}, "body"
		)
		old = document_reminder_due_date.FIRST_SEED["en"][0]
		frappe.db.set_value(
			"Message Template Body", {"parent": documents.REMINDER_EVENT, "language": "en"}, "body", old
		)
		frappe.db.set_value(
			"Message Template Body", {"parent": documents.REMINDER_EVENT, "language": "ta"}, "body", "Edited"
		)
		document_reminder_due_date.execute()
		self.assertEqual((body("en"), body("ta")), (DOCUMENT_PENDING_EN, "Edited"))  # an edited body is kept
		render = lambda context: frappe.render_template(DOCUMENT_PENDING_EN, {"context": context})  # noqa: E731
		self.assertIn("Due by 2026-11-06.", render({"documents": TC, "due_date": "2026-11-06"}))
		self.assertNotIn("Due by", render({"documents": TC}))

	def test_an_expired_clearance_no_longer_clears(self):
		applicant = self.applicant()
		self.clear(applicant, today())
		self.admit_as_officer(applicant)
		frappe.db.set_value(
			"Applicant Document", {"parent": applicant}, "cleared_until", add_days(today(), -1)
		)
		with self.assertRaisesRegex(frappe.ValidationError, "incomplete mandatory documents"):
			self.join_as_officer(applicant)

	def test_only_officers_clear_only_pending_documents_and_never_by_editing_the_checklist(self):
		applicant = self.applicant()
		frappe.set_user(PLAIN)
		try:
			with self.assertRaises(frappe.PermissionError):
				grant_temporary_clearance(applicant, [TC], today(), "x")
		finally:
			frappe.set_user("Administrator")
		with self.assertRaisesRegex(frappe.ValidationError, "not a pending mandatory document"):
			self.clear(applicant, today(), documents_=("Community Certificate",))
		with self.assertRaisesRegex(frappe.ValidationError, "past"):
			self.clear(applicant, add_days(today(), -1))
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			self.clear(applicant, today(), reason=" ")
		doc = frappe.get_doc("Student Applicant", applicant)
		doc.oc_documents[0].cleared_until = add_days(today(), 30)
		with self.assertRaisesRegex(frappe.ValidationError, "not by editing the checklist"):
			doc.save()


class TestNoShows(ReportingTestCase):
	def setUp(self):
		super().setUp()
		self.settings(reporting_deadline=add_days(today(), -5), no_show_grace_days=3)

	def refer(self):
		with patch.object(frappe.db, "commit"), patch.object(bulk, "enqueue_run"):
			run = reporting.refer_no_shows()
			if run:
				bulk.process_bulk_run(run)
		return run

	def test_after_the_deadline_and_grace_an_unjoined_student_is_listed_and_referred_not_cancelled(self):
		_applicant, late = self.admitted()
		joined_applicant, joined = self.admitted()
		self.settings(reporting_deadline=add_days(today(), -2))
		_applicant, in_grace = self.admitted()  # deadline -2 + 3 grace days: not yet a no-show
		self.settings(reporting_deadline=add_days(today(), -5))
		frappe.db.set_value(
			"Student", joined, "oc_academic_status", "Active"
		)  # joined (status is all the list reads)
		listed = [row.student for row in reporting.no_shows(company=COLLEGE)]
		self.assertIn(late, listed)
		self.assertNotIn(joined, listed)
		self.assertNotIn(in_grace, listed)
		self.assertTrue(self.refer())
		drafts = frappe.get_all(
			"Admission Cancellation", {"student": late}, ["name", "docstatus", "reason", "program_enrollment"]
		)
		self.assertEqual(len(drafts), 1)
		self.assertEqual((drafts[0].docstatus, drafts[0].program_enrollment), (0, None))
		self.assertIn("No-show", drafts[0].reason)
		self.assertEqual(
			frappe.db.get_value("Student", late, "oc_academic_status"), "Admitted"
		)  # nothing cancelled
		self.assertFalse(frappe.db.exists("Admission Cancellation", {"student": in_grace}))
		self.refer()  # the next day: already referred
		self.assertEqual(frappe.db.count("Admission Cancellation", {"student": late}), 1)
		frappe.set_user(OFFICER)
		try:
			rows = admission_no_shows.execute({"company": COLLEGE})[1]
		finally:
			frappe.set_user("Administrator")
		row = next(r for r in rows if r.student == late)
		self.assertEqual((row.cancellation, str(row.referral_date)), (drafts[0].name, add_days(today(), -1)))

	def test_a_referred_no_show_who_joins_loses_the_draft_cancellation(self):
		applicant, student = self.admitted()
		self.refer()
		self.assertTrue(frappe.db.exists("Admission Cancellation", {"student": student, "docstatus": 0}))
		frappe.db.set_value(
			"Student", student, "oc_reporting_deadline", today()
		)  # e.g. the deadline was extended
		self.join_as_officer(applicant)
		self.assertFalse(frappe.db.exists("Admission Cancellation", {"student": student}))

	def test_the_daily_job_is_scheduled(self):
		self.assertIn(
			"campus.admissions.reporting.refer_no_shows", frappe.get_hooks("scheduler_events")["daily"]
		)


class TestCancellationBeforeJoining(ReportingTestCase):
	def cancel(self, student, submit=True, enrollment=None):
		doc = frappe.get_doc(
			{
				"doctype": "Admission Cancellation", "student": student, "program_enrollment": enrollment,
				"cancellation_date": today(), "reason": "No-show",
			}
		)  # fmt: skip
		frappe.set_user(OFFICER)
		try:
			doc.insert()
			return doc.submit() if submit else doc
		finally:
			frappe.set_user("Administrator")

	def test_a_no_show_is_cancelled_and_the_advance_refunded_once(self):
		applicant, student = self.admitted()
		self.advance(student, 10000)
		self.advance(student, 2500)
		counts = self.counts()
		doc = self.cancel(student)
		self.assertEqual((flt(doc.amount_paid), flt(doc.cash_refund), flt(doc.deduction)), (12500, 12500, 0))
		self.assertIsNone(doc.credit_note)
		payment = frappe.get_doc("Payment Entry", doc.payment_entry)
		customer = frappe.db.get_value("Student", student, "customer")
		self.assertEqual(
			(payment.docstatus, payment.payment_type, payment.party, flt(payment.paid_amount), payment.references),
			(0, "Pay", customer, 12500, []),
		)  # fmt: skip
		state = frappe.db.get_value("Student", student, ["oc_academic_status", "enabled"], as_dict=True)
		self.assertEqual((state.oc_academic_status, state.enabled), ("Cancelled", 0))
		self.assertEqual(
			frappe.db.get_value("Student Applicant", applicant, "application_status"), "Rejected"
		)
		self.assertEqual(self.counts(), counts)  # no enrollment, invoice or customer made or released
		payment.submit()  # Accounts pays the refund once
		self.assertEqual(frappe.db.get_value("Payment Entry", payment.name, "docstatus"), 1)
		with self.assertRaisesRegex(frappe.ValidationError, "Cancelled"):
			self.cancel(student)  # once
		with self.assertRaisesRegex(frappe.ValidationError, "cannot join"):
			self.join_as_officer(applicant)

	def test_a_submitted_refund_is_not_refunded_again(self):
		_applicant, student = self.admitted()
		self.advance(student, 4000)
		customer = frappe.db.get_value("Student", student, "customer")
		self.assertEqual(reporting_advance(customer), 4000)
		refund = frappe.get_doc(
			{
				"doctype": "Payment Entry", "payment_type": "Pay", "company": COLLEGE, "posting_date": today(),
				"party_type": "Customer", "party": customer, "paid_from": self.accounts["bank"],
				"paid_to": self.structure.receivable_account, "paid_amount": 1500, "received_amount": 1500,
				"reference_no": "REF-UTR", "reference_date": today(),
			}
		)  # fmt: skip
		refund.insert().submit()
		self.assertEqual(flt(self.cancel(student, submit=False).cash_refund), 2500)

	def refund_entry(self, student, amount):
		customer = frappe.db.get_value("Student", student, "customer")
		return frappe.get_doc(
			{
				"doctype": "Payment Entry", "payment_type": "Pay", "company": COLLEGE, "posting_date": today(),
				"party_type": "Customer", "party": customer, "paid_from": self.accounts["bank"],
				"paid_to": self.structure.receivable_account, "paid_amount": amount, "received_amount": amount,
				"reference_no": "REF-UTR", "reference_date": today(),
			}
		)  # fmt: skip

	def test_the_advance_refund_is_paid_once_and_a_copy_is_refused(self):
		_applicant, student = self.admitted()
		self.advance(student, 6000)
		doc = self.cancel(student)
		draft = frappe.get_doc("Payment Entry", doc.payment_entry)
		self.assertEqual(draft.oc_admission_cancellation, doc.name)
		copy = frappe.copy_doc(draft).insert()
		self.assertEqual(copy.oc_admission_cancellation, doc.name)  # the link travels with a copy
		draft.submit()
		self.assertEqual(frappe.db.get_value("Payment Entry", draft.name, "docstatus"), 1)
		with self.assertRaisesRegex(
			frappe.ValidationError, f"{draft.name} already refunds the advance of {doc.name}"
		):
			copy.reload().submit()
		self.assertEqual(frappe.db.get_value("Payment Entry", copy.name, "docstatus"), 0)

	def test_the_draft_refund_is_refused_after_a_manual_refund(self):
		_applicant, student = self.admitted()
		self.advance(student, 4000)
		doc = self.cancel(student)
		self.refund_entry(student, 1500).insert().submit()  # Accounts refunded part of it another way
		draft = frappe.get_doc("Payment Entry", doc.payment_entry)
		with self.assertRaisesRegex(frappe.ValidationError, "of the advance is left unrefunded"):
			draft.submit()
		self.assertEqual(frappe.db.get_value("Payment Entry", draft.name, "docstatus"), 0)

	def test_a_scholarship_disbursement_is_not_refunded_as_advance(self):
		_applicant, student = self.admitted()
		self.advance(student, 3000)
		disbursed = self.advance(student, 7000)
		frappe.get_doc(
			{
				"doctype": "Scholarship Disbursement", "parent": "SCH-TEST", "parenttype": "Scholarship Application",
				"parentfield": "disbursements", "voucher_type": "Payment Entry", "voucher": disbursed, "amount": 7000,
			}
		).db_insert()  # fmt: skip
		self.assertEqual(flt(self.cancel(student, submit=False).cash_refund), 3000)

	def test_no_advance_means_no_payment_entry(self):
		_applicant, student = self.admitted()
		doc = self.cancel(student)
		self.assertEqual((flt(doc.cash_refund), doc.payment_entry), (0, None))
		self.assertEqual(frappe.db.get_value("Student", student, "oc_academic_status"), "Cancelled")

	def test_a_joined_student_is_cancelled_only_with_their_enrollment(self):
		result = self.admit_and_join(self.applicant())
		with self.assertRaisesRegex(frappe.ValidationError, "name the Program Enrollment"):
			self.cancel(result["student"], submit=False)


def amend(enrollment):
	"""Cancel `enrollment` and submit its amendment, as the desk's Amend does."""
	enrollment.flags.ignore_links = True  # the fee invoice links to it
	enrollment.cancel()
	amended = frappe.copy_doc(enrollment, ignore_no_copy=False)
	amended.update({"amended_from": enrollment.name, "docstatus": 0})
	amended.insert()
	return amended.submit()


def reporting_advance(customer):
	from campus.campus_finance.api import unallocated_advance

	return unallocated_advance(customer, COLLEGE)


class TestJoiningKeys(ReportingTestCase):
	def legacy_enrollment(self, student):
		enrollment = frappe.get_doc(
			{"doctype": "Program Enrollment", "student": student, "program": PROGRAM, "academic_year": YEAR, "enrollment_date": today(),
			 "student_category": OC, "oc_admission_quota": QUOTA}
		)  # fmt: skip
		enrollment.flags.legacy_import = True
		return enrollment.insert().submit()

	def admitted_with_a_cancelled_keyed_enrollment(self):
		"""What the first joining_gate patch left: the applicant's key on a cancelled enrollment of an Admitted student."""
		applicant, student = self.admitted()
		enrollment = self.legacy_enrollment(student)
		enrollment.cancel()
		frappe.db.set_value("Program Enrollment", enrollment.name, "oc_joining_key", applicant)
		return applicant, student, enrollment.name

	def test_the_repair_patch_clears_the_cancelled_key_and_the_student_joins(self):
		applicant, student, cancelled = self.admitted_with_a_cancelled_keyed_enrollment()
		for _run in range(2):  # idempotent
			repair_joining_keys.execute()
		self.assertIsNone(frappe.db.get_value("Program Enrollment", cancelled, "oc_joining_key"))
		result = self.join_as_officer(applicant)
		self.assertEqual(
			frappe.db.get_value("Program Enrollment", result["program_enrollment"], "oc_joining_key"),
			applicant,
		)
		self.assertEqual(frappe.db.get_value("Student", student, "oc_academic_status"), "Active")

	def test_a_joining_releases_a_key_left_on_a_cancelled_enrollment(self):
		applicant, _student, cancelled = self.admitted_with_a_cancelled_keyed_enrollment()
		result = self.join_as_officer(applicant)
		self.assertNotEqual(result["program_enrollment"], cancelled)
		self.assertIsNone(frappe.db.get_value("Program Enrollment", cancelled, "oc_joining_key"))

	def test_an_amended_joining_enrollment_keeps_the_joining(self):
		applicant = self.applicant()
		first = self.admit_and_join(applicant)
		original = frappe.get_doc("Program Enrollment", first["program_enrollment"])
		amended = amend(original)
		self.assertIsNone(frappe.db.get_value("Program Enrollment", original.name, "oc_joining_key"))
		self.assertEqual(frappe.db.get_value("Program Enrollment", amended.name, "oc_joining_key"), applicant)
		self.assertEqual(
			self.join_as_officer(applicant)["program_enrollment"], amended.name
		)  # a retry returns it

	def test_the_repair_patch_moves_the_key_to_the_amendment(self):
		applicant = self.applicant()
		first = self.admit_and_join(applicant)
		original = frappe.get_doc("Program Enrollment", first["program_enrollment"])
		amended = amend(original)
		frappe.db.set_value(
			"Program Enrollment", amended.name, "oc_joining_key", None
		)  # amended before the hook existed
		frappe.db.set_value("Program Enrollment", original.name, "oc_joining_key", applicant)
		repair_joining_keys.execute()
		self.assertEqual(frappe.db.get_value("Program Enrollment", amended.name, "oc_joining_key"), applicant)
		self.assertIsNone(frappe.db.get_value("Program Enrollment", original.name, "oc_joining_key"))


class TestJoiningDateFloor(ReportingTestCase):
	def test_a_joining_before_the_last_change_is_refused_before_any_seat_or_number_is_taken(self):
		applicant, student = self.admitted()
		frappe.db.set_value("Lifecycle Transition", {"student": student}, "effective_date", today())
		with (
			patch("campus.admissions.joining.seats.check_seat_available") as seat,
			patch("campus.admissions.joining.numbers.next_number") as number,
		):
			with self.assertRaisesRegex(frappe.ValidationError, "before the last status change"):
				self.join_as_officer(applicant, joining_date=add_days(today(), -1))
		seat.assert_not_called()
		number.assert_not_called()

	def test_a_busy_desk_names_what_to_retry(self):
		deadlock = frappe.QueryDeadlockError("deadlock found")
		with patch.object(frappe, "only_for"), patch.object(frappe.db, "rollback"):
			with patch.object(admit_module, "admit_once", side_effect=[deadlock, deadlock]):
				with self.assertRaisesRegex(frappe.ValidationError, "Please try admitting APP-9 again"):
					admit_module.admit("APP-9")
			from campus.admissions import joining

			with patch.object(joining, "join_once", side_effect=[deadlock, deadlock]):
				with self.assertRaisesRegex(
					frappe.ValidationError, "Please try confirming the joining of APP-9 again"
				):
					joining.confirm_joining("APP-9")


class TestAttendanceStart(ReportingTestCase):
	"""L-07 review I-3: only the joining confirmation writes the attendance start date (it narrows the denominator)."""

	def legacy_enrollment(self, student, enrollment_date):
		enrollment = frappe.get_doc(
			{"doctype": "Program Enrollment", "student": student, "program": PROGRAM, "academic_year": YEAR,
			 "enrollment_date": enrollment_date, "student_category": OC, "oc_admission_quota": QUOTA}
		)  # fmt: skip
		enrollment.flags.legacy_import = True
		return enrollment.insert().submit()

	def test_a_legacy_enrollment_dated_mid_term_counts_attendance_from_the_term_start(self):
		_applicant, student = self.admitted()
		term = (add_days(today(), -30), add_days(today(), 60))
		enrollment = self.legacy_enrollment(student, today())
		self.assertIsNone(enrollment.oc_attendance_start_date)
		self.assertIsNone(attendance_start(student))
		self.assertEqual(student_window(student, term), term)

	def test_the_patch_clears_start_dates_filled_before_the_joining_gate_and_keeps_the_joinings(self):
		gate_ran = frappe.db.get_value("Patch Log", {"patch": "campus.patches.joining_gate"}, "creation")
		if not gate_ran:
			gate_ran = (
				frappe.get_doc({"doctype": "Patch Log", "patch": "campus.patches.joining_gate"})
				.insert()
				.creation
			)
		_applicant, legacy_student = self.admitted()
		legacy = self.legacy_enrollment(legacy_student, today())
		frappe.db.set_value(
			"Program Enrollment",
			legacy.name,
			{"creation": add_days(gate_ran, -1), "oc_attendance_start_date": today()},
			update_modified=False,
		)  # what the first joining_gate fill left on an enrollment made before it
		applicant = self.applicant()
		joined = self.admit_and_join(applicant)["program_enrollment"]
		for _run in range(2):  # idempotent
			clear_legacy_attendance_start_dates.execute()
		self.assertIsNone(frappe.db.get_value("Program Enrollment", legacy.name, "oc_attendance_start_date"))
		self.assertEqual(
			str(frappe.db.get_value("Program Enrollment", joined, "oc_attendance_start_date")), today()
		)
