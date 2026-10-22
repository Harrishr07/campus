"""M12-02, M06-05 Result Run: Student Results (course grades, SGPA, CGPA, result, arrears) from Mark Sheet Entries.

Courses of a student in a session: the term's course offerings the student is in (kind Current) and the courses
the student's Exam Registration of the session lists as Arrear (graded on the sheet of the course in the
session; credits and type from the offering of the earlier attempt). Per course the first applicable outcome wins:
SA when attendance eligibility (Student Services) is Shortage (current courses); the regulation's withdrawal code
(WD/WC, result WD) when an Exam Withdrawal Application of the course is approved (P2-T21); AB when the student is
marked absent in a Seating Plan of the session (exam attendance, M06-02) or the mark row says absent; else
pass or fail by the student's Exam Rule Set.

Marks (P2-T19, via campus.examinations.result_rules): the ESE plus the course's approved Mark Moderation; the CIA
of an arrear is carried forward from the first attempt when the Exam Rule Set says so; the attempt number
(earlier fails, and absences when the rule counts them) feeds the ESE-alone rule. A failed course gets grace marks
when the Exam Rule Set allows them (Grace Mark Audit report). A pass is graded by the Grading Scheme method of its
course type (rules.grading_method on the session cohort of the course, campus.examinations.result_cohort):
relative Box-Cox bands, the online table or the absolute table. A fail is U, grade point 0.

SGPA counts this session's passed current courses; CGPA every pass (latest result versions of terms starting no
later than this one), both leaving out the Grading Scheme's excluded course categories. Result is Pass when every
course passed, arrears count the courses not yet passed. A final-year session with no arrears gets its class
(rules.classify with the student's entry type, years of study and break of study).

An Arrear with no row on a mark sheet of the session stays Pending (owed, outside the SGPA, counted as an arrear).

Revaluation (P2-T20): the ESE of a course with a submitted Revaluation Outcome is the latest outcome's, in place of
the mark sheet's (moderation and grace still apply on top).

Versioned: before publication a re-run replaces the latest version in place. After publication a change makes one
pending version with a change log, graded on the relative bands frozen at publication; the published version stays
the latest (and the only one students and staff see) until a Result Ratification publishes the pending one.

M06-10: an Affiliated session is never run (the university grades it), and Affiliated students are left out of the
run of an Autonomous session (campus.examinations.affiliation).

M06-12 pre-validation: a run starts only when every course offered to its students in the session's term has a
course type (blank is never read as Internal Only or Theory) that each student's Exam Rule Set covers; otherwise it
is refused listing the incomplete courses. Internal Only is the explicit exam type of a course with no ESE.
"""

import json
import math
from collections import Counter

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt, getdate

from campus.campus_platform.api import get_regulation, get_rule
from campus.examinations import result_rules, rules, seating
from campus.examinations.affiliation import AFFILIATED, examination_mode, examination_modes, refuse_affiliated_session
from campus.examinations.access import COE_ROLE
from campus.examinations.arrears import outstanding_arrears
from campus.examinations.courses import COURSE_FIELDS, course_type, offering_course, student_limits
from campus.examinations.doctype.mark_moderation.mark_moderation import approved_adjustments
from campus.examinations.result_cohort import Cohorts
from campus.examinations.revaluation import revised_ese
from campus.student_services.api import eligibility_status, students_on_break, student_offerings, withdrawal_code

RUN_TYPE = "Result Run"
HANDLER = "campus.examinations.results.run_student"
RESULT = "Student Result"
SA, AB, FAIL, WD = "SA", "AB", "U", "WD"
CURRENT, ARREAR = "Current", "Arrear"
PENDING = "Pending"  # an arrear registered in the session with no mark sheet row: still owed
SAT = ("Fail", "AB")  # earlier outcomes an arrear attempt follows (their CIA can be carried forward)
PUBLISHED = "Published"
ROW_FIELDS = (
	"course", "course_offering", "course_type", "credits", "cia", "ese", "total", "grade", "grade_point", "result",
	"kind", "attempt", "moderation", "grace", "grace_rule", "grading_method", "in_gpa",
)  # fmt: skip


