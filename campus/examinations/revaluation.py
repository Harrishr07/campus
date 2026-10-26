"""M06-06 Photocopy, revaluation and review of end-semester scripts (P2-T20).

A Revaluation Application (type Photocopy, Revaluation or Review) lists courses of the student's published Student
Result of an Exam Session. It is accepted from the release of the results (publish_at) until the Exam Rule Set's
`revaluation_window_days` after it, checked on save and again on submit. A course is eligible when the student sat
it (Pass or Fail) and the Exam Rule Set's row of its course type allows revaluation (`revaluation_allowed`; theory
and theory with lab, never labs or projects). One live application per type and course.

- Photocopy: once its fee is paid the COE issues the photocopy (`issue_photocopy`).
- Revaluation: when the Exam Rule Set says `revaluation_after_photocopy` (R2022 16.4), each course needs its issued
  photocopy, and a teacher of the course in the session's term records a justification (`justify`) before submit.
- Review: only for a course with a Revaluation Outcome of the student's revaluation of it in the session.

The fee is the Exam Fee Rate's fee of the type per course, billed on submit as a Sales Invoice of the Exam fee head
through campus_finance (the exam fee pattern: a job after commit, as Administrator in the worker). A cancelled
application cancels its unpaid invoice; a paid one, an issued photocopy or an outcome refuses the cancel.

A Revaluation Outcome (COE) records the revaluer's ESE of one course of a paid Revaluation or Review. The revaluer
is never an examiner who valued the script (Valuation Entries of its dummy numbers), never the revaluer of an
earlier outcome of it, and a teacher of the course only where the Exam Rule Set allows (T18 rules). On submit the
student's result is recomputed (campus.examinations.results reads the latest outcome's ESE per course in place of
the mark sheet's): after publication a change makes the pending Student Result version that a Result Ratification
publishes; the published version is never edited. The student is told the outcome is in (no marks).

Reports: Revaluation Change Stats; Evaluation Grievances vs Appeared (AQAR 2.5.2) and the evaluation_grievances
data point: distinct students with a submitted Revaluation or Review application (a photocopy alone is not a
grievance) in the company's released sessions (published, publish_at passed) of the academic year.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, today

from campus.campus_messaging.api import send
from campus.campus_platform.api import get_rule
from campus.examinations import revaluation_rules
from campus.examinations.access import MARKS_ROLES
from campus.examinations.affiliation import refuse_affiliated_session
from campus.examinations.courses import offering_course, rule_limits, student_limits

PHOTOCOPY, REVALUATION, REVIEW = "Photocopy", "Revaluation", "Review"
GRIEVANCE_TYPES = (REVALUATION, REVIEW)
APPLICATION, APPLICATION_COURSE, OUTCOME = (
	"Revaluation Application",
	"Revaluation Application Course",
	"Revaluation Outcome",
)
RESULT, SESSION = "Student Result", "Exam Session"
FEE_FIELDS = {PHOTOCOPY: "photocopy_fee", REVALUATION: "revaluation_fee", REVIEW: "review_fee"}
SAT = ("Pass", "Fail")
JUSTIFICATION_FIELDS = ("justification", "justified_by", "justified_on")
FEE_JOB = "campus.examinations.revaluation.raise_fee"
EXAM_HEAD = "Exam"
OUTCOME_EVENT = "exam.revaluation_completed"
OUTCOME_TEMPLATE = (
	"{{ doc.application_type }} complete: {{ doc.course }}",
	"The {{ doc.application_type }} of {{ doc.course }} ({{ doc.exam_session }}) is complete. A revised result is "
	"published on the campus portal once it is ratified.",
)


# ---- application ------------------------------------------------------------------------------


def validate_application(doc):
	"""Window, eligibility, duplicates, the photocopy / justification / revaluation prerequisites and the fee. An
	Affiliated session is refused before anything else: the university revalues its scripts (its outcome arrives as a
	correction import, M06-10)."""
	refuse_affiliated_session(doc.exam_session, _("college photocopy, revaluation and review"))
	doc.company = frappe.db.get_value(SESSION, doc.exam_session, "company")
	doc.application_date = today()
	rule_set = get_rule(doc.student, "Exam Rule Set")
	check_window(doc, rule_set)
	result = published_result(doc.student, doc.exam_session)
	doc.program = result.program
	check_courses(doc, result, rule_set)
	check_duplicates(doc)
	keep_justifications(doc)
	if doc.application_type == REVALUATION and cint(rule_set.revaluation_after_photocopy):
		check_photocopy_and_justification(doc)
	if doc.application_type == REVIEW:
		check_revalued(doc)
	doc.fee_amount = application_fee(doc)


def check_window(doc, rule_set):
	publish_at = frappe.db.get_value(SESSION, {"name": doc.exam_session, "status": "Published"}, "publish_at")
	if not publish_at or get_datetime(publish_at) > now_datetime():
		frappe.throw(
			_("The results of {0} are not released yet: the application window opens at release.").format(
				frappe.bold(doc.exam_session)
			)
		)
	if not revaluation_rules.window_open(getdate(publish_at), today(), rule_set.revaluation_window_days):
		frappe.throw(
			_(
				"The application window of {0} is closed: it runs {1} days from the release of the results."
			).format(frappe.bold(doc.exam_session), cint(rule_set.revaluation_window_days))
		)


def published_result(student, exam_session):
	name = frappe.db.get_value(RESULT, {"student": student, "exam_session": exam_session, "is_latest": 1})
	if not name:
		frappe.throw(
			_("{0} has no published result in {1}.").format(frappe.bold(student), frappe.bold(exam_session))
		)
	return frappe.get_doc(RESULT, name)


def check_courses(doc, result, rule_set):
	published = {row.course: row for row in result.courses}
	seen = set()
	if not doc.courses:
		frappe.throw(_("List the courses of the application."))
	for row in doc.courses:
		if row.course in seen:
			frappe.throw(_("{0} is listed twice.").format(frappe.bold(row.course)))
		seen.add(row.course)
		course = published.get(row.course)
		if not course:
			frappe.throw(
				_("{0} is not on the published result of {1}.").format(
					frappe.bold(row.course), frappe.bold(doc.exam_session)
				)
			)
		if course.result not in SAT:
			frappe.throw(
				_("{0} was not sat ({1}): there is no script to see or revalue.").format(
					frappe.bold(row.course), course.grade
				)
			)
		if not revaluation_allowed(rule_set, course.course_type, doc.student):
			frappe.throw(
				_(
					"{0} ({1}) is not eligible for photocopy, revaluation or review under the regulation."
				).format(frappe.bold(row.course), _(course.course_type))
			)
		row.course_type, row.grade = course.course_type, course.grade


def revaluation_allowed(rule_set, course_type, student):
	"""Whether the Exam Rule Set's row of `course_type` allows photocopy, revaluation and review."""
	limits = rule_limits(rule_set, {"course_type": course_type, "cia_max": 0, "ese_max": 0}, student)
	return bool(cint(limits["revaluation_allowed"]))


