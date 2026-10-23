"""M05-15 Completion: the credit completion check, award eligibility, the degree-awarding authority and the move to
Alumni.

Completion check (run_check): the student's published results (graduation.published_attempts: latest, ratified,
released) and submitted Credit Recognitions against the Effective curriculum of the student's programme, regulation
and batch, by campus.examinations.completion_rules. Each run is kept as a Completion Check record for audit; a
re-run whose outcome is unchanged records nothing new. A student is Study Completed only with a Complete check (the
Convocation List calls it).

Award eligibility (award_refusal): no dues to any company of the group (has_dues blocking, as the transfer
certificate) and the programme's Degree Awarding Authority valid on the award date: an Official Document of its type
and authority, of the programme or the whole college, in force that day. No disciplinary hold is recorded in the app
yet (P4-T16), so none is checked. Refusals name every reason.

Alumni (Completion Settings): on convocation, or by the daily job a set number of days after the graduation date
(dated that day). The app has no alumni record, so the lifecycle status alone marks it.

Bulk: run_completion_checks queues one Bulk Run over the students of a college's programme (and batch); each student's
outcome is its Completion Check, linked to the run. COE, Dean Academics or System Manager, within their colleges.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Coalesce
from frappe.utils import fmt_money, getdate, now_datetime, today

from campus.campus_finance.api import has_dues
from campus.campus_platform.api import DEAN_ROLE, get_regulation, live_run, permitted_companies, run_bulk
from campus.curriculum.api import effective_curriculum
from campus.examinations import completion_rules as rules
from campus.examinations import graduation, graduation_rules
from campus.examinations.access import COE_ROLE
from campus.student_services.api import (
	ACTIVE,
	ALUMNI,
	AWARD_ELIGIBLE,
	GRADUATED,
	STUDY_COMPLETED,
	last_change_date,
	lifecycle_status,
	transition,
)

CHECK, CATEGORY_ROW = "Completion Check", "Completion Check Category"
AUTHORITY, SETTINGS, OFFICIAL_DOCUMENT = "Degree Awarding Authority", "Completion Settings", "Official Document"
RUN_TYPE = "Completion Check"
RUN_ROLES = (COE_ROLE, DEAN_ROLE, "System Manager")
CHECKED_STATUSES = (ACTIVE, STUDY_COMPLETED, AWARD_ELIGIBLE)  # the students a bulk run checks
ON_CONVOCATION = "On Convocation"
ALUMNI_SAVEPOINT = "campus_alumni"


# ---- completion check ---------------------------------------------------------------------


def run_check(student, bulk_run=None):
	"""Check `student`'s credit completion; returns the Completion Check. The latest one is returned when the outcome
	is unchanged, unless `bulk_run` is a different run: each run then records every student's outcome (the runner
	processes a student once per run). The student row is locked, so concurrent checks never record one outcome twice."""
	frappe.db.get_value("Student", student, "name", for_update=True)
	facts = check_facts(student)
	outcome = rules.evaluate(
		facts.rows, facts.minimums, facts.counting, facts.total, facts.passed, facts.recognised, facts.specialisations
	)
	digest = rules.fingerprint(facts.curriculum, outcome)  # before the (translated) reasons: language-independent
	if not facts.curriculum:
		outcome["reasons"] = [_("No Effective curriculum for {0} under {1}.").format(facts.program or "-", facts.regulation or "-")]
	else:
		outcome["reasons"] = reasons(outcome)
	latest = latest_check(student)
	if latest and latest.fingerprint == digest and (not bulk_run or latest.bulk_run == bulk_run):
		return latest
	return record(student, facts, outcome, digest, bulk_run)


def check_facts(student):
	"""What a completion check reads: programme, regulation, batch, curriculum rows and requirements, passed and
	recognised courses, Honours / Minor rows."""
	info = frappe.db.get_value("Student", student, ["student_name", "oc_company", "oc_batch"], as_dict=True)
	regulation, program = get_regulation(student), student_program(student)
	curriculum = effective_curriculum(program, regulation, info.oc_batch) if program and regulation else None
	rows = curriculum_rows(curriculum)
	minimums = dict(
		frappe.get_all("Category Credit Requirement", {"parenttype": "Curriculum", "parent": curriculum or ""}, ["category", "min_credits"], as_list=True)
	)
	categories = {row["category"] for row in rows} | set(minimums)
	counting = dict(frappe.get_all("Course Category", {"name": ["in", list(categories) or [""]]}, ["name", "counts_toward_credits"], as_list=True))
	attempts = graduation.published_attempts(student)
	types = graduation.registration_types(student)
	return frappe._dict(
		student_name=info.student_name, company=info.oc_company, batch=info.oc_batch, program=program, regulation=regulation,
		curriculum=curriculum, rows=rows, minimums=minimums, counting=counting, total=graduation.required_credits(regulation),
		passed=passed_courses(attempts, types), recognised=recognised_courses(student),
		specialisations=specialisations(attempts, types, regulation),
	)  # fmt: skip


def student_program(student):
	"""The programme of the student's latest submitted Program Enrollment."""
	return frappe.db.get_value(
		"Program Enrollment", {"student": student, "docstatus": 1}, "program", order_by="enrollment_date desc, creation desc"
	)


