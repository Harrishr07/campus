"""M05-02 integration tests: attendance marks, leave kinds, the Attendance Eligibility Run and Condonation Request."""

from unittest.mock import patch

import frappe

from campus.campus_platform.approvals import approve, request_approval
from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.student_services import condonation_fee, eligibility_run
from campus.student_services.api import attendance_marks, attendance_summary, eligibility_status, summarise, term_window
from campus.tests.approval_fixtures import level
from campus.tests.broadcast_fixtures import make_guardian
from campus.tests.factories import make_company, make_user
from campus.tests.finance_factories import make_finance_company
from campus.tests.test_attendance_eligibility import approved_leave, make_offering, make_term, mark, mark_pattern
from campus.tests.test_regulation import enroll, make_program, make_regulation, make_student, make_year
from campus.tests.utils import CampusTestCase

COLLEGE = "Condonation Test College"
PROGRAM = "Condonation Test BE"
COURSES = ["CND X", "CND Y"]
POLICY = "CND Test Policy"
STAFF = "cnd-staff@example.com"
DEAN = "cnd-dean@example.com"
APPROVER = "cnd-approver@example.com"
STUDENT_USER = "cnd-student@example.com"
BANDS = [(80, 85, 2), (86, 90, 3), (91, 95, 4), (96, None, 5)]
R2026 = {
	"formula": "course_average", "overall_min_pct": 80, "medical_band_min_pct": 70, "per_course_min_pct": 75,
	"od_counts": 1, "medical_counts": 1, "condonation_fee": 0,
	"mark_bands": [{"from_pct": lo, "to_pct": hi, "marks": marks} for lo, hi, marks in BANDS],
}  # fmt: skip
R2022 = {
	"formula": "sum_based", "overall_min_pct": 75, "medical_band_min_pct": 65, "per_course_min_pct": 0,
	"od_counts": 1, "medical_counts": 1,
}  # fmt: skip


def login(email, *roles):
	make_user(email, [COLLEGE])
	user = frappe.get_doc("User", email)
	user.roles = []
	for role in roles:
		user.append("roles", {"role": role})
	user.save(ignore_permissions=True)


def condonation(student, term, **values):
	return frappe.get_doc(
		{
			"doctype": "Condonation Request", "student": student, "academic_term": term, "evidence_kind": "Medical",
			"evidence": "/files/certificate.pdf", "reason": "Dengue, hospitalised", **values,
		}
	)  # fmt: skip


def inline_bulk(run_type, items, handler, parameters=None, **_ignored):
	"""run_bulk stand-in: the real runner commits per chunk; run the handler for each item in this transaction."""
	run = frappe._dict(get_parameters=lambda: parameters)
	for item in items:
		frappe.get_attr(handler)(item, run)
	return None