def eligible_courses(result, rule_set):
	"""Course rows of a published result that the student may apply for: sat, and of a course type the rule allows."""
	return [
		row
		for row in result.courses
		if row.result in SAT and revaluation_allowed(rule_set, row.course_type, result.student)
	]


def check_duplicates(doc):
	frappe.db.get_value(
		"Student", doc.student, "name", for_update=True
	)  # one application of a student at a time
	app, row = frappe.qb.DocType(APPLICATION), frappe.qb.DocType(APPLICATION_COURSE)
	taken = (
		frappe.qb.from_(row)
		.join(app)
		.on((app.name == row.parent) & (row.parenttype == APPLICATION))
		.select(row.course)
		.where(
			(app.student == doc.student) & (app.exam_session == doc.exam_session) & (app.application_type == doc.application_type)
			& (app.docstatus < 2) & (app.name != (doc.name or "")) & row.course.isin([r.course for r in doc.courses])
		)
		.for_update()
		.run(pluck=True)
	)  # fmt: skip
	if taken:
		frappe.throw(
			_("{0} already applied for a {1} of {2} in {3}.").format(
				frappe.bold(doc.student),
				_(doc.application_type),
				", ".join(sorted(set(taken))),
				frappe.bold(doc.exam_session),
			)
		)


def keep_justifications(doc):
	"""Only `justify` records a justification: a saved draft keeps the stored ones, a new row has none."""
	before = (
		{}
		if doc.is_new()
		else {r.course: r for r in (doc.get_doc_before_save() or frappe._dict(courses=[])).courses}
	)
	for row in doc.courses:
		stored = before.get(row.course)
		row.update({f: stored.get(f) if stored else None for f in JUSTIFICATION_FIELDS})


