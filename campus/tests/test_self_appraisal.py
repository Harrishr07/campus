"""P2-T09 (M07-04 / M07-05) integration tests: Faculty Achievement rules, the API Score Rule version in force, the
self-appraisal that creates or updates an HRMS Appraisal with KRA scores, HOD review through the approval engine
(no self-approval, locked afterwards), the FDP (NAAC 6.3.4) and conference support (6.3.2) reports and data points,
and the escaped Faculty CV.

Fixture (period 2026-27, rule rows as test_api_scoring.py): faculty_1 attended three FDPs (one Absent, one a
non-FDP event and one in 2025-26 are ignored), has a verified Conference (3) and Award (5), and an unverified Conference
(ignored); weekly workload 12 hours (patched in). Hand figures: Professional Development 8 (FDP 12 capped at 8) + 3 + 5
= 16 of 20 -> 80% -> 4.0 stars; Teaching 12 of 20 -> 60% -> 3.0 stars; total score 3.0 * 0.6 + 4.0 * 0.4 = 3.4.
"""

from unittest import mock

import frappe
from frappe.utils import add_days, today

from campus.campus_platform.approval_engine import latest_request
from campus.campus_platform.approvals import approve
from campus.faculty import api, self_appraisal
from campus.faculty.report.conference_financial_support import conference_financial_support
from campus.faculty.report.fdp_participation import fdp_participation
from campus.faculty.setup import seed_appraisal_review_policy
from campus.iqac import registry
from campus.tests import demo
from campus.tests.utils import CampusTestCase

YEAR = "2026-27"
TEACHING, PD = "SA Test Teaching", "SA Test Professional Development"
FILTERS = {"company": demo.ENGINEERING, "academic_year": YEAR}
HOURS = "campus.faculty.workload.submitted_hours"


class SelfAppraisalFixture(CampusTestCase):
	demo_scale = "small"

	def setUp(self):
		super().setUp()
		frappe.db.savepoint("sa_test")
		self.faculty, self.hod = demo.employee_of("faculty_1"), demo.employee_of("hod_cse")
		for username in ("faculty_1", "hod_cse"):
			frappe.get_doc("User", demo.email(username)).add_roles("Employee")
		self.make_rule()
		self.cycle = self.make_cycle()
		seed_appraisal_review_policy()
		self.hours = mock.patch(HOURS, return_value={self.faculty: 12, self.hod: 6})
		self.hours.start()

	def tearDown(self):
		self.hours.stop()
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="sa_test")
		super().tearDown()

	def make_rule(self, effective_from="2026-01-01", **extra):
		for title in (TEACHING, PD):
			demo.get_or_insert("KRA", {"title": title}, {})
		return frappe.get_doc(
			{
				"doctype": "API Score Rule", "rule_name": "SA Test Rule", "company": demo.ENGINEERING, "effective_from": effective_from,
				"rows": [
					{"activity": "FDP Attended", "points": 4, "annual_cap": 8, "kra": PD},
					{"activity": "Conference", "points": 3, "annual_cap": 6, "kra": PD},
					{"activity": "Award", "points": 5, "annual_cap": 0, "kra": PD},
					{"activity": "Teaching Workload", "points": 1, "annual_cap": 20, "kra": TEACHING},
				],
				"kras": [{"kra": TEACHING, "weightage": 60, "target_points": 20}, {"kra": PD, "weightage": 40, "target_points": 20}],
				**extra,
			}
		).insert(ignore_permissions=True)  # fmt: skip

	def make_cycle(self):
		return frappe.get_doc(
			{
				"doctype": "Appraisal Cycle", "cycle_name": "SA Test Cycle 2026-27", "company": demo.ENGINEERING,
				"start_date": "2026-06-01", "end_date": "2027-05-31",
			}
		).insert(ignore_permissions=True).name  # fmt: skip

	def fdp(self, title, start, attendees, is_fdp=1):
		"""A submitted Training Event; `attendees` = [(employee, attendance)]."""
		event = frappe.get_doc(
			{
				"doctype": "Training Event", "event_name": title, "event_status": "Completed", "type": "Workshop", "location": "Seminar Hall",
				"start_time": f"{start} 10:00:00", "end_time": f"{start} 16:00:00", "introduction": "FDP", "company": demo.ENGINEERING,
				"oc_is_fdp": is_fdp, "employees": [{"employee": e, "attendance": a, "status": "Open"} for e, a in attendees],
			}
		).insert(ignore_permissions=True)  # fmt: skip
		event.submit()
		return event

	def achievement(self, employee, kind="Conference", title="Paper presentation", on="2026-08-10", amount=0, verified=1, evidence="/private/files/evidence.pdf", **extra):
		doc = frappe.get_doc(
			{
				"doctype": "Faculty Achievement", "employee": employee, "achievement_type": kind, "title": title,
				"achievement_date": on, "financial_support_amount": amount, "evidence": evidence, **extra,
			}
		).insert(ignore_permissions=True)  # fmt: skip
		if verified:
			doc.verified = 1
			doc.save(ignore_permissions=True)
		return doc

	def activity(self):
		for i, day in enumerate(("2026-07-10", "2026-09-12", "2026-12-05")):
			self.fdp(f"SA FDP {i}", day, [(self.faculty, "Present")])
		self.fdp("SA FDP absent", "2026-10-01", [(self.faculty, "Absent")])
		self.fdp("SA seminar", "2026-10-02", [(self.faculty, "Present")], is_fdp=0)
		self.fdp("SA FDP last year", "2025-12-05", [(self.faculty, "Present")])
		self.achievement(self.faculty, "Conference")
		self.achievement(self.faculty, "Award", "Best teacher", "2026-09-05")
		self.achievement(self.faculty, "Conference", "Unverified", verified=0)
		self.achievement(self.faculty, "Conference", "Last year", "2025-08-10")

	def appraisal(self, employee=None):
		return self_appraisal.create_or_update(employee or self.faculty, self.cycle)

	def goals(self, appraisal):
		return {g.kra: (g.per_weightage, g.score) for g in appraisal.goals}

	def request_as(self, user, appraisal):
		frappe.set_user(user)
		try:
			return self_appraisal.request_review(appraisal.name)
		finally:
			frappe.set_user("Administrator")

	def act_as(self, user, review):
		frappe.set_user(user)
		try:
			return approve(latest_request(frappe.get_doc("Appraisal Review", review)).name)
		finally:
			frappe.set_user("Administrator")