def start_run(exam_session, program):
	"""Queue the Result Run of `program` students for the session; returns the Bulk Run name. After publication
	the run makes new result versions."""
	from campus.campus_platform.bulk import run_bulk

	frappe.only_for((COE_ROLE, "System Manager"))
	session = frappe.get_doc("Exam Session", exam_session)
	session.check_permission("write")
	refuse_affiliated_session(exam_session, _("the Result Run"))
	if frappe.db.get_value("Program", program, "oc_company") != session.company:
		frappe.throw(_("Program {0} does not belong to {1}.").format(frappe.bold(program), frappe.bold(session.company)))
	students = program_students(session, program)
	if not students:
		frappe.throw(
			_("No student of {0} writes the college's examinations in {1}: their results come from the university (Affiliated mode) or they are on a break.").format(
				frappe.bold(program), frappe.bold(exam_session)
			)
		)
	check_configuration(session, students)
	return run_bulk(RUN_TYPE, students, HANDLER, parameters={"exam_session": exam_session, "program": program})


def program_students(session, program):
	"""Students enrolled in the program in the session's year, less those on a break of study (P2-T21) and those
	whose examinations the university runs (Affiliated mode, M06-10)."""
	year = frappe.db.get_value("Academic Term", session.academic_term, "academic_year")
	students = frappe.get_all(
		"Program Enrollment",
		{"program": program, "academic_year": year, "docstatus": 1, "oc_company": session.company},
		pluck="student",
		distinct=True,
	)
	students = set(students) - students_on_break(students)
	modes = examination_modes(student_regulations(students))
	return sorted(s for s in students if modes[s] != AFFILIATED)


def check_configuration(session, students):
	"""Refuse the run, listing every incomplete course, when an offering of the students in the session's term
	has no curriculum row or course type, or a course type a student's Exam Rule Set does not cover (M06-12)."""
	courses = offered_courses(session.academic_term, students)
	regulations = {r for course in courses for r in course["regulations"]}
	gaps = result_rules.configuration_gaps(courses, *regulation_rule_types(regulations))
	if gaps:
		listed = "".join(f"<li>{frappe.bold(escape_html(label))}: {escape_html(reason)}</li>" for label, reason in gaps)
		frappe.throw(
			_("The Result Run cannot start: these courses are not fully configured.") + f"<ul>{listed}</ul>",
			title=_("Incomplete course configuration"),
		)


def offered_courses(term, students):
	"""The term's course offerings of `students` as configuration_gaps courses (exam type of their curriculum row)."""
	if not students:
		return []
	group, member = frappe.qb.DocType("Student Group"), frappe.qb.DocType("Student Group Student")
	members = (
		frappe.qb.from_(group).join(member).on(member.parent == group.name)
		.select(group.name, group.course, group.oc_curriculum, group.oc_semester, member.student)
		.where((group.group_based_on == "Course") & (group.academic_term == term) & (member.active == 1))
		.where(member.student.isin(students))
		.orderby(group.name)
		.run(as_dict=True)
	)  # fmt: skip
	regulations = student_regulations({m.student for m in members})
	courses = {}
	for m in members:
		if m.name not in courses:
			courses[m.name] = offered_course(m)
		if regulations[m.student]:
			courses[m.name]["regulations"].add(regulations[m.student])
		else:
			courses[m.name]["unregulated"].add(m.student)
	return list(courses.values())


def student_regulations(students):
	"""{student: regulation or None}: the assigned regulations read at once, the others resolved one by one."""
	assigned = dict(frappe.get_all("Student", {"name": ["in", list(students) or [""]]}, ["name", "oc_regulation"], as_list=True))
	return {student: assigned.get(student) or get_regulation(student) for student in students}


def offered_course(offering):
	row = frappe.db.get_value(
		"Curriculum Course",
		{"parent": offering.oc_curriculum, "parenttype": "Curriculum", "course": offering.course, "semester": offering.oc_semester},
		COURSE_FIELDS,
		as_dict=True,
	)  # fmt: skip
	return {
		"label": f"{offering.course} ({offering.name})", "has_row": bool(row), "exam_type": row and row.exam_type,
		"course_type": row and row.exam_type and course_type(row), "regulations": set(), "unregulated": set(),
	}  # fmt: skip