def check_photocopy_and_justification(doc):
	for row in doc.courses:
		if not issued_photocopy(doc.student, doc.exam_session, row.course):
			frappe.throw(
				_(
					"A revaluation of {0} needs its photocopy issued first (Photocopy application), then a teacher's justification."
				).format(frappe.bold(row.course))
			)
		if doc.docstatus == 1 and not row.justified_by:
			frappe.throw(
				_("{0}: a revaluation needs a justification by a teacher of the course first.").format(
					frappe.bold(row.course)
				)
			)


def issued_photocopy(student, exam_session, course):
	return bool(
		applications_of(student, exam_session, course, PHOTOCOPY, {"photocopy_issued_on": ["is", "set"]})
	)


def applications_of(student, exam_session, course, kind, extra=None):
	names = frappe.get_all(
		APPLICATION_COURSE, {"parenttype": APPLICATION, "course": course}, pluck="parent", distinct=True
	)
	return frappe.get_all(
		APPLICATION,
		{
			"name": ["in", names or [""]],
			"student": student,
			"exam_session": exam_session,
			"application_type": kind,
			"docstatus": 1,
			**(extra or {}),
		},
		pluck="name",
	)


def check_revalued(doc):
	for row in doc.courses:
		if not frappe.db.exists(
			OUTCOME,
			{
				"student": doc.student,
				"exam_session": doc.exam_session,
				"course": row.course,
				"application_type": REVALUATION,
				"docstatus": 1,
			},
		):
			frappe.throw(
				_("{0}: a Review is allowed only after a revaluation of the course.").format(
					frappe.bold(row.course)
				)
			)


def application_fee(doc):
	from campus.examinations.exam_fee import fee_rate

	rate = fee_rate(doc.company, doc.program)
	return revaluation_rules.fee_total(rate.get(FEE_FIELDS[doc.application_type]), len(doc.courses))


@frappe.whitelist(methods=["POST"])
def justify(application, course, justification):
	"""A teacher of `course` in the session's term: record the justification for revaluing it (draft Revaluation)."""
	from campus.examinations.doctype.valuation_allocation.valuation_allocation import course_teachers

	doc = frappe.get_doc(APPLICATION, frappe.db.get_value(APPLICATION, application, "name", for_update=True))
	if frappe.session.user not in course_teachers(
		doc.exam_session, course
	):  # before anything about the application
		raise frappe.PermissionError(
			_("Only a teacher of {0} this term justifies its revaluation.").format(course)
		)
	if doc.docstatus != 0 or doc.application_type != REVALUATION:
		frappe.throw(_("A justification is recorded on a draft Revaluation application."))
	if not (justification or "").strip():
		frappe.throw(_("Write the justification."))
	row = next((r for r in doc.courses if r.course == course), None)
	if not row:
		frappe.throw(_("{0} is not on {1}.").format(frappe.bold(course), application))
	frappe.db.set_value(
		APPLICATION_COURSE, row.name,
		{"justification": justification.strip(), "justified_by": frappe.session.user, "justified_on": now_datetime()},
	)  # fmt: skip


@frappe.whitelist(methods=["POST"])
def issue_photocopy(application):
	"""COE: record that the photocopies of a paid Photocopy application are issued."""
	frappe.only_for(MARKS_ROLES)
	frappe.db.get_value(APPLICATION, application, "name", for_update=True)
	doc = frappe.get_doc(APPLICATION, application)
	check_company(doc)
	if doc.docstatus != 1 or doc.application_type != PHOTOCOPY:
		frappe.throw(_("Photocopies are issued on a submitted Photocopy application."))
	if not fee_paid(doc):
		frappe.throw(_("The fee of {0} is not paid yet.").format(frappe.bold(application)))
	if not doc.photocopy_issued_on:
		doc.db_set("photocopy_issued_on", now_datetime())


