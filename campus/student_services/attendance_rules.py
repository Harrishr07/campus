"""M05-02 Attendance eligibility maths. Pure functions: thresholds come from an Attendance Rule record.

Decision, for one student and term (courses with nothing conducted are ignored):
- Eligible: overall % >= overall minimum and, when a per-course minimum is set, every course % >= it.
- Medical band: not Eligible, but the student has approved medical leave and, counting those leave
  periods as attended, overall % >= the medical band minimum and every course % still meets the
  per-course minimum. Leave counts only here, never in the reported percentages.
- Shortage (SA): otherwise.
Leave kinds (Student Leave Application `oc_leave_kind`), per the rule:
- On Duty counts as attended (in the reported percentages) only when the rule's `od_counts` is set.
- Medical leave is the "leave" above only when the rule's `medical_counts` is set.
- Plain Leave never counts.
Attendance marks (CIA): the course % rounded to a whole number picks the Attendance Rule's mark band.
Overall % is all attended / all conducted (`sum_based`) or the mean of the course % (`course_average`).
With nothing conducted at all there is nothing to fall short of: Eligible, overall None.

M05-12 class sessions (Course Schedule `oc_session_state`): only held sessions are conducted. A session counts when it
is Conducted, a Makeup, or Scheduled (a past session nobody cancelled is taken as held, as before session states
existed); Cancelled and Rescheduled sessions drop out, and so does a session a Makeup replaces. A Rescheduled
session's new session counts on its own date, so the period counts once. Per counted session the student's mark is
their record; an approved leave covering the session turns anything but Present into Leave of that kind.
"""

ELIGIBLE = "Eligible"
MEDICAL_BAND = "Medical band"
SHORTAGE = "Shortage"

ATTENDED = "attended"
MEDICAL_LEAVE = "leave"

PRESENT, ON_LEAVE = "Present", "Leave"
ON_DUTY, MEDICAL = "On Duty", "Medical"

SCHEDULED, CONDUCTED, CANCELLED, RESCHEDULED, MAKEUP = "Scheduled", "Conducted", "Cancelled", "Rescheduled", "Makeup"
SESSION_STATES = (SCHEDULED, CONDUCTED, CANCELLED, RESCHEDULED, MAKEUP)
HELD_STATES = (SCHEDULED, CONDUCTED, MAKEUP)


def bucket(status, leave_kind, rule):
	"""How one submitted attendance record counts: ATTENDED, MEDICAL_LEAVE or None.

	`leave_kind` is the kind of the submitted Student Leave Application backing a Leave record, else None.
	"""
	if status == PRESENT:
		return ATTENDED
	if status != ON_LEAVE:
		return None
	if leave_kind == ON_DUTY and rule["od_counts"]:
		return ATTENDED
	if leave_kind == MEDICAL and rule["medical_counts"]:
		return MEDICAL_LEAVE
	return None


def session_counts(state, replaced):
	"""Whether a class session dated in the window is conducted (in the denominator). A blank state is Scheduled."""
	return (state or SCHEDULED) in HELD_STATES and not replaced


def session_mark(status, leave_kind, covering_kind):
	"""(status, leave kind) of one counted session for the student.

	`status` / `leave_kind` come from the student's record (None when unmarked), `covering_kind` is the kind of a
	submitted Student Leave Application covering the session, else None. Present, and a Leave record backed by its own
	application, stand; otherwise a covering leave makes the session Leave of its kind.
	"""
	if status == PRESENT or (status == ON_LEAVE and leave_kind) or not covering_kind:
		return status, leave_kind
	return ON_LEAVE, covering_kind


def attendance_marks(bands, pct):
	"""CIA marks for a course percentage. `bands` is a list of (from_pct, to_pct or None, marks).

	The percentage is rounded half up to a whole number first; a band takes from_pct <= pct <= to_pct
	(no to_pct = open ended). No bands, or no band for the percentage, gives 0.
	"""
	whole = int(pct + 0.5)
	for low, high, marks in bands:
		if low <= whole and (high is None or whole <= high):
			return marks
	return 0


def percentage(attended, conducted):
	return attended * 100.0 / conducted if conducted else 0.0


def overall_percentage(formula, courses):
	"""`courses` is a list of (conducted, attended) pairs; None when no period was conducted."""
	held = [(conducted, attended) for conducted, attended in courses if conducted]
	if not held:
		return None
	if formula == "course_average":
		return sum(percentage(attended, conducted) for conducted, attended in held) / len(held)
	return percentage(sum(a for _c, a in held), sum(c for c, _a in held))


def meets_minimums(rule, courses):
	"""True if the overall % and (when set) each course % reach the rule's minimums."""
	overall = overall_percentage(rule["formula"], courses)
	if overall is None:
		return True
	return overall >= rule["overall_min_pct"] and courses_meet(rule["per_course_min_pct"], courses)


def courses_meet(minimum, courses):
	return all(percentage(attended, conducted) >= minimum for conducted, attended in courses if conducted)


def eligibility(rule, courses):
	"""Status for `courses`, a list of (conducted, attended, approved_leave) per course; `rule` a dict."""
	raw = [(conducted, attended) for conducted, attended, _leave in courses]
	if meets_minimums(rule, raw):
		return ELIGIBLE
	with_leave = [(conducted, attended + leave) for conducted, attended, leave in courses]
	if sum(leave for _c, _a, leave in courses) == 0:
		return SHORTAGE
	band_rule = {**rule, "overall_min_pct": rule["medical_band_min_pct"]}
	return MEDICAL_BAND if meets_minimums(band_rule, with_leave) else SHORTAGE