def regulation_rule_types(regulations):
	"""({regulation: course types its Exam Rule Set covers}, regulations with more than one Exam Rule Set) of those
	of `regulations` with an Exam Rule Set."""
	rule_sets = dict(frappe.get_all("Exam Rule Set", {"regulation": ["in", list(regulations) or [""]]}, ["name", "regulation"], as_list=True))
	counts = Counter(rule_sets.values())
	types = {regulation: set() for regulation in rule_sets.values()}
	for row in frappe.get_all(
		"Exam Rule Set Type", {"parent": ["in", list(rule_sets) or [""]], "parenttype": "Exam Rule Set"}, ["parent", "course_type"]
	):
		types[rule_sets[row.parent]].add(row.course_type)
	return types, {regulation for regulation, count in counts.items() if count > 1}


def run_student(student, run):
	"""Bulk handler: (re)compute one student's Student Result for the run's session."""
	exam_session = run.get_parameters()["exam_session"]
	return compute_student_result(student, exam_session, run_cohorts(run, exam_session))


def run_cohorts(run, exam_session):
	"""The relative grading cohorts of one bulk run, read once per worker process."""
	key = (run.name, str(run.creation))
	cached = getattr(frappe.local, "campus_result_cohorts", None)
	if not cached or cached[0] != key:
		cached = frappe.local.campus_result_cohorts = (key, new_cohorts(exam_session))
	return cached[1]


def new_cohorts(exam_session, frozen=None):
	"""Cohorts of the session: the bands frozen at publication once Published (unless `frozen` is False), else live
	(also for a session published before bands were frozen)."""
	term, status, stored = frappe.db.get_value("Exam Session", exam_session, ["academic_term", "status", "frozen_bands"])
	bands = json.loads(stored) if frozen is not False and status == PUBLISHED and stored else None
	return Cohorts(exam_session, lambda student: eligibility_status(student, term) == "Shortage", bands, record=status != PUBLISHED)


def compute_student_result(student, exam_session, cohorts=None):
	"""Create or replace (before publication) or version (after) the Student Result of `student` in `exam_session`;
	returns the name of its latest version."""
	session = frappe.db.get_value(
		"Exam Session", exam_session, ["name", "company", "academic_term", "status", "is_final_year"], as_dict=True, for_update=True
	)
	refuse_affiliated_session(exam_session, _("the Result Run"))
	if examination_mode(student) == AFFILIATED:
		frappe.throw(_("The university grades {0} (Affiliated mode); import the university's results.").format(frappe.bold(student)))
	run = StudentRun(student, session, cohorts or new_cohorts(exam_session))
	return save_version(student, session, run.values())