def check_company(doc):
	"""Refuse a COE restricted (User Permission) to other companies."""
	from campus.campus_platform.company_scope import permitted_companies

	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and doc.company not in permitted:
		raise frappe.PermissionError(_("{0} belongs to a college you do not work for.").format(doc.name))


# ---- who reads an application ---------------------------------------------------------------------

FULL_READ_ROLES = ("COE", "System Manager", "Dean Academics")


def teachable_drafts(user):
	"""Draft Revaluation applications listing a course `user` teaches in the term of the application's session, at
	the college of the offering's Program (a teacher of the same course and term elsewhere sees none of them)."""
	from campus.examinations.access import instructed_offerings

	taught = frappe.get_all(
		"Student Group",
		{"name": ["in", instructed_offerings(user)], "group_based_on": "Course"},
		["course", "academic_term", "program"],
	)
	companies = {
		p.name: p.oc_company
		for p in frappe.get_all(
			"Program", {"name": ["in", [t.program for t in taught] or [""]]}, ["name", "oc_company"]
		)
	}
	taught = [
		t for t in taught if companies.get(t.program)
	]  # an offering without a college's Program gives nothing
	if not taught:
		return []
	app, row, session = (
		frappe.qb.DocType(APPLICATION),
		frappe.qb.DocType(APPLICATION_COURSE),
		frappe.qb.DocType(SESSION),
	)
	pairs = None
	for t in taught:
		clause = (
			(row.course == t.course)
			& (session.academic_term == t.academic_term)
			& (app.company == companies[t.program])
		)
		pairs = clause if pairs is None else pairs | clause
	return (
		frappe.qb.from_(app)
		.join(row).on((row.parent == app.name) & (row.parenttype == APPLICATION))
		.join(session).on(session.name == app.exam_session)
		.select(app.name).distinct()
		.where((app.docstatus == 0) & (app.application_type == REVALUATION) & pairs)
		.run(pluck=True)
	)  # fmt: skip


def permission_query(user=None):
	"""COE, System Manager and Dean Academics read every application; a teacher only the drafts to justify."""
	from campus.examinations.access import has_any_role

	user = user or frappe.session.user
	if has_any_role(user, FULL_READ_ROLES):
		return ""
	names = teachable_drafts(user)
	return f"`tab{APPLICATION}`.name in ({', '.join(frappe.db.escape(n) for n in names)})" if names else "1=0"


def has_permission(doc, ptype=None, user=None):
	"""Deny-only for teachers: read of a draft revaluation they can justify, nothing else."""
	from campus.examinations.access import has_any_role

	user = user or frappe.session.user
	if has_any_role(user, FULL_READ_ROLES):
		return None
	if ptype not in ("read", "print"):
		return False
	return bool(doc.name) and doc.name in teachable_drafts(user)


# ---- fee ----------------------------------------------------------------------------------------


def check_invoiceable(doc):
	"""Before submit: the fee of the type must be set (never a silent free application) and invoiceable."""
	from campus.campus_finance.api import check_fee_invoice
	from campus.examinations.exam_fee import RATE

	if flt(doc.fee_amount) <= 0:
		label = frappe.get_meta(RATE).get_label(FEE_FIELDS[doc.application_type])
		frappe.throw(
			_("Set the {0} on the Exam Fee Rate of {1} before submitting.").format(
				_(label), frappe.bold(doc.company)
			)
		)
	check_fee_invoice(doc.student, EXAM_HEAD, doc.company)