def curriculum_rows(curriculum):
	if not curriculum:
		return []
	return frappe.get_all(
		"Curriculum Course", {"parenttype": "Curriculum", "parent": curriculum},
		["course", "category", "credits", "is_elective"], order_by="idx asc",
	)  # fmt: skip


def passed_courses(attempts, types):
	"""{course: credits} of the core courses passed in published results (the latest pass)."""
	return {
		row.course: row.credits
		for row in attempts
		if row.result == graduation_rules.PASS and types.get(row.course) not in graduation_rules.ADDITIONAL_TYPES
	}


def recognised_courses(student):
	return dict(frappe.get_all("Credit Recognition", {"student": student, "docstatus": 1}, ["course", "credits"], as_list=True))


def specialisations(attempts, types, regulation):
	"""(Honours / Minor, credits required, credits passed) for each variant the student registered for. Both need the
	Classification Rule's honours_credits: the regulations set one figure for Honours and Minor (rulings: 18)."""
	rule = graduation.classification_rule(regulation)
	needed = rule.honours_credits if rule else 0
	found = []
	for variant in (graduation_rules.HONOURS, graduation_rules.MINOR):
		if variant in types.values():
			passed = {a.course: a.credits for a in attempts if a.result == graduation_rules.PASS and types.get(a.course) == variant}
			found.append((variant, needed, sum(passed.values())))
	return found


def reasons(outcome):
	lines = [
		_("{0}: {1} of {2} credits").format(row["category"], row["earned"], row["required"])
		for row in outcome["categories"]
		if row["status"] == rules.SHORT
	]
	if outcome["missing_courses"]:
		lines.append(_("Mandatory courses not cleared: {0}").format(", ".join(outcome["missing_courses"])))
	return lines


def latest_check(student):
	name = frappe.db.get_value(CHECK, {"student": student}, "name", order_by="creation desc, name desc", for_update=True)
	return frappe.get_doc(CHECK, name) if name else None


def record(student, facts, outcome, digest, bulk_run):
	doc = frappe.get_doc(
		{
			"doctype": CHECK, "student": student, "student_name": facts.student_name, "company": facts.company,
			"program": facts.program, "batch": facts.batch, "regulation": facts.regulation, "curriculum": facts.curriculum,
			"checked_on": now_datetime(), "result": outcome["result"], "bulk_run": bulk_run, "fingerprint": digest,
			"missing_courses": ", ".join(outcome["missing_courses"]), "reasons": "\n".join(outcome["reasons"]),
			"categories": [
				{"category": r["category"], "required_credits": r["required"], "earned_credits": r["earned"], "status": r["status"]}
				for r in outcome["categories"]
			],
		}
	)  # fmt: skip
	doc.flags.from_completion_service = True
	return doc.insert(ignore_permissions=True)


# ---- award eligibility --------------------------------------------------------------------


def award_refusal(student, award_date, program=None):
	"""Why `student` cannot be award eligible on `award_date` for `program` (default: the latest enrollment's) (every
	reason, plain text), or None."""
	found = []
	dues = has_dues(student)
	if dues.blocking > 0:
		owed = ", ".join(f"{company}: {fmt_money(amount, currency='INR')}" for company, amount in dues.by_company.items() if amount > 0)
		found.append(_("Dues outstanding ({0}).").format(owed))
	company = frappe.db.get_value("Student", student, "oc_company")
	problem = authority_refusal(company, program or student_program(student), getdate(award_date))
	if problem:
		found.append(problem)
	return " ".join(found) or None


def authority_refusal(company, program, on_date):
	"""Why the degree of `program` at `company` cannot be awarded on `on_date` by its authority, or None."""
	setting = frappe.db.get_value(AUTHORITY, {"company": company, "program": program}, ["authority_name", "document_type", "document_authority"], as_dict=True)
	if not setting:
		return _("No Degree Awarding Authority is set for {0} of {1}.").format(program or "-", company)
	documents = authority_documents(company, program, setting)
	if rules.covering_document(documents, on_date):
		return None
	if not documents:
		return _("No {0} document of {1} for {2} is on the Official Document register (degree awarded by {3}).").format(
			_(setting.document_type), setting.document_authority, program, setting.authority_name
		)
	latest = documents[0]
	return _("The {0} document {1} of {2} for {3} is not in force on {4}: valid {5} to {6}, {7}.").format(
		_(setting.document_type), latest.reference_no or latest.name, setting.document_authority, program,
		frappe.format(on_date, "Date"), frappe.format(latest.valid_from, "Date"), frappe.format(latest.valid_to, "Date"), _(latest.status),
	)  # fmt: skip