class StudentRun:
	"""One student's Result Run in one session."""

	def __init__(self, student, session, cohorts):
		self.student, self.session, self.cohorts = student, session, cohorts
		self.rule_set = get_rule(student, "Exam Rule Set")
		self.scheme = get_rule(student, "Grading Scheme")
		self.excluded = {row.course_category for row in self.scheme.get("gpa_excluded_categories", [])}
		self.moderation = approved_adjustments(session.name)
		self.history = earlier_rows(student, session.name, session.academic_term)
		self.short_of_attendance = cohorts.short(student)
		self.revalued = revised_ese(student, session.name)  # Revaluation Outcomes (P2-T20), after publication only

	def values(self):
		rows = [row for row in self.current_rows() + self.arrear_rows() if row]
		self.give_grace(rows)
		for row in rows:
			if row["result"] == rules.PASS:
				self.grade(row)
		current = [r for r in rows if r["kind"] == CURRENT]
		attempts = self.history + rows
		outcomes = [(r["course"], r["result"]) for r in attempts]
		values = {
			"courses": [{f: row.get(f) for f in ROW_FIELDS} for row in rows],
			"sgpa": rules.sgpa([(r["credits"], r["grade_point"], r["result"] == rules.PASS) for r in current if r["in_gpa"]]),
			"credits_earned": sum(r["credits"] for r in current if r["result"] == rules.PASS),
			"cgpa": rules.cgpa([(r["course"], r["credits"], r["grade_point"], r["result"] == rules.PASS) for r in attempts if r["in_gpa"]]),
			"result": result_rules.overall_result([r["result"] for r in rows]),
			"arrear_count": len(outstanding_arrears(outcomes)),
		}
		values["classification"] = self.classification(values, outcomes) if self.session.is_final_year else None
		return values

	# ---- courses ------------------------------------------------------------------------------

	def current_rows(self):
		return [self.course_row(offering_course(o.name) | {"offering": o.name}, CURRENT) for o in student_offerings(self.student, self.session.academic_term)]

	def arrear_rows(self):
		rows = []
		for course in arrear_courses(self.student, self.session.name):
			earlier = [r for r in self.history if r["course"] == course and r["course_offering"]]
			if earlier:  # the earlier attempt's offering gives credits and type; the sheet of this session the marks
				rows.append(self.course_row(offering_course(earlier[-1]["course_offering"]) | {"offering": None}, ARREAR))
		return rows

	def course_row(self, course, kind):
		"""The Student Result Course row of one course, or None for a course the Result Run does not grade."""
		if course["exam_type"] == result_rules.INTERNAL_ONLY:  # no end-semester exam
			return None
		if not course["exam_type"]:  # unconfigured: refused, never graded on a guessed type (M06-12)
			frappe.throw(_("Course {0} has no course type.").format(frappe.bold(course["course"])))
		earlier = [r for r in self.history if r["course"] == course["course"]]
		attempt = rules.attempt_number([r["result"] for r in earlier], cint(self.rule_set.absent_counts_as_attempt))
		row = {
			"course": course["course"], "course_offering": course["offering"] or (earlier[-1]["course_offering"] if earlier else None),
			"course_type": course["course_type"], "credits": course["credits"], "kind": kind, "attempt": attempt,
			"cia": 0, "ese": 0, "total": 0, "grade_point": 0, "moderation": 0, "grace": 0,
			"in_gpa": int(rules.counts_in_gpa({"category": course["category"]}, self.excluded)),
		}  # fmt: skip
		if kind == CURRENT and self.short_of_attendance:
			return {**row, "grade": SA, "result": SA}
		withdrawn = withdrawal_code(self.student, self.session.name, course["course"])
		if withdrawn:
			return {**row, "grade": withdrawn, "result": WD}
		absent_in_hall = seating.absent(self.student, self.session.name, course["course"])
		marks = marks_of(self.student, self.session.name, course, kind, required=kind == CURRENT and not absent_in_hall)
		if marks is None and kind == ARREAR and not absent_in_hall:  # no sheet row yet: still owed, nothing graded
			return {**row, "grade": PENDING, "result": PENDING}
		marks = marks or frappe._dict(cia=None, ese=0, absent=0)
		if course["course"] in self.revalued and not marks.absent:
			marks.ese = self.revalued[course["course"]]
		if kind == ARREAR:
			carried = [r["cia"] for r in earlier if r["result"] in SAT]
			marks.cia = result_rules.arrear_cia(carried, marks.cia, cint(self.rule_set.cia_carry_forward))
		if marks.absent or absent_in_hall:
			return {**row, "cia": flt(marks.cia), "grade": AB, "result": AB}
		limits = student_limits(self.student, course)
		moderation = flt(self.moderation.get(course["course"]))
		row.update(
			cia=flt(marks.cia), ese=result_rules.combined_ese(flt(marks.ese), moderation, 0, limits["ese_max"]),
			moderation=moderation, _limits=limits,
		)  # fmt: skip
		return self.judge(row)

	def judge(self, row):
		"""Pass or Fail on the row's CIA and ESE; a pass keeps the 0-100 mark it is graded on."""
		limits, attempt = row["_limits"], row["attempt"]
		row["total"] = rules.round_half_up(rules.total_pct(row["cia"], row["ese"], limits["cia_max"], limits["ese_max"]), 2)
		basis = rules.pass_basis(
			row["cia"], row["ese"], limits["cia_max"], limits["ese_max"], limits["ese_min_pct"], limits["total_min_pct"],
			attempt=attempt, ese_only_from_attempt=limits["ese_only_from_attempt"], ese_only_min_pct=limits["ese_only_min_pct"],
		)  # fmt: skip
		if not basis:
			return {**row, "grade": FAIL, "grade_point": 0, "result": rules.FAIL}
		applies = rules.ese_alone_applies(attempt, limits["ese_only_from_attempt"])
		row["_mark"] = rules.graded_mark(row["cia"], row["ese"], limits["cia_max"], limits["ese_max"], applies)
		return {**row, "result": rules.PASS}

	# ---- grace and grades ---------------------------------------------------------------------

	def give_grace(self, rows):
		failed = {r["course"]: r for r in rows if r["result"] == rules.FAIL and "_limits" in r}
		needs = {}
		for course, row in failed.items():
			limits = row["_limits"]
			alone = limits["ese_only_min_pct"] if rules.ese_alone_applies(row["attempt"], limits["ese_only_from_attempt"]) else None
			need = result_rules.grace_needed(
				row["cia"], row["ese"], limits["cia_max"], limits["ese_max"], limits["ese_min_pct"], limits["total_min_pct"], alone
			)
			if need:
				needs[course] = need
		for course, marks in result_rules.allocate_grace(needs, self.rule_set.as_dict()).items():
			row = failed[course]
			row.update(ese=row["ese"] + marks, grace=marks, grace_rule=self.rule_set.name)
			row.update(self.judge(row))

	def grade(self, row):
		method_row = next((m for m in self.scheme.get("methods", []) if m.course_type == row["course_type"]), None)
		configured = method_row and method_row.method
		method = rules.ABSOLUTE if not configured or row["course_type"] in rules.ALWAYS_ABSOLUTE else configured
		bands = None
		if method == rules.RELATIVE:  # the cohort (or the bands frozen at publication) decides
			grades = [g.as_dict() for g in self.scheme.grades]
			bands = self.cohorts.relative_bands(row["course"], self.scheme.name, row["course_type"], method_row, grades)
			method = rules.RELATIVE if bands else rules.ABSOLUTE
		if bands:
			letter, point = rules.relative_grade(row["_mark"], bands)
		else:
			table = self.scheme.online_grades if method == rules.ONLINE else self.scheme.grades
			letter, point = rules.grade(row["_mark"], [g.as_dict() for g in table])
		row.update(grade=letter, grade_point=point, grading_method=method)

	# ---- classification -----------------------------------------------------------------------

	def classification(self, values, outcomes):
		"""The class of a final-year result with no arrears, by the regulation's Classification Rule (or None)."""
		if values["arrear_count"] or not values["courses"]:
			return None
		rule = frappe.db.get_value("Classification Rule", {"regulation": get_regulation(self.student)})
		if not rule:
			return None
		by_course = {}
		for course, result in outcomes:
			by_course.setdefault(course, []).append(result)
		lateral, batch = frappe.db.get_value("Student", self.student, ["oc_lateral_entry", "oc_batch"])
		found = rules.classify(
			values["cgpa"], [c.as_dict() for c in frappe.get_doc("Classification Rule", rule).classes],
			first_appearance=rules.passed_at_first_appearance(by_course),
			years_taken=study_years(batch, self.session.academic_term), break_years=break_years(self.student),
			entry_type=rules.LATERAL if cint(lateral) else rules.REGULAR,
		)  # fmt: skip
		return found[0] if found else None


