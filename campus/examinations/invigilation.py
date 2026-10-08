"""M06-02 Invigilation roster: invigilators for every Exam Hall used in the session's Seating Plans.

The faculty pool is the roster's table, or every active teacher (Employee with an Instructor record) of the
company when it is empty. invigilation_rules balances duties per session type (FN / AN) within one and keeps
out a teacher of a course written in the hall (an instructor of that course's offering in the session's term)
and anyone on approved leave that day (the faculty service's leave check, as Substitutions use). A hall nobody
may take refuses the roster. The largest per-type gap is stored (duty_spread) and a gap above one is warned.
"""

import frappe
from frappe import _

from campus.examinations import invigilation_rules
from campus.examinations.access import COE_ROLE

DOCTYPE = "Invigilation Roster"


def roster_name(exam_session):
	return f"IVR-{exam_session}"


def generate(roster):
	"""(Re)build the roster's duties; returns the number of duties."""
	frappe.only_for((COE_ROLE, "System Manager"))
	doc = frappe.get_doc(DOCTYPE, roster, for_update=True)
	doc.check_permission("write")
	if not doc.faculty:
		doc.set("faculty", [{"employee": e} for e in company_teachers(doc.company)])
	faculty = sorted(row.employee for row in doc.faculty)
	halls = session_halls(doc.exam_session)
	duties, unfilled = invigilation_rules.assign(
		halls, faculty, own_courses(faculty, doc.exam_session), leave_days(faculty, halls), doc.invigilators_per_hall
	)
	if unfilled:
		names = ", ".join(sorted({f"{h.room} ({frappe.utils.formatdate(h.date)} {h.slot})" for h in unfilled}))
		frappe.throw(_("No free invigilator for {0}. Add faculty to the pool.").format(names))
	people = dict(frappe.get_all("Employee", {"name": ["in", faculty or [""]]}, ["name", "employee_name"], as_list=True))
	doc.set(
		"duties",
		[{"exam_date": h.date, "slot": h.slot, "room": h.room, "employee": e, "employee_name": people.get(e)} for h, e in duties],
	)
	gaps = invigilation_rules.spread(duties, faculty)
	doc.duty_spread = max(gaps.values(), default=0)
	doc.flags.generating = True
	doc.save()
	for slot, gap in gaps.items():
		if gap > 1:
			frappe.msgprint(
				_("{0} duties differ by {1} between faculty: leave or own-course exclusions leave no fairer roster. Widen the pool.").format(slot, gap),
				indicator="orange", alert=True,
			)
	return len(doc.duties)


def session_halls(exam_session):
	"""invigilation_rules.Hall of every hall with a seated student in the session's Seating Plans."""
	halls = {}
	for plan in frappe.get_all("Seating Plan", {"exam_session": exam_session}, ["name", "exam_date", "slot"]):
		for seat in frappe.get_all("Seating Plan Seat", {"parenttype": "Seating Plan", "parent": plan.name}, ["room", "course"]):
			halls.setdefault((str(plan.exam_date), plan.slot, seat.room), set()).add(seat.course)
	return [invigilation_rules.Hall(d, s, r, frozenset(c)) for (d, s, r), c in halls.items()]


def company_teachers(company):
	instructors = frappe.get_all("Instructor", {"employee": ["is", "set"]}, pluck="employee")
	return sorted(
		frappe.get_all("Employee", {"name": ["in", instructors or [""]], "company": company, "status": "Active"}, pluck="name")
	)


def own_courses(faculty, exam_session):
	"""{employee: courses they teach in the session's term}."""
	term = frappe.db.get_value("Exam Session", exam_session, "academic_term")
	taught = {}
	for employee in faculty:
		instructors = frappe.get_all("Instructor", {"employee": employee}, pluck="name") or [""]
		groups = frappe.get_all("Student Group Instructor", {"instructor": ["in", instructors], "parenttype": "Student Group"}, pluck="parent")
		taught[employee] = set(
			frappe.get_all("Student Group", {"name": ["in", groups or [""]], "academic_term": term}, pluck="course")
		)
	return taught


def leave_days(faculty, halls):
	from campus.faculty.api import on_leave

	dates = sorted({h.date for h in halls})
	return {(e, d) for e in faculty for d in dates if on_leave(e, d)}