def authority_documents(company, program, setting):
	"""Official Documents of the authority's type and body for the programme or the whole college, latest end first."""
	document = frappe.qb.DocType(OFFICIAL_DOCUMENT)
	return (
		frappe.qb.from_(document)
		.select(document.name, document.reference_no, document.valid_from, document.valid_to, document.status)
		.where((document.company == company) & (document.document_type == setting.document_type))
		.where(document.authority == setting.document_authority)
		.where((document.program == program) | (Coalesce(document.program, "") == ""))
		.orderby(document.valid_to, order=frappe.qb.desc)
		.run(as_dict=True)
	)


# ---- alumni -------------------------------------------------------------------------------


def alumni_on_convocation(student, convocation_date, source):
	"""Move a graduate to Alumni from the convocation date when the setting says so."""
	if frappe.db.get_single_value(SETTINGS, "alumni_move") == ON_CONVOCATION:
		transition(student, ALUMNI, convocation_date, _("Alumni on convocation"), source)


def move_graduates_to_alumni(on_date=None):
	"""Daily: graduates whose graduation date is the set number of days past become Alumni, dated that day. In "On
	Convocation" mode the days are 0, so a graduate recorded outside a Convocation List (or before the setting) is not
	left behind. A student the lifecycle refuses is logged and skipped."""
	on_convocation = frappe.db.get_single_value(SETTINGS, "alumni_move") == ON_CONVOCATION
	days = 0 if on_convocation else frappe.db.get_single_value(SETTINGS, "alumni_after_days") or 0
	on_date, moved = getdate(on_date or today()), 0
	for student in frappe.get_all("Student", {"oc_academic_status": GRADUATED}, pluck="name", order_by="name asc"):
		graduated_on = last_change_date(student)
		if not graduated_on or not rules.alumni_due(getdate(graduated_on), days, on_date):
			continue
		frappe.db.savepoint(ALUMNI_SAVEPOINT)
		try:
			transition(student, ALUMNI, rules.alumni_date(getdate(graduated_on), days), _("Alumni {0} days after graduation").format(days), (SETTINGS, SETTINGS))
			moved += 1
		except frappe.ValidationError as error:
			frappe.db.rollback(save_point=ALUMNI_SAVEPOINT)
			frappe.log_error(title=_("Alumni move refused"), message=f"{student}: {error}")
	return moved


# ---- desk actions -------------------------------------------------------------------------


def check_runner(company):
	"""Throw unless the session user may run completion checks for `company`."""
	frappe.only_for(RUN_ROLES)
	permitted = permitted_companies(frappe.session.user)
	if not company or (permitted is not None and company not in permitted):
		frappe.throw(_("You cannot run completion checks for {0}.").format(company or "-"), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def check_student(student):
	"""Run the completion check of one student; returns {name, result}."""
	check_runner(frappe.db.get_value("Student", student, "oc_company"))
	doc = run_check(student)
	return {"name": doc.name, "result": doc.result}


@frappe.whitelist(methods=["POST"])
def run_completion_checks(company, program, batch=None):
	"""Queue the completion checks of `company`'s students in `program` (and `batch`); returns the Bulk Run name. A
	run already queued or running for the same students is returned instead of a second one."""
	check_runner(company)
	if frappe.db.get_value("Program", program, "oc_company") != company:
		frappe.throw(_("{0} is not a program of {1}.").format(frappe.bold(program), frappe.bold(company)))
	frappe.db.get_value("Company", company, "name", for_update=True)  # serialise starts for the college
	parameters = {"company": company, "program": program, "batch": batch or None}
	running = live_run(RUN_TYPE, **parameters)
	if running:
		return running
	students = batch_students(company, program, batch)
	if not students:
		frappe.throw(_("No student of {0} in {1} to check.").format(company, program))
	return run_bulk(RUN_TYPE, students, "campus.examinations.completion.check_item", chunk=20, parameters=parameters)


def batch_students(company, program, batch=None):
	"""Students of `company` with a submitted enrollment in `program` (and `batch`), on roll or completing."""
	student, enrollment = frappe.qb.DocType("Student"), frappe.qb.DocType("Program Enrollment")
	query = (
		frappe.qb.from_(enrollment)
		.join(student)
		.on(student.name == enrollment.student)
		.select(student.name)
		.distinct()
		.where((enrollment.docstatus == 1) & (enrollment.program == program) & (student.oc_company == company))
		.where(student.oc_academic_status.isin(CHECKED_STATUSES))
		.orderby(student.name)
	)
	if batch:
		query = query.where(student.oc_batch == batch)
	return query.run(pluck=True)


def check_item(student, run):
	"""Bulk Run handler: one student's completion check, linked to the run."""
	run_check(student, bulk_run=run.name)