# ---- reads ------------------------------------------------------------------------------------


def arrear_courses(student, exam_session):
	"""Courses the student's Exam Registration of the session lists as an eligible Arrear."""
	registration = frappe.db.get_value("Exam Registration", {"exam_session": exam_session, "student": student})
	if not registration:
		return []
	return frappe.get_all(
		"Exam Registration Course",
		{"parent": registration, "parenttype": "Exam Registration", "kind": ARREAR, "eligibility": "Eligible"},
		pluck="course",
		order_by="idx",
	)


def marks_of(student, exam_session, course, kind, required=True):
	"""{cia, ese, absent} of the student's row on the session's sheet of the offering (current) or course (arrear);
	without a row, an error when `required`, else None."""
	filters = {"exam_session": exam_session}
	filters.update({"course_offering": course["offering"]} if kind == CURRENT else {"course": course["course"]})
	sheets = frappe.get_all("Mark Sheet Entry", filters, pluck="name")
	marks = sheets and frappe.db.get_value(
		"Mark Sheet Entry Row",
		{"parent": ["in", sheets], "parenttype": "Mark Sheet Entry", "student": student},
		["cia", "ese", "absent"],
		as_dict=True,
	)
	if not marks and not required:
		return None
	if not marks:
		frappe.throw(
			_("No marks entered for {0} in {1}.").format(frappe.bold(student), frappe.bold(course["offering"] or course["course"]))
		)
	return marks


