"""M03-04, M03-07, M05-03 Course Registration: a student's semester course selection, approved advisor -> HOD.

Credits come from the student's Effective curriculum. The limits come from the regulation's
Registration Rule (credit cap, drop, add, elective seat cap); the Registration Window gives the dates
and may override the cap. Seats are counted from offering Student Group membership under a row lock
on the Elective Group, and final approval enrolls the student exactly once.

M03-08: a registration is bound to the Program Enrollment it was made for (apply and cancel use that one),
the credit cap counts the student's other submitted registrations of the term, and the window deadline holds
for every save of a draft; a late registration needs a reason and Dean Academics' authorisation.

Prerequisites (M03-07) are met only by a Pass in a published result (curriculum.api.unmet_prerequisites). A row
without that evidence is held with the reason (hold_reason): the registration saves and goes to review, and final
approval is refused while a row is held. Both re-evaluate on every save and on submit, so a result published
meanwhile releases the hold. Honours / Minor rows need the Registration Rule's CGPA over the curriculum's courses up
to its semester, and Honours no outstanding arrear (examinations.api.cgpa, arrear_courses).
"""

from functools import cached_property

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import cint, getdate

from campus.campus_platform.api import ApprovableDocument, get_regulation, get_rule, latest_enrollment
from campus.curriculum import registration_rules as rules
from campus.curriculum.api import effective_curriculum, unmet_prerequisites
from campus.curriculum.enrollment import (
	count_members,
	current_offering,
	enroll,
	find_offering,
	unenroll,
)

RULE = "Registration Rule"
LATE_ROLES = {"Dean Academics", "System Manager"}