@frappe.whitelist(methods=["POST"])
def reraise_fee(application):
	"""COE: queue the fee invoice again of a submitted application whose invoice job failed."""
	frappe.only_for(MARKS_ROLES)
	values = frappe.db.get_value(
		APPLICATION,
		application,
		["docstatus", "fee_amount", "fee_invoice", "company"],
		as_dict=True,
		for_update=True,
	)
	if not values:
		frappe.throw(
			_("Revaluation Application {0} not found.").format(frappe.bold(application)),
			frappe.DoesNotExistError,
		)
	check_company(frappe._dict(values, name=application))
	if values.docstatus != 1 or flt(values.fee_amount) <= 0:
		frappe.throw(_("{0} is not a submitted application with a fee.").format(frappe.bold(application)))
	if values.fee_invoice:
		frappe.throw(
			_("{0} already has its invoice {1}.").format(frappe.bold(application), values.fee_invoice)
		)
	frappe.enqueue(
		FEE_JOB, queue="short", enqueue_after_commit=True, now=frappe.in_test, application=application
	)


def queue_fee(doc):
	"""Queue the fee invoice of a submitted application (inline under tests, like the exam fee)."""
	if flt(doc.fee_amount) > 0:
		frappe.enqueue(
			FEE_JOB, queue="short", enqueue_after_commit=True, now=frappe.in_test, application=doc.name
		)


def raise_fee(application):
	"""Worker entry point: raise the invoice of a submitted application that has a fee and none yet."""
	from campus.campus_finance.api import raise_fee_invoice

	caller = frappe.session.user
	frappe.set_user("Administrator")
	try:
		values = frappe.db.get_value(
			APPLICATION, application, ["docstatus", "fee_amount", "fee_invoice", "student", "company", "exam_session", "application_type"],
			as_dict=True, for_update=True,
		)  # fmt: skip
		if not values or values.docstatus != 1 or flt(values.fee_amount) <= 0 or values.fee_invoice:
			return
		invoice = raise_fee_invoice(
			values.student, EXAM_HEAD, values.fee_amount, values.company,
			_("{0} fee, {1} ({2})").format(_(values.application_type), values.exam_session, application),
		)  # fmt: skip
		frappe.db.set_value(APPLICATION, application, "fee_invoice", invoice.name)
	finally:
		frappe.set_user(caller)


def fee_paid(doc):
	if flt(doc.fee_amount) <= 0:
		return True
	invoice = doc.fee_invoice and frappe.db.get_value(
		"Sales Invoice", doc.fee_invoice, ["docstatus", "outstanding_amount"], as_dict=True
	)
	return bool(invoice and invoice.docstatus == 1 and flt(invoice.outstanding_amount) <= 0)


def check_cancel(doc):
	if frappe.db.exists(OUTCOME, {"application": doc.name, "docstatus": ["<", 2]}):
		frappe.throw(
			_("{0} has a revaluation outcome; it cannot be cancelled.").format(frappe.bold(doc.name))
		)
	if doc.photocopy_issued_on:
		frappe.throw(
			_("The photocopies of {0} are issued; it cannot be cancelled.").format(frappe.bold(doc.name))
		)
	invoice = doc.fee_invoice and frappe.db.get_value(
		"Sales Invoice",
		doc.fee_invoice,
		["docstatus", "outstanding_amount", "grand_total"],
		as_dict=True,
		for_update=True,
	)
	if invoice and invoice.docstatus == 1 and flt(invoice.outstanding_amount) < flt(invoice.grand_total):
		frappe.throw(
			_("The fee of {0} is paid; a refund goes through Campus Finance, the application stays.").format(
				frappe.bold(doc.name)
			)
		)


def cancel_fee(doc):
	if doc.fee_invoice and frappe.db.get_value("Sales Invoice", doc.fee_invoice, "docstatus") == 1:
		invoice = frappe.get_doc("Sales Invoice", doc.fee_invoice)
		invoice.flags.ignore_permissions = (
			True  # the canceller may lack Accounts rights; the invoice is the application's own
		)
		invoice.cancel()


# ---- outcome ------------------------------------------------------------------------------------


