"""M06-08 integration tests: CIA templates, schedules, question-wise marks with CO / Bloom tags, consolidation
(R2022 theory and lab, R2026 theory with attendance marks), the lock at the deadline, approved unlocks,
permissions and the two CIA reports. Expected values are hand-computed in the comments (AC1-AC4)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, now_datetime

from campus.campus_platform.approvals import approve, request_approval
from campus.examinations import cia
from campus.examinations.doctype.cia_schedule.cia_schedule import DEADLINE_ROLES
from campus.examinations.report.cia_marks_audit_trail.cia_marks_audit_trail import execute as audit_report
from campus.examinations.report.cia_status_by_offering.cia_status_by_offering import execute as status_report
from campus.tests.approval_fixtures import level, make_department
from campus.tests.test_grievances import hold
from campus.tests.test_regulation import make_program
from campus.tests.test_results import (
	COE_USER,
	COLLEGE,
	FACULTY,
	OTHER_FACULTY,
	PROGRAM,
	ExamFixture,
	make_login,
)

HOD_USER = "cia-hod@example.com"
POLICY = "CIA Test Unlock Policy"
# (component, question, max, CO, Bloom level)
THEORY_PATTERN = [
	("Assignment 1", "A", 40, "CO1", "Apply"),
	("Test 1", "Q1", 20, "CO1", "Remember"), ("Test 1", "Q2", 40, "CO2", "Apply"),
	("Assignment 2", "A", 40, "CO3", "Apply"),
	("Test 2", "Q1", 20, "CO3", "Understand"), ("Test 2", "Q2", 40, "CO4", "Analyse"),
]  # fmt: skip
LAB_PATTERN = [
	("Observation and Record", "Record", 75, "CO1", "Apply"),
	("Test", "Q1", 10, "CO2", "Understand"), ("Test", "Q2", 15, "CO3", "Apply"),
]  # fmt: skip
# question marks in pattern order; "AB" marks the student absent from that question's component
THEORY_163 = [32, 15, 30, 36, 18, 32]  # 32 + 45 + 36 + 50 = 163 of 200


class CIAFixture(ExamFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_login(HOD_USER, "HOD")
		department = make_department("CIA Test Department", COLLEGE)
		frappe.db.set_value("Program", PROGRAM, "department", department)
		hold("HOD", department, HOD_USER)
		regulation26 = frappe.db.get_value("Student", cls.s26.name, "oc_regulation")
		if not frappe.db.exists("Attendance Rule", {"regulation": regulation26}):
			frappe.get_doc(
				{
					"doctype": "Attendance Rule", "regulation": regulation26, "formula": "course_average",
					"overall_min_pct": 80, "medical_band_min_pct": 70, "per_course_min_pct": 75,
					"mark_bands": [{"from_pct": lo, "to_pct": hi, "marks": m} for lo, hi, m in ((80, 85, 2), (86, 90, 3), (91, 95, 4), (96, None, 5))],
				}
			).insert()  # fmt: skip
		for day in range(10):  # 9 of 10 present: 90%, band 86-90 -> 3 marks
			mark_attendance(cls.s26.name, cls.offerings26["EXM TH"], day, "Absent" if day == 9 else "Present")

	def setUp(self):
		super().setUp()
		self.addCleanup(
			frappe.set_user, "Administrator"
		)  # helpers switch users; a failing assert must not leak one
		frappe.db.delete(
			"Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.unlock_policies()]}
		)
		frappe.db.delete("Approval Policy", {"document_type": "CIA Unlock Request"})
		frappe.get_doc(
			{"doctype": "Approval Policy", "policy_name": POLICY, "document_type": "CIA Unlock Request",
			"levels": [level("User", COE_USER, title="COE")]}
		).insert()  # fmt: skip

	def regulation(self, student):
		return frappe.db.get_value("Student", student.name, "oc_regulation")

	def unlock_policies(self):
		return frappe.get_all("Approval Policy", {"document_type": "CIA Unlock Request"}, pluck="name") or [
			""
		]

	def schedule(self, offering, pattern, deadline_days=1):
		return frappe.get_doc(
			{
				"doctype": "CIA Schedule", "course_offering": offering,
				"entry_deadline": add_days(now_datetime(), deadline_days),
				"components": [{"component": c, "assessment_date": "2022-11-01"} for c in dict.fromkeys(r[0] for r in pattern)],
				"questions": [
					{"component": c, "question": q, "max_marks": m, "course_outcome": co, "bloom_level": b}
					for c, q, m, co, b in pattern
				],
			}
		).insert()  # fmt: skip

	def sheet(self, offering):
		return frappe.get_doc("Mark Sheet Entry", {"course_offering": offering})

	def enter(self, offering, pattern, marks_by_student, user="Administrator"):
		"""Save the sheet once, as `user`, with question marks in pattern order per student."""
		frappe.set_user(user)
		sheet = self.sheet(offering)
		for student in set(marks_by_student) - {
			row.student for row in sheet.marks
		}:  # ExamFixture left SA students out
			sheet.append("marks", {"student": student})
		sheet.save()  # picks up the schedule's question rows
		rows = {(r.student, r.component, r.question): r for r in sheet.cia_marks}
		for student, marks in marks_by_student.items():
			for (component, question, *_tags), value in zip(pattern, marks, strict=True):
				row = rows[(student, component, question)]
				row.absent, row.marks = (1, 0) if value == "AB" else (0, value)
		sheet.save(ignore_version=False)  # tests skip versions by default
		frappe.set_user("Administrator")
		return sheet

	def cia_of(self, sheet):
		sheet.reload()
		return {row.student: (row.cia, row.cia_attendance) for row in sheet.marks}

	def pass_deadline(self, schedule):
		frappe.db.set_value(
			"CIA Schedule", schedule.name, "entry_deadline", add_to_date(now_datetime(), hours=-1)
		)


def mark_attendance(student, offering, day, status):
	doc = frappe.get_doc(
		{"doctype": "Student Attendance", "student": student, "student_group": offering, "status": status,
		"date": add_days("2022-10-03", day)}
	)  # fmt: skip
	doc.flags.ignore_validate = True  # holiday list and group checks are Education's, not under test
	doc.insert(ignore_permissions=True)
	doc.submit()


class TestCIAConsolidation(CIAFixture):
	def test_r2022_theory_two_assessments_convert_to_40(self):  # AC1
		offering = self.offerings22["EXM TH"]
		schedule = self.schedule(offering, THEORY_PATTERN)
		self.assertEqual(
			schedule.template,
			frappe.db.get_value(
				"CIA Component Template", {"regulation": self.regulation(self.s22), "course_type": "Theory"}
			),
		)
		sheet = self.enter(offering, THEORY_PATTERN, {
			self.s22.name: THEORY_163,  # 163 / 200 x 40 = 32.6 -> 33
			self.s_ab.name: [30, 12, 28, 34, "AB", "AB"],  # absent from Test 2: 104 / 200 x 40 = 20.8 -> 21
			self.s_sa.name: [30, 14.5, 28, 40, 20, 30],  # 162.5 / 200 x 40 = 32.5 -> 33 (half up)
		})  # fmt: skip
		self.assertEqual(
			self.cia_of(sheet), {self.s22.name: (33, 0), self.s_ab.name: (21, 0), self.s_sa.name: (33, 0)}
		)
		self.assertEqual(sheet.cia_schedule, schedule.name)

	def test_r2022_lab_75_plus_25_converts_to_60(self):  # AC2
		offering = self.offerings22["EXM LB"]
		self.schedule(offering, LAB_PATTERN)
		sheet = self.enter(offering, LAB_PATTERN, {
			self.s22.name: [68, 8, 11],  # 87 / 100 x 60 = 52.2 -> 52
			self.s_ab.name: [60, 10, 15],  # 85 / 100 x 60 = 51
			self.s_sa.name: [75, 10, 15],  # 60
		})  # fmt: skip
		self.assertEqual(
			self.cia_of(sheet), {self.s22.name: (52, 0), self.s_ab.name: (51, 0), self.s_sa.name: (60, 0)}
		)

	def test_r2026_theory_adds_attendance_marks_per_band(self):  # AC2
		offering = self.offerings26["EXM TH"]
		self.schedule(offering, THEORY_PATTERN)
		sheet = self.enter(offering, THEORY_PATTERN, {self.s26.name: THEORY_163})
		self.assertEqual(
			self.cia_of(sheet), {self.s26.name: (32, 3)}
		)  # 163 / 200 x 35 = 28.525 -> 29, + 3 (90%)

	def test_co_tagged_question_marks_are_stored(self):  # AC4
		offering = self.offerings22["EXM TH"]
		self.schedule(offering, THEORY_PATTERN)
		sheet = self.enter(offering, THEORY_PATTERN, {self.s22.name: THEORY_163})
		rows = frappe.get_all(
			"Mark Sheet CIA Mark", {"parent": sheet.name, "student": self.s22.name},
			["course_outcome", "bloom_level", "max_marks", "marks"],
		)  # fmt: skip
		by_co = {}
		for row in rows:
			by_co.setdefault(row.course_outcome, [0, 0])
			by_co[row.course_outcome][0] += row.marks
			by_co[row.course_outcome][1] += row.max_marks
		self.assertEqual(by_co, {"CO1": [47, 60], "CO2": [30, 40], "CO3": [54, 60], "CO4": [32, 40]})
		self.assertEqual(
			sorted({r.bloom_level for r in rows}), ["Analyse", "Apply", "Remember", "Understand"]
		)
		self.assertEqual(
			len(sheet.cia_marks), len(sheet.marks) * len(THEORY_PATTERN)
		)  # one row per student and question

	def test_question_marks_above_the_maximum_are_refused(self):
		offering = self.offerings22["EXM TH"]
		self.schedule(offering, THEORY_PATTERN)
		with self.assertRaises(frappe.ValidationError):
			self.enter(offering, THEORY_PATTERN, {self.s22.name: [41, 15, 30, 36, 18, 32]})

	def test_cia_may_be_entered_while_the_session_is_draft_but_ese_may_not(self):
		frappe.db.set_value("Exam Session", self.session.name, "status", "Draft")
		offering = self.offerings22["EXM TH"]
		self.schedule(offering, THEORY_PATTERN)
		sheet = self.enter(offering, THEORY_PATTERN, {self.s22.name: THEORY_163})
		self.assertEqual(self.cia_of(sheet)[self.s22.name], (33, 0))
		sheet.marks[0].ese = 50
		with self.assertRaises(frappe.ValidationError):
			sheet.save()


class TestCIATemplatesAndSchedules(CIAFixture):
	def template(self, student):
		return frappe.get_doc(
			"CIA Component Template", {"regulation": self.regulation(student), "course_type": "Theory"}
		)

	def test_seeded_templates_match_the_regulations(self):
		r22, r26 = self.template(self.s22), self.template(self.s26)
		self.assertEqual([(c.component, c.max_marks, c.weight) for c in r22.components],
			[("Assignment 1", 40, 8), ("Test 1", 60, 12), ("Assignment 2", 40, 8), ("Test 2", 60, 12)])  # fmt: skip
		self.assertEqual((r22.cia_max, r22.includes_attendance_marks), (40, 0))
		self.assertEqual((r26.cia_max, r26.includes_attendance_marks, r26.attendance_max), (40, 1, 5))
		self.assertEqual(sum(c.weight for c in r26.components), 35)

	def test_weights_must_add_up_to_the_converted_maximum(self):
		frappe.db.set_value(
			"Regulation", self.regulation(self.s22), "status", "Draft"
		)  # the seed is locked otherwise
		doc = self.template(self.s22)
		doc.components[0].weight = 9
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_maximum_must_match_the_exam_rule_set(self):
		frappe.db.set_value("Regulation", self.regulation(self.s22), "status", "Draft")
		doc = self.template(self.s22)
		doc.cia_max, doc.components[0].weight = 41, 9  # adds up, but the Exam Rule Set says 40
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_template_locks_with_an_effective_regulation(self):
		doc = self.template(self.s22)
		doc.round_to_integer = 0
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_questions_must_add_up_to_each_component(self):
		pattern = [
			row if row[:2] != ("Test 2", "Q2") else ("Test 2", "Q2", 30, "CO4", "Analyse")
			for row in THEORY_PATTERN
		]
		with self.assertRaises(frappe.ValidationError):
			self.schedule(self.offerings22["EXM TH"], pattern)
		with self.assertRaises(frappe.ValidationError):
			self.schedule(self.offerings22["EXM TH"], [*THEORY_PATTERN, ("Viva", "Q1", 10, "CO1", "Apply")])

	def test_one_schedule_per_offering(self):
		self.schedule(self.offerings22["EXM TH"], THEORY_PATTERN)
		with self.assertRaises(frappe.ValidationError):
			self.schedule(self.offerings22["EXM TH"], THEORY_PATTERN)


class TestCIALock(CIAFixture):
	def locked_sheet(self):
		offering = self.offerings22["EXM TH"]
		schedule = self.schedule(offering, THEORY_PATTERN)
		sheet = self.enter(offering, THEORY_PATTERN, {self.s22.name: THEORY_163}, user=FACULTY)
		self.pass_deadline(schedule)
		return schedule, sheet

	def edit_first_question(self, value, user=FACULTY):
		frappe.set_user(user)
		sheet = self.sheet(self.offerings22["EXM TH"])
		row = next(r for r in sheet.cia_marks if r.student == self.s22.name and r.component == "Assignment 1")
		row.marks = value
		sheet.save(ignore_version=False)  # tests skip versions by default
		frappe.set_user("Administrator")
		return sheet

	def unlock(self, schedule, hours=2):
		frappe.set_user(FACULTY)
		request = frappe.get_doc(
			{"doctype": "CIA Unlock Request", "cia_schedule": schedule.name, "reason": "Assignment 1 re-marked",
			"unlock_until": add_to_date(now_datetime(), hours=hours)}
		).insert()  # fmt: skip
		approval = request_approval("CIA Unlock Request", request.name)
		frappe.set_user(COE_USER)
		approve(approval, None)
		frappe.set_user("Administrator")
		return request.reload()

	def test_after_the_deadline_edits_need_an_approved_unlock(self):  # AC3
		schedule, _sheet = self.locked_sheet()
		self.assertEqual(cia.lock_state(schedule.name), cia.LOCKED)
		for user in (FACULTY, COE_USER, "Administrator"):
			with self.assertRaises(frappe.ValidationError, msg=user):
				self.edit_first_question(20, user)
		request = self.unlock(schedule)
		self.assertEqual(request.docstatus, 1)
		self.assertEqual(cia.lock_state(schedule.name), cia.UNLOCKED)
		sheet = self.edit_first_question(20)  # 151 / 200 x 40 = 30.2 -> 30
		self.assertEqual(self.cia_of(sheet)[self.s22.name], (30, 0))
		frappe.db.set_value(
			"CIA Unlock Request", request.name, "unlock_until", add_to_date(now_datetime(), hours=-1)
		)
		self.assertEqual(cia.lock_state(schedule.name), cia.LOCKED)  # the window has closed
		with self.assertRaises(frappe.ValidationError):
			self.edit_first_question(25)

	def test_ese_marks_stay_editable_after_the_cia_lock(self):
		self.locked_sheet()
		frappe.set_user(FACULTY)
		sheet = self.sheet(self.offerings22["EXM TH"])
		next(r for r in sheet.marks if r.student == self.s22.name).ese = 40
		sheet.save()
		self.assertEqual(self.cia_of(sheet)[self.s22.name], (33, 0))

	def test_unlock_needs_a_locked_schedule_and_approval(self):
		schedule = self.schedule(self.offerings22["EXM TH"], THEORY_PATTERN)
		values = {"doctype": "CIA Unlock Request", "cia_schedule": schedule.name, "reason": "x",
			"unlock_until": add_to_date(now_datetime(), hours=2)}  # fmt: skip
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(values).insert()  # still open
		self.pass_deadline(schedule)
		request = frappe.get_doc(values).insert()
		with self.assertRaises(frappe.ValidationError):
			request.submit()  # a policy matches: only approval submits it
		self.assertEqual(cia.lock_state(schedule.name), cia.LOCKED)

	def test_question_pattern_locks_too(self):
		schedule, _sheet = self.locked_sheet()
		schedule.reload()
		schedule.questions[0].course_outcome = "CO2"
		with self.assertRaises(frappe.ValidationError):
			schedule.save()

	def test_lock_job_consolidates_once_and_stamps_the_schedule(self):
		offering = self.offerings26["EXM TH"]
		schedule = self.schedule(offering, THEORY_PATTERN)
		sheet = self.enter(offering, THEORY_PATTERN, {self.s26.name: THEORY_163})
		frappe.db.set_value(
			"Mark Sheet Entry Row",
			{"parent": sheet.name, "student": self.s26.name},
			{"cia": 0, "cia_attendance": 0},
		)
		self.pass_deadline(schedule)
		cia.lock_schedule(schedule.name)
		self.assertTrue(frappe.db.get_value("CIA Schedule", schedule.name, "locked_on"))
		self.assertEqual(self.cia_of(sheet)[self.s26.name], (32, 3))  # attendance re-read at the lock

	def test_audit_trail_shows_the_unlock_and_the_edits(self):  # AC3
		schedule, _sheet = self.locked_sheet()
		request = self.unlock(schedule)
		self.edit_first_question(20)
		frappe.set_user(COE_USER)
		_columns, rows = audit_report({"company": COLLEGE, "course_offering": self.offerings22["EXM TH"]})
		events = [(r["event"], r["document"]) for r in rows]
		self.assertIn(("Unlock requested", request.name), events)
		self.assertIn(("Unlock approved", request.name), events)
		edits = [r for r in rows if r["event"] == "CIA edit" and r["student"] == self.s22.name]
		changes = [(r["detail"], float(r["old_value"]), float(r["new_value"])) for r in edits]
		self.assertIn(("Assignment 1 A marks", 32, 20), changes)
		self.assertIn(("cia", 33, 30), changes)
		self.assertTrue(all(r["user"] for r in rows))
		self.assertEqual(audit_report({"company": "Some Other College"})[1], [])

	def test_a_passed_deadline_cannot_be_moved_to_reopen(self):  # fix 1
		schedule, _sheet = self.locked_sheet()
		frappe.set_user(COE_USER)
		schedule = frappe.get_doc("CIA Schedule", schedule.name)
		schedule.entry_deadline = add_days(now_datetime(), 3)
		with self.assertRaises(frappe.ValidationError):
			schedule.save()
		self.assertEqual(cia.lock_state(schedule.name), cia.LOCKED)

	def test_deadline_moves_before_the_lock_are_audited(self):  # fix 1
		schedule = self.schedule(self.offerings22["EXM TH"], THEORY_PATTERN)
		old = schedule.entry_deadline
		frappe.set_user(COE_USER)
		schedule.reload()
		schedule.entry_deadline = add_days(now_datetime(), 4)
		schedule.save(ignore_version=False)  # tests skip versions by default
		rows = audit_report({"company": COLLEGE, "course_offering": self.offerings22["EXM TH"]})[1]
		moves = [r for r in rows if r["event"] == "Deadline changed"]
		self.assertEqual([(r["document"], r["user"]) for r in moves], [(schedule.name, COE_USER)])
		# the Version keeps whole seconds
		self.assertEqual(
			frappe.utils.get_datetime(moves[0]["old_value"]),
			frappe.utils.get_datetime(old).replace(microsecond=0),
		)

	def test_no_unlock_without_a_completed_approval(self):  # fix 2
		schedule, _sheet = self.locked_sheet()
		frappe.db.delete(
			"Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.unlock_policies()]}
		)
		frappe.db.delete(
			"Approval Policy", {"document_type": "CIA Unlock Request"}
		)  # no policy: the engine would submit directly
		frappe.set_user(FACULTY)
		request = frappe.get_doc(
			{"doctype": "CIA Unlock Request", "cia_schedule": schedule.name, "reason": "x",
			"unlock_until": add_to_date(now_datetime(), hours=2)}
		).insert()  # fmt: skip
		with self.assertRaises(frappe.ValidationError):
			request_approval("CIA Unlock Request", request.name)
		frappe.set_user(COE_USER)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("CIA Unlock Request", request.name).submit()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CIA Unlock Request", request.name, "docstatus"), 0)
		self.assertEqual(cia.lock_state(schedule.name), cia.LOCKED)

	def test_question_tags_are_frozen_by_the_lock(self):  # minor: CO / Bloom / max are part of the snapshot
		self.locked_sheet()
		sheet = self.sheet(self.offerings22["EXM TH"])
		sheet.cia_marks[0].course_outcome = "CO6"
		with self.assertRaises(frappe.ValidationError):
			sheet.save()

	def test_lock_job_picks_due_schedules_once(self):  # fix 3
		due = self.schedule(self.offerings22["EXM TH"], THEORY_PATTERN)
		self.enter(self.offerings22["EXM TH"], THEORY_PATTERN, {self.s22.name: THEORY_163})
		later = self.schedule(self.offerings22["EXM LB"], LAB_PATTERN)
		self.pass_deadline(due)
		with (
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
		):  # the job commits per schedule
			cia.lock_due_schedules()
			stamped = frappe.db.get_value("CIA Schedule", due.name, "locked_on")
			sheet_modified = frappe.db.get_value("Mark Sheet Entry", {"cia_schedule": due.name}, "modified")
			self.assertTrue(stamped)
			self.assertFalse(frappe.db.get_value("CIA Schedule", later.name, "locked_on"))  # deadline ahead
			cia.lock_due_schedules()  # a second run finds nothing to do
			cia.lock_schedule(due.name)  # nor does a direct call on a stamped schedule
			cia.lock_schedule(later.name)  # or on one whose deadline is ahead
		self.assertEqual(frappe.db.get_value("CIA Schedule", due.name, "locked_on"), stamped)
		self.assertEqual(
			frappe.db.get_value("Mark Sheet Entry", {"cia_schedule": due.name}, "modified"), sheet_modified
		)
		self.assertFalse(frappe.db.get_value("CIA Schedule", later.name, "locked_on"))


class TestCIAPermissions(CIAFixture):
	def test_versions_are_kept(self):
		for doctype in ("Mark Sheet Entry", "CIA Schedule", "CIA Unlock Request", "CIA Component Template"):
			self.assertTrue(frappe.get_meta(doctype).track_changes, doctype)

	def test_faculty_edit_own_hod_and_coe_read(self):
		schedule = self.schedule(self.offerings22["EXM TH"], THEORY_PATTERN)
		sheet = self.sheet(self.offerings22["EXM TH"])
		for doc in (sheet, schedule):
			for user, read, write in (
				(FACULTY, True, True),
				(OTHER_FACULTY, False, False),
				(HOD_USER, True, False),
				(COE_USER, True, True),
			):
				self.assertEqual(
					frappe.has_permission(doc.doctype, "read", doc, user=user), read, (doc.doctype, user)
				)
				self.assertEqual(
					frappe.has_permission(doc.doctype, "write", doc, user=user), write, (doc.doctype, user)
				)
		frappe.set_user(HOD_USER)
		self.assertIn(sheet.name, frappe.get_list("Mark Sheet Entry", pluck="name"))
		self.assertEqual(frappe.get_list("CIA Schedule", pluck="name"), [schedule.name])
		frappe.set_user(OTHER_FACULTY)
		self.assertEqual(frappe.get_list("CIA Schedule", pluck="name"), [])

	def test_hod_does_not_read_another_departments_offering(self):
		make_program("CIA Other BE", COLLEGE)
		frappe.db.set_value(
			"Program", "CIA Other BE", "department", make_department("CIA Other Department", COLLEGE)
		)
		offering = self.offerings26["EXM LB"]
		frappe.db.set_value("Student Group", offering, "program", "CIA Other BE")
		sheet = self.sheet(offering)
		self.assertFalse(frappe.has_permission("Mark Sheet Entry", "read", sheet, user=HOD_USER))
		self.assertTrue(
			frappe.has_permission(
				"Mark Sheet Entry", "read", self.sheet(self.offerings26["EXM TH"]), user=HOD_USER
			)
		)
		frappe.set_user(HOD_USER)
		self.assertNotIn(sheet.name, frappe.get_list("Mark Sheet Entry", pluck="name"))

	def test_dean_academics_reads_schedules_but_the_coe_owns_deadlines(self):  # minor
		self.assertNotIn("Dean Academics", DEADLINE_ROLES)
		perms = frappe.get_all(
			"DocPerm", {"parent": "CIA Schedule", "role": "Dean Academics"}, ["read", "write", "create"]
		)
		self.assertEqual([(p.read, p.write, p.create) for p in perms], [(1, 0, 0)])

	def test_only_the_coe_sets_the_deadline(self):
		schedule = self.schedule(self.offerings22["EXM TH"], THEORY_PATTERN)
		frappe.set_user(FACULTY)
		schedule.questions[0].course_outcome = "CO2"  # the pattern is the faculty's
		schedule.save()
		schedule.entry_deadline = add_days(now_datetime(), 5)
		with self.assertRaises(frappe.PermissionError):
			schedule.save()

	def test_status_report_by_offering(self):
		locked = self.schedule(self.offerings22["EXM TH"], THEORY_PATTERN)
		self.enter(self.offerings22["EXM TH"], THEORY_PATTERN, {
			self.s22.name: THEORY_163, self.s_ab.name: [30, 12, 28, 34, "AB", "AB"], self.s_sa.name: [30, 14.5, 28, 40, 20, 30],
		})  # fmt: skip
		self.pass_deadline(locked)
		self.schedule(self.offerings22["EXM LB"], LAB_PATTERN)
		frappe.set_user(COE_USER)
		rows = {
			r["course_offering"]: r
			for r in status_report({"company": COLLEGE, "academic_term": self.term})[1]
		}
		theory, lab = rows[self.offerings22["EXM TH"]], rows[self.offerings22["EXM LB"]]
		self.assertEqual(
			(theory["status"], theory["students"], theory["absent_students"], theory["cia_max"]),
			("Locked", 3, 1, 40),
		)
		self.assertEqual(theory["average_cia"], 29)  # (33 + 21 + 33) / 3
		self.assertEqual((lab["status"], lab["cia_max"]), ("Open", 60))
		frappe.set_user(OTHER_FACULTY)
		self.assertEqual(status_report({"company": COLLEGE})[1], [])