class CourseRegistration(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.set_context()
		self.fill_items()
		self.check_items()
		window = self.get_window()
		self.check_window(window)
		problems = self.rule_problems(window) + self.seat_problems(lock=False)
		if problems:
			frappe.throw("<br>".join(problems), title=_("Registration Rules Not Met"))
		self.report_holds()

	def before_submit(self):
		super().before_submit()
		self.refuse_holds()
		self.assign_offerings()
		problems = self.credit_problems(self.get_window(), lock=True) + self.seat_problems(lock=True)
		if problems:
			frappe.throw("<br>".join(problems), title=_("Registration Rules Not Met"))

	def on_submit(self):
		self.apply_rows(enrolling=True)

	def on_cancel(self):
		self.apply_rows(enrolling=False)

	@cached_property
	def rule(self):
		return get_rule(self.student, RULE)

	@cached_property
	def regulation_code(self):
		return frappe.db.get_value("Regulation", self.regulation, "code")

	def set_context(self):
		student = frappe.db.get_value("Student", self.student, ["oc_company"], as_dict=True)
		enrollment = self.bind_enrollment()
		self.company = student.oc_company
		if not has_user_permission(frappe.get_doc("Student", self.student)):  # Company User Permissions
			frappe.throw(_("You are not permitted to register {0}.").format(frappe.bold(self.student)), frappe.PermissionError)
		self.department = frappe.db.get_value("Program", enrollment.program, "department")
		self.regulation = get_regulation(self.student)
		batch = frappe.db.get_value("Student", self.student, "oc_batch") or enrollment.academic_year
		self.curriculum = effective_curriculum(enrollment.program, self.regulation, batch)
		if not self.curriculum:
			frappe.throw(
				_("No Effective curriculum of regulation {0} for programme {1}.").format(
					frappe.bold(self.regulation), frappe.bold(enrollment.program)
				)
			)
		if not self.class_group:
			self.class_group = find_class_group(self.student, enrollment.program)

	def bind_enrollment(self):
		"""The Program Enrollment this registration is for: the stored (or given) one, else the student's latest.
		Stored once at creation; the field is set-only-once."""
		if self.program_enrollment:
			enrollment = frappe.db.get_value(
				"Program Enrollment",
				{"name": self.program_enrollment, "student": self.student, "docstatus": ["<", 2]},
				["program", "academic_year", "name"],
				as_dict=True,
			)
			if not enrollment:
				frappe.throw(
					_("{0} is not an enrollment of {1}.").format(frappe.bold(self.program_enrollment), frappe.bold(self.student))
				)
			return enrollment
		enrollment = latest_enrollment(self.student)
		if not enrollment:
			frappe.throw(_("Student {0} has no Program Enrollment.").format(frappe.bold(self.student)))
		self.program_enrollment = enrollment.name
		return enrollment

	def fill_items(self):
		by_course = {}
		for row in frappe.get_doc("Curriculum", self.curriculum).courses:
			by_course.setdefault(row.course, []).append(row)
		self.curriculum_rows = {}
		for item in self.items:
			candidates = by_course.get(item.course)
			if not candidates:
				frappe.throw(_("Row {0}: {1} is not in curriculum {2}.").format(item.idx, frappe.bold(item.course), self.curriculum))
			row = self.pick_curriculum_row(item, candidates)
			item.update(
				{
					"credits": row.credits, "semester": row.semester, "category": row.category,
					"is_elective": row.is_elective, "elective_group": row.elective_group,
				}
			)  # fmt: skip
			self.curriculum_rows[item.course] = row
		self.total_credits = 0

	def pick_curriculum_row(self, item, candidates):
		"""The curriculum row of the course for this semester. A Regular course must be in this semester;
		Arrear, Dropped, Additional, Honours and Minor courses may come from any semester of the curriculum."""
		same_semester = [r for r in candidates if r.semester == cint(self.semester)]
		if same_semester:
			return same_semester[0]
		if item.registration_type == "Regular":
			frappe.throw(
				_("Row {0}: {1} is not a semester {2} course of curriculum {3}; register it as Arrear or Additional.").format(
					item.idx, frappe.bold(item.course), self.semester, self.curriculum
				)
			)
		return candidates[0]

	def check_items(self):
		seen, self.flags.passed_cache = set(), {}  # the student's passes, read once for every row
		for item in self.items:
			if item.course in seen:
				frappe.throw(_("Row {0}: {1} is listed twice.").format(item.idx, frappe.bold(item.course)))
			seen.add(item.course)
			registered = current_offering(self.student, item.course, self.academic_term)
			if item.registration_type == "Dropped" and not registered:
				frappe.throw(_("Row {0}: {1} is not registered this term, so it cannot be dropped.").format(item.idx, frappe.bold(item.course)))
			if item.registration_type != "Dropped" and registered:
				frappe.throw(_("Row {0}: {1} is already registered this term.").format(item.idx, frappe.bold(item.course)))
			self.check_prerequisites(item)

	def check_prerequisites(self, item):
		"""Hold the row (with the reason) while a prerequisite has no Pass in a published result."""
		prerequisites = self.curriculum_rows[item.course].prerequisites
		missing = unmet_prerequisites(self.student, prerequisites, self.flags.passed_cache) if item.registration_type != "Dropped" else []
		item.hold_reason = rules.hold_reason(missing)

	def held_rows(self):
		return [_("Row {0}: {1}: {2}").format(i.idx, i.course, i.hold_reason) for i in self.items if i.hold_reason]

	def report_holds(self):
		held = self.held_rows()
		if held:
			frappe.msgprint("<br>".join(held), title=_("Held For Review"), indicator="orange")

	def refuse_holds(self):
		held = self.held_rows()
		if held:
			frappe.throw(
				"<br>".join(held) + "<br>" + _("A held row cannot be approved; drop it or wait for the published result."),
				title=_("Rows Held For Review"),
			)

	def get_window(self):
		program = frappe.db.get_value("Curriculum", self.curriculum, "program")
		windows = frappe.get_all(
			"Registration Window",
			filters={"academic_term": self.academic_term, "company": self.company},
			or_filters=[["program", "=", program], ["program", "is", "not set"]],
			fields=["name", "opens_on", "closes_on", "drop_until", "max_credits", "program"],
			order_by="program desc",
			limit=1,
		)
		return windows[0] if windows else None

	def check_window(self, window):
		"""Registering courses needs an open window on the registration date and on the day of the save, so
		backdating, re-saving and amending a draft all meet the deadline. Drops are governed by the drop deadline.

		Submitting is not checked: approval may complete after the window closes. A closed window is
		overridden only by a late registration: a reason and Dean Academics' authorisation.
		"""
		if self.docstatus != 0 or all(i.registration_type == "Dropped" for i in self.items):
			return
		dates = [getdate(self.registration_date), getdate()]
		closed = [d for d in dates if not window or not getdate(window.opens_on) <= d <= getdate(window.closes_on)]
		if closed:
			return self.authorise_late(closed[0])
		if self.is_new():
			self.late_approved_by = None

	def authorise_late(self, date):
		"""Keep the stored authorisation of a saved draft whose courses are unchanged, else take the session user
		if they may authorise."""
		kept = (
			bool(self.late_approved_by)
			and not self.is_new()
			and not self.has_value_changed("late_approved_by")
			and not self.courses_changed()
		)
		if self.late_reason and (kept or LATE_ROLES & set(frappe.get_roles())):
			self.late_approved_by = self.late_approved_by if kept else frappe.session.user
			return
		frappe.throw(
			_(
				"Registration for {0} is not open on {1}. A late registration needs a reason and the authorisation of Dean Academics."
			).format(frappe.bold(self.academic_term), date)
		)

	def courses_changed(self):
		before = self.get_doc_before_save()
		courses = lambda doc: [(i.course, i.registration_type) for i in doc.items]  # noqa: E731
		return not before or courses(before) != courses(self)

	def rule_problems(self, window):
		rule = self.rule
		rows = [(i.registration_type, i.credits) for i in self.items]
		prefix = lambda field: rules.clause(self.regulation_code, rule.get(field))  # noqa: E731
		excluded = rules.excluded_types(rule.excluded_types)
		self.total_credits = rules.counted_credits(rows, excluded)
		term_start = frappe.db.get_value("Academic Term", self.academic_term, "term_start_date")
		deadline = rules.drop_deadline(term_start, rule.drop_window_days, window and window.drop_until)
		return (
			self.credit_problems(window, lock=False)
			+ rules.drop_problems(rows, self.registration_date, deadline, rule.max_drop_credits, prefix("drop_clause"))
			+ rules.add_problems(rows, self.semester, rule, prefix("add_clause"))
			+ self.choose_problems(prefix("elective_clause"))
			+ self.honours_problems(prefix("honours_clause"))
		)

	def honours_problems(self, prefix):
		kinds = {i.registration_type for i in self.items}
		if not kinds & {rules.HONOURS, rules.MINOR}:
			return []
		from campus.examinations.api import arrear_courses, cgpa  # lazy: examinations.api pulls in the finance stack

		upto = cint(self.rule.honours_cgpa_upto_semester)
		filters = {"parent": self.curriculum, "parenttype": "Curriculum", **({"semester": ["<=", upto]} if upto else {})}
		courses = set(frappe.get_all("Curriculum Course", filters, pluck="course"))
		return rules.honours_problems(kinds, cgpa(self.student, courses), arrear_courses(self.student), self.rule, prefix)

	def credit_problems(self, window, lock):
		"""The credit cap over the student's other submitted registrations of the term plus this one. Every
		submitted row counts, so a submitted drop does not free the credits of the registration it drops
		(conservative; a drop row itself counts 0 only where the rule excludes Dropped).
		With `lock` the Student row is locked and the others are read with locking reads, so two registrations
		submitted at once cannot both pass."""
		rule = self.rule
		if lock:
			frappe.db.get_value("Student", self.student, "name", for_update=True)
		rows = self.registered_rows(lock) + [(i.registration_type, i.credits) for i in self.items]
		limit = (window and window.max_credits) or rule.max_credits_per_semester
		prefix = rules.clause(self.regulation_code, rule.max_credits_clause)
		return rules.credit_limit_problems(rows, limit, rules.excluded_types(rule.excluded_types), prefix)

	def registered_rows(self, lock):
		"""(registration_type, credits) of the rows of the student's other active registrations of the term."""
		registration = frappe.qb.DocType("Course Registration")
		item = frappe.qb.DocType("Course Registration Item")
		query = (
			frappe.qb.from_(registration)
			.join(item)
			.on(item.parent == registration.name)
			.select(item.registration_type, item.credits)
			.where((registration.student == self.student) & (registration.academic_term == self.academic_term))
			.where((registration.docstatus == 1) & (registration.name != (self.name or "")))
		)
		return [tuple(row) for row in (query.for_update() if lock else query).run()]

	def choose_problems(self, prefix):
		"""No more electives of one group than the group allows."""
		picked = {}
		for item in self.items:
			if item.elective_group and item.registration_type != "Dropped":
				picked.setdefault(item.elective_group, []).append(item.course)
		in_this = {item.course for item in self.items}
		problems = []
		for group, courses in picked.items():
			choose = frappe.db.get_value("Elective Group", group, "choose_n")
			chosen = len(courses) + len(self.held_in_group(group, in_this))
			if chosen > choose:
				problems.append(prefix + _("elective group {0} allows {1} course(s); {2} chosen.").format(group, choose, chosen))
		return problems

	def held_in_group(self, group, skip):
		"""Courses of the elective group the student already holds a seat in, from earlier registrations."""
		courses = frappe.get_all(
			"Curriculum Course", {"parent": self.curriculum, "elective_group": group}, pluck="course"
		)
		return [c for c in courses if c not in skip and current_offering(self.student, c, self.academic_term)]

	def seat_problems(self, lock):
		"""Seat-cap messages for the electives being added. With `lock` the Elective Group row is locked
		FOR UPDATE first, so concurrent registrations for the last seat serialise: the loser counts
		the winner's membership and fails."""
		prefix = rules.clause(self.regulation_code, self.rule.elective_clause)
		problems = []
		for item in sorted(self.elective_items(), key=lambda i: (i.elective_group, i.course)):
			cap = frappe.db.get_value(
				"Elective Group", item.elective_group, "seat_cap_per_course", for_update=bool(lock)
			)
			enrolled = count_members(self.curriculum, item.course, self.academic_term, lock=lock)
			problem = rules.seat_problem(item.course, enrolled, cap, prefix)
			problems += [problem] if problem else []
		return problems

	def elective_items(self):
		return [i for i in self.items if i.elective_group and i.registration_type != "Dropped"]

	def assign_offerings(self):
		section = frappe.db.get_value("Student Group", self.class_group, "oc_section") if self.class_group else None
		for item in self.items:
			if item.registration_type == "Dropped":
				item.offering = current_offering(self.student, item.course, self.academic_term)
				continue
			item.offering = find_offering(self.curriculum, item.course, self.academic_term, section)
			if item.offering and frappe.db.get_value("Student Group", item.offering, "oc_company") != self.company:
				frappe.throw(_("Row {0}: the offering belongs to another company.").format(item.idx))
			if not item.offering:
				frappe.throw(_("Row {0}: no offering of {1} exists for {2}.").format(item.idx, frappe.bold(item.course), self.academic_term))

	def apply_rows(self, enrolling):
		"""Enroll (or on cancel, reverse) every row; a drop does the opposite of a registration."""
		for item in self.items:
			if (item.registration_type == "Dropped") == enrolling:
				unenroll(self.student, item, self.program_enrollment)
			else:
				enroll(self.student, item, self.program_enrollment, self.registration_date)


def find_class_group(student, program):
	"""The student's active Batch group of `program`, if any (scopes the Class Advisor approval)."""
	group = frappe.qb.DocType("Student Group")
	member = frappe.qb.DocType("Student Group Student")
	rows = (
		frappe.qb.from_(group)
		.join(member)
		.on(member.parent == group.name)
		.select(group.name)
		.where((member.student == student) & (group.group_based_on == "Batch"))
		.where((group.program == program) & (group.disabled == 0))
		.orderby(group.creation)
		.limit(1)
		.run()
	)
	return rows[0][0] if rows else None