def validate_outcome(doc):
	"""Bind the outcome to its paid application and course, check the revaluer and the mark, record the before."""
	app = frappe.get_doc(
		APPLICATION, frappe.db.get_value(APPLICATION, doc.application, "name", for_update=True)
	)
	if app.docstatus != 1:
		frappe.throw(_("{0} is not submitted.").format(frappe.bold(app.name)))
	if app.application_type not in GRIEVANCE_TYPES:
		frappe.throw(
			_("A {0} application has no outcome: issue its photocopy.").format(_(app.application_type))
		)
	doc.update({f: app.get(f) for f in ("application_type", "student", "exam_session", "company")})
	if doc.course not in {r.course for r in app.courses}:
		frappe.throw(_("{0} is not on {1}.").format(frappe.bold(doc.course), app.name))
	if not fee_paid(app):
		frappe.throw(_("The fee of {0} is not paid yet.").format(frappe.bold(app.name)))
	if frappe.qb.get_query(
		OUTCOME, filters={"application": app.name, "course": doc.course, "docstatus": ["<", 2], "name": ["!=", doc.name or ""]},
		fields=["name"], for_update=True,
	).run():  # fmt: skip
		frappe.throw(_("{0} of {1} already has an outcome.").format(frappe.bold(doc.course), app.name))
	set_revaluer(doc)
	check_revaluer(doc)
	row = next(
		(r for r in current_result(doc.student, doc.exam_session).courses if r.course == doc.course), None
	)
	if not row:
		frappe.throw(
			_("{0} is not on the result of {1}.").format(
				frappe.bold(doc.course), frappe.bold(doc.exam_session)
			)
		)
	ese_max = student_limits(doc.student, offering_course(row.course_offering))["ese_max"]
	if not 0 <= flt(doc.new_ese) <= flt(ese_max):
		frappe.throw(_("The ESE on revaluation lies within 0-{0}.").format(flt(ese_max)))
	doc.original_ese = current_ese(doc.student, doc.exam_session, doc.course, doc.name)
	doc.ese_change = round(flt(doc.new_ese) - flt(doc.original_ese), 2)
	doc.original_grade = row.grade


def current_result(student, exam_session):
	"""The pending version when one exists (an earlier outcome not yet ratified), else the published one."""
	pending = frappe.db.get_value(
		RESULT, {"student": student, "exam_session": exam_session, "pending_ratification": 1}
	)
	return frappe.get_doc(RESULT, pending) if pending else published_result(student, exam_session)


def set_revaluer(doc):
	doc.revaluer = None
	if doc.examiner_type == "Internal" and doc.employee:
		doc.revaluer = frappe.db.get_value("Employee", doc.employee, "user_id")
	elif doc.examiner_type == "External" and doc.external_member:
		email = frappe.db.get_value("External Member", doc.external_member, "email")
		doc.revaluer = email and frappe.db.get_value("User", {"email": email})
	if not doc.revaluer:
		frappe.throw(_("Choose the revaluer: an Employee or External Member with a user."))
	if doc.revaluer == frappe.session.user:
		frappe.throw(_("The revaluer does not record their own outcome; the COE records it."))


def check_revaluer(doc):
	"""A different examiner: not one who valued the script, not an earlier revaluer of it, a course teacher only by
	the Exam Rule Set (server-side join of the dummy numbers; nothing is returned to the examiner)."""
	from campus.examinations.doctype.valuation_allocation.valuation_allocation import course_teachers

	dummies = frappe.get_all(
		"Dummy Number Map",
		{"student": doc.student, "exam_session": doc.exam_session, "course": doc.course},
		pluck="dummy_number",
	)
	valued = frappe.get_all(
		"Valuation Entry", {"dummy_number": ["in", dummies or [""]], "docstatus": ["<", 2]}, pluck="examiner"
	)
	if doc.revaluer in valued:
		frappe.throw(_("{0} valued this script; another examiner revalues it.").format(doc.revaluer))
	earlier = frappe.get_all(
		OUTCOME,
		{
			"student": doc.student,
			"exam_session": doc.exam_session,
			"course": doc.course,
			"docstatus": 1,
			"name": ["!=", doc.name or ""],
		},
		pluck="revaluer",
	)
	if doc.revaluer in earlier:
		frappe.throw(_("{0} revalued this script already; another examiner takes it.").format(doc.revaluer))
	allowed = cint(get_rule(doc.student, "Exam Rule Set").allow_course_teacher_as_examiner)
	if not allowed and doc.revaluer in course_teachers(doc.exam_session, doc.course):
		frappe.throw(
			_("{0} teaches {1} this term and cannot revalue its scripts.").format(doc.revaluer, doc.course)
		)