class TestAttendanceCondonation(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_finance_company(COLLEGE, "CNDT")
		for year in ("2022", "2026"):
			make_year(year)
		make_program(PROGRAM, COLLEGE)
		cls.rule26 = make_rule("R2026-CND", "2026", R2026)
		cls.rule22 = make_rule("R2022-CND", "2022", R2022)
		cls.term = make_term()
		students = {
			name: make_student(name, COLLEGE, batch)
			for name, batch in (("Cndband", "2026"), ("Cndshort", "2026"), ("Cndok", "2026"), ("Cndod", "2026"), ("Cnd22", "2022"))
		}
		for student in students.values():
			enroll(student, PROGRAM, "2022", submit=True)
		cls.band, cls.short, cls.ok, cls.od, cls.s22 = (students[n].name for n in ("Cndband", "Cndshort", "Cndok", "Cndod", "Cnd22"))
		cls.groups = [make_offering(c, PROGRAM, COLLEGE, list(students.values()), cls.term) for c in COURSES]
		leave = approved_leave(cls.band, "Medical")
		od_leave = approved_leave(cls.od, "On Duty")
		pattern = {  # student: ([course X present, absent, leave], [course Y present, absent])
			cls.band: ((7, 2, 1, leave), (8, 2)),  # raw 70 / 80; medical leave lifts X to 80: medical band under R2026
			cls.short: ((5, 5, 0, None), (5, 5)),  # 50%: detained
			cls.ok: ((9, 1, 0, None), (9, 1)),  # 90%: eligible
			cls.od: ((7, 2, 1, od_leave), (8, 2)),  # the leave is On Duty: counts as attended
			cls.s22: ((9, 1, 0, None), (9, 1)),
		}
		for student, (x, y) in pattern.items():
			mark_pattern(student, cls.groups[0], present=x[0], absent=x[1], leave=x[2], leave_application=x[3])
			mark_pattern(student, cls.groups[1], present=y[0], absent=y[1])
		login(STAFF, "Academics User")
		login(DEAN, "Dean Academics")
		login(APPROVER, "Academics User")
		login(STUDENT_USER, "Student")
		frappe.db.set_value("Student", cls.band, "user", STUDENT_USER)

	def setUp(self):
		frappe.db.savepoint("condonation_test")
		self.addCleanup(frappe.db.rollback, save_point="condonation_test")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		frappe.get_doc(
			{
				"doctype": "Approval Policy", "policy_name": POLICY, "document_type": "Condonation Request",
				"company": COLLEGE, "levels": [level("User", APPROVER, title="HOD")],
			}
		).insert()  # fmt: skip

	def approved_condonation(self, student=None):
		doc = condonation(student or self.band, self.term).insert()
		request = request_approval("Condonation Request", doc.name)
		frappe.set_user(APPROVER)
		approve(request, None)
		frappe.set_user("Administrator")
		doc.reload()
		return doc

	# attendance marks and leave kinds

	def test_attendance_marks_come_from_the_regulation_bands(self):
		self.assertEqual(attendance_marks(self.ok, self.groups[0])["marks"], 3)  # 90% under the R2026 bands
		result = attendance_marks(self.band, self.groups[0])
		self.assertEqual((result["pct"], result["marks"], result["conducted"], result["attended"]), (70.0, 0, 10, 7))
		self.assertEqual(attendance_marks(self.s22, self.groups[0])["marks"], 0)  # R2022 has no bands

	def test_marks_follow_a_changed_band(self):
		frappe.db.set_value("Attendance Mark Band", {"parent": self.rule26.name, "from_pct": 86}, "marks", 4)
		self.assertEqual(attendance_marks(self.ok, self.groups[0])["marks"], 4)

	def test_on_duty_counts_as_attended_only_when_the_rule_says_so(self):
		row = lambda: attendance_summary(self.od, self.term)["offerings"][0]  # noqa: E731
		self.assertEqual((row()["attended"], row()["leave"]), (8, 0))
		frappe.db.set_value("Attendance Rule", self.rule26.name, "od_counts", 0)
		self.assertEqual((row()["attended"], row()["leave"]), (7, 0))

	def test_medical_leave_counts_only_when_the_rule_says_so(self):
		self.assertEqual(eligibility_status(self.band, self.term), "Medical band")
		frappe.db.set_value("Attendance Rule", self.rule26.name, "medical_counts", 0)
		self.assertEqual(eligibility_status(self.band, self.term), "Shortage")

	def test_plain_leave_never_counts(self):
		frappe.db.set_value("Student Leave Application", {"student": self.band}, "oc_leave_kind", "Leave")
		self.assertEqual(eligibility_status(self.band, self.term), "Shortage")

	def test_medical_and_on_duty_leave_need_their_certificate_to_submit(self):
		leave = frappe.get_doc(
			{
				"doctype": "Student Leave Application", "student": self.band, "from_date": "2022-06-06", "to_date": "2022-06-06",
				"oc_leave_kind": "Medical",
			}
		)  # fmt: skip
		leave.flags.ignore_validate = True
		leave.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			leave.submit()

	# condonation

	def test_medical_band_becomes_eligible_only_after_approval(self):
		self.assertEqual(eligibility_status(self.band, self.term), "Medical band")
		doc = condonation(self.band, self.term).insert()
		self.assertEqual(eligibility_status(self.band, self.term), "Medical band")  # a draft changes nothing
		request = request_approval("Condonation Request", doc.name)
		self.assertEqual(eligibility_status(self.band, self.term), "Medical band")  # nor does a pending approval
		frappe.set_user(APPROVER)
		self.assertEqual(approve(request, None), "Approved")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Condonation Request", doc.name, "docstatus"), 1)
		summary = summarise(self.band, self.term, term_window(self.term), {})
		self.assertEqual((summary["status"], summary["band_status"], summary["condoned"]), ("Eligible", "Medical band", True))
		self.assertEqual(eligibility_status(self.s22, self.term), "Eligible")

	def test_condonation_is_for_that_term_only(self):
		self.approved_condonation()
		other_term = frappe.get_doc(
			{"doctype": "Academic Term", "academic_year": frappe.db.get_value("Academic Term", self.term, "academic_year"),
			"term_name": "Cnd Even", "term_start_date": "2023-01-01", "term_end_date": "2023-05-31"}
		).insert()  # fmt: skip
		self.assertFalse(summarise(self.band, other_term.name, term_window(other_term.name), {})["condoned"])

	def test_below_the_band_there_is_no_condonation(self):
		self.assertEqual(eligibility_status(self.short, self.term), "Shortage")
		with self.assertRaisesRegex(frappe.ValidationError, "detained"):
			condonation(self.short, self.term).insert()

	def test_no_condonation_when_attendance_is_enough(self):
		with self.assertRaisesRegex(frappe.ValidationError, "no condonation is needed"):
			condonation(self.ok, self.term).insert()

	def test_one_request_per_student_and_term(self):
		condonation(self.band, self.term).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "already has a condonation request"):
			condonation(self.band, self.term).insert()

	def test_student_can_only_request_for_themself(self):
		frappe.set_user(STUDENT_USER)
		with self.assertRaises(frappe.PermissionError):
			condonation(self.short, self.term).insert()
		doc = condonation(self.band, self.term).insert()
		self.assertEqual(doc.company, COLLEGE)
		with self.assertRaises(frappe.PermissionError):
			request_approval("Condonation Request", doc.name)  # a student cannot start (or skip) the approval

	def test_other_students_cannot_read_a_request(self):
		doc = condonation(self.band, self.term).insert()
		make_user_student = "cnd-other-student@example.com"
		login(make_user_student, "Student")
		frappe.db.set_value("Student", self.ok, "user", make_user_student)
		frappe.set_user(make_user_student)
		self.assertFalse(frappe.has_permission("Condonation Request", "read", doc.name))
		self.assertEqual(frappe.get_list("Condonation Request"), [])

	def test_fee_invoice_is_raised_under_the_condonation_fee_category(self):
		frappe.db.set_value("Attendance Rule", self.rule26.name, "condonation_fee", 500)
		customer = frappe.get_doc({"doctype": "Customer", "customer_name": "Cndband Customer", "customer_type": "Individual"}).insert()
		frappe.db.set_value("Student", self.band, "customer", customer.name)
		doc = condonation(self.band, self.term).insert()
		request = request_approval("Condonation Request", doc.name)
		frappe.set_user(APPROVER)  # the approver has no Accounts rights, so the invoice is not made in his session
		session = (frappe.session.user, frappe.session.sid, dict(frappe.local.form_dict))
		with patch("frappe.set_user", side_effect=AssertionError("set_user in a request path")), patch(
			"frappe.enqueue"
		) as enqueue:
			approve(request, None)
		self.assertEqual((frappe.session.user, frappe.session.sid, dict(frappe.local.form_dict)), session)
		queued = [c for c in enqueue.call_args_list if c.args and c.args[0] == condonation_fee.JOB]
		self.assertEqual([c.kwargs["request"] for c in queued], [doc.name])
		self.assertTrue(queued[0].kwargs["enqueue_after_commit"])
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.get_value("Condonation Request", doc.name, "fee_invoice"))  # not yet: the worker makes it
		condonation_fee.raise_fee(doc.name)
		condonation_fee.raise_fee(doc.name)  # idempotent
		self.assertEqual(frappe.session.user, "Administrator")
		doc.reload()
		self.assertEqual(doc.fee_amount, 500)
		invoice = frappe.get_doc("Sales Invoice", doc.fee_invoice)
		self.assertEqual((invoice.docstatus, invoice.grand_total, invoice.items[0].item_code, invoice.student), (1, 500, "Condonation", self.band))
		self.assertEqual(frappe.db.count("Sales Invoice", {"student": self.band, "remarks": ["like", "Condonation%"]}), 1)
		with self.assertRaisesRegex(frappe.ValidationError, "fee invoice"):
			doc.cancel()

	def test_no_fee_invoice_when_the_rule_has_no_fee(self):
		self.assertFalse(self.approved_condonation().fee_invoice)

	# the run

	def make_run(self, **values):
		return frappe.get_doc(
			{"doctype": "Attendance Eligibility Run", "company": COLLEGE, "academic_term": self.term, "send_guardian_alerts": 0, **values}
		).insert()

	def rows(self, run):
		return {r.student: r for r in frappe.get_doc("Attendance Eligibility Run", run.name).rows}

	def test_run_snapshots_status_per_student_and_is_idempotent(self):
		run = self.make_run()
		with patch.object(eligibility_run, "run_bulk", inline_bulk):
			run.start_run()
			first = self.rows(run)
			run.start_run()
		rows = self.rows(run)
		self.assertEqual({s: r.status for s, r in rows.items()}, {
			self.band: "Condonation", self.short: "Detained (SA)", self.ok: "Eligible", self.od: "Eligible", self.s22: "Eligible",
		})
		self.assertEqual(set(first), set(rows))
		self.assertEqual(len(frappe.get_doc("Attendance Eligibility Run", run.name).rows), 5)
		run.reload()
		self.assertEqual((run.eligible_count, run.condonation_count, run.detained_count), (3, 1, 1))
		self.assertEqual((rows[self.band].overall_pct, rows[self.short].overall_pct), (75.0, 50.0))
		self.assertEqual(rows[self.band].shortage_summary, "CND X (70%)")
		self.assertEqual(rows[self.short].shortage_summary, "CND X (50%), CND Y (50%)")

	def test_one_run_per_scope(self):
		self.make_run()
		with self.assertRaisesRegex(frappe.ValidationError, "already exists"):
			self.make_run()
		self.make_run(program=PROGRAM)  # a different scope is a different run

	def test_rerun_after_condonation_shows_eligible_and_filters_apply(self):
		run = self.make_run()
		with patch.object(eligibility_run, "run_bulk", inline_bulk):
			run.start_run()
			self.approved_condonation()
			run.start_run()
		row = self.rows(run)[self.band]
		self.assertEqual((row.status, row.condoned), ("Eligible", 1))
		empty = self.make_run(semester=9)
		with patch.object(eligibility_run, "run_bulk", inline_bulk):
			empty.start_run()
		self.assertEqual(self.rows(empty), {})

	def test_locked_run_is_frozen(self):
		run = self.make_run()
		with patch.object(eligibility_run, "run_bulk", inline_bulk):
			run.start_run()
			frappe.set_user(DEAN)
			run.lock_run()
			run.reload()
			self.assertEqual((run.locked, run.locked_by), (1, DEAN))
			with self.assertRaisesRegex(frappe.ValidationError, "locked"):
				run.start_run()
			with self.assertRaisesRegex(frappe.ValidationError, "locked"):  # a queued item arriving after the lock
				eligibility_run.run_student(self.band, frappe._dict(get_parameters=lambda: {"run": run.name}))
			with self.assertRaisesRegex(frappe.ValidationError, "locked"):
				run.save()
			frappe.set_user("Administrator")
			with self.assertRaisesRegex(frappe.ValidationError, "locked"):
				run.delete()

	def test_only_the_dean_may_lock_and_an_empty_run_cannot_be_locked(self):
		run = self.make_run()
		frappe.set_user(DEAN)
		with self.assertRaisesRegex(frappe.ValidationError, "no results"):
			run.lock_run()
		with patch.object(eligibility_run, "run_bulk", inline_bulk):
			run.start_run()
		frappe.set_user(STAFF)
		with self.assertRaises(frappe.PermissionError):
			run.lock_run()

	def test_run_alerts_guardians_of_students_who_are_not_eligible(self):
		for student in (self.band, self.short, self.ok):
			make_guardian(f"Cndguardian {student}", [student])
		run = self.make_run(send_guardian_alerts=1)
		with patch.object(eligibility_run, "run_bulk", inline_bulk), patch("campus.campus_messaging.api.send") as send:
			run.start_run()
		alerted = {call.args[1].name: call.args[2] for call in send.call_args_list}
		self.assertEqual(set(alerted), {self.band, self.short})  # not the eligible student with a guardian
		guardian = frappe.db.get_value("Student Guardian", {"parent": self.band}, "guardian")
		self.assertEqual(alerted[self.band], [f"Guardian:{guardian}"])
		by_student = {call.args[1].name: call for call in send.call_args_list}
		self.assertEqual(by_student[self.band].args[0], "attendance.shortage")
		self.assertEqual(by_student[self.band].args[3]["percentage"], 75.0)

	def test_message_log_is_written_for_the_guardian(self):
		guardian = make_guardian("Cndguardian real", [self.short])
		run = self.make_run(send_guardian_alerts=1)
		with patch.object(eligibility_run, "run_bulk", inline_bulk):
			run.start_run()
		logs = frappe.get_all(
			"Message Log", {"recipient": f"Guardian:{guardian}", "reference_name": self.short}, ["event_key", "message"]
		)
		self.assertTrue(logs)
		self.assertEqual({log.event_key for log in logs}, {"attendance.shortage"})
		self.assertIn("50", logs[0].message)


def make_rule(code, year, values):
	regulation = regulation_name(code, COLLEGE)
	rule = make_regulation(code, COLLEGE, [PROGRAM], year).name
	assert rule == regulation
	return frappe.get_doc({"doctype": "Attendance Rule", "regulation": regulation, **values}).insert()