class TestAchievementAndRule(SelfAppraisalFixture):
	def test_evidence_must_be_a_private_file(self):
		with self.assertRaises(frappe.ValidationError):
			self.achievement(self.faculty, evidence="/files/certificate.pdf", verified=0)
		doc = self.achievement(self.faculty, evidence="/private/files/certificate.pdf", verified=0)
		self.assertEqual(doc.evidence, "/private/files/certificate.pdf")

	def test_verification_needs_evidence(self):
		with self.assertRaises(frappe.ValidationError):
			self.achievement(self.faculty, evidence="", verified=1)

	def test_only_hr_can_verify(self):
		frappe.set_user(demo.email("faculty_1"))
		try:
			doc = frappe.get_doc(
				{"doctype": "Faculty Achievement", "employee": self.faculty, "achievement_type": "Award", "title": "Mine",
				"achievement_date": today(), "evidence": "/private/files/a.pdf", "verified": 1}
			).insert()  # fmt: skip
			self.assertFalse(frappe.db.get_value("Faculty Achievement", doc.name, "verified"))  # the field is HR-only
			doc.verified = 1
			doc.save()
			self.assertFalse(frappe.db.get_value("Faculty Achievement", doc.name, "verified"))
		finally:
			frappe.set_user("Administrator")

	def test_faculty_files_only_for_themselves_and_amount_cannot_be_negative(self):
		frappe.set_user(demo.email("faculty_1"))
		try:
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc(
					{"doctype": "Faculty Achievement", "employee": self.hod, "achievement_type": "Award", "title": "x", "achievement_date": today()}
				).insert()
		finally:
			frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			self.achievement(self.faculty, amount=-1, verified=0)

	def test_training_attendance_is_not_a_faculty_achievement_type(self):
		options = frappe.get_meta("Faculty Achievement").get_field("achievement_type").options.split("\n")
		self.assertNotIn("FDP Attended", options)

	def test_rule_weightage_must_total_one_hundred(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_rule(effective_from="2026-02-01", kras=[{"kra": TEACHING, "weightage": 60, "target_points": 20}])

	def test_rule_rows_need_a_kra_of_the_rule(self):
		other = demo.get_or_insert("KRA", {"title": "SA Test Other"}, {})
		with self.assertRaises(frappe.ValidationError):
			self.make_rule(effective_from="2026-02-01", rows=[{"activity": "Award", "points": 1, "annual_cap": 0, "kra": other}])

	def test_rule_in_force_is_the_latest_version_effective_by_the_date(self):
		newer = self.make_rule(effective_from="2027-01-01")
		self.assertEqual(self_appraisal.rule_in_force(demo.ENGINEERING, "2026-12-31").effective_from.isoformat(), "2026-01-01")
		self.assertEqual(self_appraisal.rule_in_force(demo.ENGINEERING, "2027-05-31").name, newer.name)
		self.assertIsNone(self_appraisal.rule_in_force(demo.ENGINEERING, "2025-12-31"))


class TestSelfAppraisal(SelfAppraisalFixture):
	def test_kra_scores_follow_the_rule_caps(self):
		self.activity()
		appraisal = self.appraisal()
		self.assertEqual(self.goals(appraisal), {TEACHING: (60, 3.0), PD: (40, 4.0)})
		self.assertEqual(appraisal.total_score, 3.4)
		self.assertEqual(appraisal.docstatus, 0)
		self.assertEqual(appraisal.oc_api_total, 28)  # 12 + 16 points
		self.assertIn("FDP Attended", appraisal.oc_api_breakdown)
		self.assertIn("capped", appraisal.oc_api_breakdown)  # FDP 12 raw points, 8 counted

	def test_fdp_attendance_is_read_from_the_training_event_not_copied(self):
		self.activity()
		self.assertFalse(frappe.db.exists("Faculty Achievement", {"employee": self.faculty, "title": ["like", "SA FDP%"]}))
		breakdown = {r.activity: r for r in self_appraisal.compute(self.faculty, self.cycle).results}
		self.assertEqual(breakdown["FDP Attended"].quantity, 3)  # absent, non-FDP and last year's events are not counted

	def test_updating_keeps_one_appraisal_and_follows_new_achievements(self):
		self.activity()
		first = self.appraisal()
		self.achievement(self.faculty, "Award", "Second award", "2026-10-20")
		second = self.appraisal()
		self.assertEqual(second.name, first.name)
		self.assertEqual(frappe.db.count("Appraisal", {"employee": self.faculty, "appraisal_cycle": self.cycle}), 1)
		self.assertEqual(self.goals(second), {TEACHING: (60, 3.0), PD: (40, 5.0)})  # 16 + 5 = 21 of 20, limited to 100%
		self.assertEqual(second.total_score, 3.8)

	def test_goal_scores_cannot_be_edited_by_hand(self):
		self.activity()
		appraisal = self.appraisal()
		appraisal.goals[0].score = 5
		appraisal.save()
		self.assertEqual(self.goals(frappe.get_doc("Appraisal", appraisal.name)), {TEACHING: (60, 3.0), PD: (40, 4.0)})

	def test_no_rule_in_force_is_refused(self):
		frappe.db.delete("API Score Rule", {"company": demo.ENGINEERING})
		with self.assertRaises(frappe.ValidationError):
			self.appraisal()

	def test_only_the_appraisee_or_hr_can_create_the_self_appraisal(self):
		frappe.set_user(demo.email("faculty_1"))
		try:
			with self.assertRaises(frappe.PermissionError):
				self.appraisal(self.hod)
			self.assertEqual(self.appraisal().employee, self.faculty)
		finally:
			frappe.set_user("Administrator")


class TestHodReview(SelfAppraisalFixture):
	def setUp(self):
		super().setUp()
		self.activity()
		self.appraisal_doc = self.appraisal()

	def test_hrms_appraisal_cannot_be_submitted_without_the_hod_review(self):
		with self.assertRaises(frappe.ValidationError):
			self.appraisal_doc.submit()

	def test_hod_approval_submits_the_appraisal_and_locks_the_faculty_out(self):
		review = self.request_as(demo.email("faculty_1"), self.appraisal_doc)
		self.assertEqual(frappe.db.get_value("Appraisal", self.appraisal_doc.name, "docstatus"), 0)
		self.assertEqual(self.act_as(demo.email("hod_cse"), review), "Approved")
		appraisal = frappe.get_doc("Appraisal", self.appraisal_doc.name)
		self.assertEqual((appraisal.docstatus, appraisal.total_score), (1, 3.4))
		self.assertEqual(frappe.db.get_value("Appraisal Review", review, "docstatus"), 1)
		faculty = demo.email("faculty_1")
		self.assertFalse(frappe.has_permission("Appraisal", "write", appraisal, user=faculty))
		frappe.set_user(faculty)
		try:
			appraisal.reflections = "changed after approval"
			with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
				appraisal.save()
		finally:
			frappe.set_user("Administrator")

	def test_recompute_after_the_hod_submitted_is_refused(self):
		review = self.request_as(demo.email("faculty_1"), self.appraisal_doc)
		self.act_as(demo.email("hod_cse"), review)
		with self.assertRaises(frappe.ValidationError):
			self.appraisal()

	def test_scores_are_frozen_while_the_review_is_pending(self):
		self.request_as(demo.email("faculty_1"), self.appraisal_doc)
		self.achievement(self.faculty, "Award", "Late award", "2026-11-20")
		with self.assertRaises(frappe.ValidationError):
			self.appraisal()

	def test_the_requester_cannot_approve_their_own_review(self):
		review = self.request_as(demo.email("faculty_1"), self.appraisal_doc)
		with self.assertRaises(frappe.PermissionError):
			self.act_as(demo.email("faculty_1"), review)
		self.assertEqual(frappe.db.get_value("Appraisal", self.appraisal_doc.name, "docstatus"), 0)

	def test_an_hod_cannot_approve_their_own_appraisal(self):
		own = self.appraisal(self.hod)
		review = self_appraisal.request_review(own.name)  # raised by Administrator (HR), so only the HOD position could approve
		with self.assertRaises(frappe.ValidationError):
			self.act_as(demo.email("hod_cse"), review)
		self.assertEqual(frappe.db.get_value("Appraisal", own.name, "docstatus"), 0)

	def test_another_teacher_cannot_request_a_review(self):
		with self.assertRaises(frappe.PermissionError):
			self.request_as(demo.email("faculty_2"), self.appraisal_doc)

	def test_a_second_open_review_is_refused(self):
		self.request_as(demo.email("faculty_1"), self.appraisal_doc)
		with self.assertRaises(frappe.ValidationError):
			self_appraisal.request_review(self.appraisal_doc.name)


class TestReportsAndCv(SelfAppraisalFixture):
	def setUp(self):
		super().setUp()
		f2, f3 = demo.employee_of("faculty_2"), demo.employee_of("faculty_3")
		self.fdp("SA FDP one", "2026-07-10", [(self.faculty, "Present"), (f2, "Present"), (f3, "Absent")])
		self.fdp("SA FDP two", "2026-09-12", [(self.faculty, "Present")])
		self.fdp("SA FDP other year", "2027-06-20", [(f3, "Present")])
		self.fdp("SA seminar", "2026-10-02", [(f3, "Present")], is_fdp=0)
		self.achievement(self.faculty, "Conference", "ICML", amount=5000)
		self.achievement(self.faculty, "Membership", "IEEE", on="2026-11-01", amount=2000)
		self.achievement(f2, "Conference", "Unverified", amount=3000, verified=0)
		self.achievement(f2, "Award", "Teaching award", amount=1000)
		self.achievement(f3, "Conference", "Self funded", amount=0)
		self.achievement(f2, "Conference", "NeurIPS", on="2027-02-02", amount=4000)

	def test_fdp_participation_lists_attended_fdp_events_of_the_year(self):
		rows = fdp_participation.execute(FILTERS)[1]
		self.assertEqual(sorted((r["employee"], r["training_event"]) for r in rows), sorted([
			(self.faculty, "SA FDP one"), (self.faculty, "SA FDP two"), (demo.employee_of("faculty_2"), "SA FDP one"),
		]))  # fmt: skip

	def test_fdp_data_point_counts_distinct_teachers(self):
		point = registry.data_point("fdp_teachers", demo.ENGINEERING, YEAR)
		self.assertEqual(point["value"], 2)  # faculty_1 twice counts once
		self.assertEqual({r["name"] for r in point["records"]}, {self.faculty, demo.employee_of("faculty_2")})
		self.assertEqual(registry.data_point("fdp_teachers", demo.ENGINEERING, YEAR, "No Such Department")["value"], 0)

	def test_conference_support_lists_verified_supported_conferences_and_memberships(self):
		rows = conference_financial_support.execute(FILTERS)[1]
		self.assertEqual(sorted((r["employee"], r["title"], r["amount"]) for r in rows), sorted([
			(self.faculty, "ICML", 5000), (self.faculty, "IEEE", 2000), (demo.employee_of("faculty_2"), "NeurIPS", 4000),
		]))  # fmt: skip

	def test_support_data_point_counts_teachers_and_the_report_totals_the_amount(self):
		point = registry.data_point("teachers_financially_supported", demo.ENGINEERING, YEAR)
		self.assertEqual(point["value"], 2)
		self.assertEqual(sum(r["amount"] for r in conference_financial_support.execute(FILTERS)[1]), 11000)

	def test_reports_need_company_and_year(self):
		self.assertEqual(fdp_participation.execute({})[1], [])
		self.assertEqual(conference_financial_support.execute({"company": demo.ENGINEERING})[1], [])

	def test_faculty_cv_prints_escaped(self):
		hostile = self.achievement(self.faculty, "Award", "placeholder", amount=0)
		frappe.db.set_value("Faculty Achievement", hostile.name, "title", "<script>alert(1)</script>")  # as left by an import
		frappe.db.set_value("Employee", self.faculty, "oc_specialisation", "<img src=x onerror=alert(2)>")
		html = frappe.get_print("Employee", self.faculty, print_format="Faculty CV")
		self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
		self.assertNotIn("<script>alert(1)", html)
		self.assertNotIn("<img src=x", html)
		self.achievement(self.faculty, "Award", "Pending Verification Prize", verified=0)
		html = frappe.get_print("Employee", self.faculty, print_format="Faculty CV")
		self.assertIn("IEEE", html)
		self.assertNotIn("Pending Verification Prize", html)  # only verified achievements go on the CV