def current_ese(student, exam_session, course, exclude=None):
	"""The script's ESE as it stands: the latest submitted outcome's, else the mark sheet's."""
	revised = revised_ese(student, exam_session, exclude)
	if course in revised:
		return revised[course]
	sheets = frappe.get_all(
		"Mark Sheet Entry", {"exam_session": exam_session, "course": course}, pluck="name"
	)
	return flt(
		sheets
		and frappe.db.get_value(
			"Mark Sheet Entry Row",
			{"parent": ["in", sheets], "parenttype": "Mark Sheet Entry", "student": student},
			"ese",
		)
	)


def revised_ese(student, exam_session, exclude=None):
	"""{course: ESE} of the student's latest submitted Revaluation Outcome per course in the session (the Result Run
	grades on these in place of the mark sheet's ESE)."""
	filters = {"student": student, "exam_session": exam_session, "docstatus": 1}
	if exclude:
		filters["name"] = ["!=", exclude]
	return {
		r.course: flt(r.new_ese)
		for r in frappe.get_all(OUTCOME, filters, ["course", "new_ese"], order_by="creation, name")
	}


def apply_outcome(doc):
	"""Recompute the student's result on the outcome (a pending version after publication) and tell the student."""
	from campus.examinations.results import compute_student_result

	name = compute_student_result(doc.student, doc.exam_session)
	grade = frappe.db.get_value(
		"Student Result Course", {"parenttype": RESULT, "parent": name, "course": doc.course}, "grade"
	)
	doc.db_set({"result_version": name, "revised_grade": grade})
	send(OUTCOME_EVENT, doc, [f"Student:{doc.student}"])


def seed_outcome_template():
	"""The outcome notice template; an existing (possibly edited) one is left alone."""
	if frappe.db.exists("Message Template", OUTCOME_EVENT):
		return
	subject, body = OUTCOME_TEMPLATE
	frappe.get_doc(
		{
			"doctype": "Message Template", "event_key": OUTCOME_EVENT, "purpose": "transactional",
			"channels": [{"channel": "sms"}, {"channel": "whatsapp"}, {"channel": "email"}],
			"bodies": [{"language": "en", "subject": subject, "body": body}],
		}
	).insert(ignore_permissions=True)  # fmt: skip


# ---- reports and the data point (AQAR 2.5.2) ------------------------------------------------------


def year_sessions(company, academic_year):
	"""The company's released sessions of the year (campus.examinations.coe_reports.released_sessions)."""
	from campus.examinations.coe_reports import released_sessions

	return [s.name for s in released_sessions(company, academic_year)]


def grievance_applications(sessions, programs=None):
	"""Submitted Revaluation and Review applications of `sessions` (optionally of `programs`): [{name, student, exam_session}]."""
	filters = {
		"exam_session": ["in", sessions or [""]],
		"docstatus": 1,
		"application_type": ["in", GRIEVANCE_TYPES],
	}
	if programs is not None:
		filters["program"] = ["in", programs or [""]]
	return frappe.get_all(APPLICATION, filters, ["name", "student", "exam_session"], order_by="name")


def appeared_students(exam_session):
	"""Distinct students who sat at least one course (Pass or Fail) on their published result of the session."""
	result, row = frappe.qb.DocType(RESULT), frappe.qb.DocType("Student Result Course")
	return set(
		frappe.qb.from_(result)
		.join(row)
		.on((row.parent == result.name) & (row.parenttype == RESULT))
		.select(result.student)
		.distinct()
		.where((result.exam_session == exam_session) & (result.is_latest == 1) & row.result.isin(SAT))
		.run(pluck=True)
	)


def evaluation_grievances(company, academic_year, programs=None):
	"""{value, records}: distinct students with a grievance about evaluation in the year (AQAR 2.5.2)."""
	rows = grievance_applications(year_sessions(company, academic_year), programs)
	return {
		"value": len({r.student for r in rows}),
		"records": [{"doctype": APPLICATION, "name": r.name} for r in rows],
	}