def earlier_rows(student, exam_session, term):
	"""Course rows (dicts) of the student's latest result versions of other sessions whose term starts no later
	than `term`, oldest first."""
	start = frappe.db.get_value("Academic Term", term, "term_start_date")
	result, course, academic_term = (frappe.qb.DocType(n) for n in (RESULT, "Student Result Course", "Academic Term"))
	return (
		frappe.qb.from_(result)
		.join(course)
		.on((course.parent == result.name) & (course.parenttype == RESULT))
		.join(academic_term)
		.on(academic_term.name == result.academic_term)
		.select(course.course, course.course_offering, course.credits, course.cia, course.grade_point, course.result, course.in_gpa)
		.where((result.student == student) & (result.exam_session != exam_session) & (result.is_latest == 1))
		.where(academic_term.term_start_date <= start)
		.orderby(academic_term.term_start_date)
		.orderby(result.creation)
		.orderby(course.idx)
		.run(as_dict=True)
	)


def study_years(batch, term):
	"""Whole years from the start of the student's batch year to the end of `term` (0 when the batch is unknown)."""
	begun = batch and frappe.db.get_value("Academic Year", batch, "year_start_date")
	ended = frappe.db.get_value("Academic Term", term, "term_end_date")
	if not (begun and ended):
		return 0
	return math.ceil((getdate(ended) - getdate(begun)).days / 365.25)


def break_years(student):
	"""Whole years of the student's approved breaks of study (P2-T21)."""
	if not frappe.db.table_exists("Break of Study"):
		return 0
	days = sum(frappe.get_all("Break of Study", {"student": student, "docstatus": 1}, pluck="break_days"))
	return math.ceil(days / 365) if days else 0


# ---- versions ---------------------------------------------------------------------------------


def save_version(student, session, values):
	"""Write `values` to the latest version (unpublished session). After publication, a change - or the student's
	first result - makes (or updates) the one pending version, which a Result Ratification publishes; going back to
	the published content drops it."""
	latest = frappe.db.get_value(RESULT, {"student": student, "exam_session": session.name, "is_latest": 1}, ["name", "version"], as_dict=True, for_update=True)
	if latest and session.status != PUBLISHED:
		doc = frappe.get_doc(RESULT, latest.name)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return doc.name
	if not latest and session.status != PUBLISHED:
		doc = new_result(student, session)
		doc.update(values)
		doc.insert(ignore_permissions=True)
		return doc.name
	pending = frappe.db.get_value(RESULT, {"student": student, "exam_session": session.name, "pending_ratification": 1}, "name", for_update=True)
	if latest:
		log = result_rules.change_log(summary(frappe.get_doc(RESULT, latest.name).as_dict()), summary(values))
	else:  # the student's first result after publication: everything is new, and pending too
		log = result_rules.change_log({"sgpa": 0, "cgpa": 0, "courses": []}, summary(values)) or _("First result after publication")
	if latest and not log:
		if pending:
			frappe.delete_doc(RESULT, pending, ignore_permissions=True, force=True)
		return latest.name
	doc = frappe.get_doc(RESULT, pending) if pending else new_result(student, session)
	doc.update({**values, "previous_version": latest and latest.name, "change_log": log, "is_latest": 0, "pending_ratification": 1})
	if pending:
		doc.save(ignore_permissions=True)
	else:
		doc.version = max(frappe.get_all(RESULT, {"student": student, "exam_session": session.name}, pluck="version") or [0]) + 1
		doc.insert(ignore_permissions=True)
	return doc.name


def summary(values):
	return {
		"sgpa": flt(values["sgpa"]),
		"cgpa": flt(values["cgpa"]),
		"arrear_count": cint(values.get("arrear_count")),
		"classification": values.get("classification") or "",
		"courses": [{"course": c["course"], "grade": c["grade"], "result": c["result"], "total": flt(c["total"])} for c in values["courses"]],
	}


def new_result(student, session):
	program = frappe.db.get_value("Program Enrollment", {"student": student, "docstatus": 1}, "program")
	return frappe.get_doc(
		{
			"doctype": RESULT, "student": student, "exam_session": session.name, "company": session.company,
			"academic_term": session.academic_term, "program": program, "regulation": get_regulation(student),
			"version": 1, "is_latest": 1,
		}
	)  # fmt: skip


