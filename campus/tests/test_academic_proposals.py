"""P2-T03 (M02-02, M02-04) tests: pick_curriculum (unit), and Academic Proposal behaviour (integration): AC1 a
proposal cannot move to the next body without a resolution of a quorate meeting of the stage's body that references
it, AC2 final approval makes curriculum v2 Effective for the listed batches only (the 2022 batch still resolves to v1),
AC3 the comment trail and versions are readable by IQAC; plus the Proposal Tracker and the AQAR 1.1.2 / 1.2.1 data points."""

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import add_days, getdate, today

from campus.academic_governance import api as governance
from campus.academic_governance import proposals, setup
from campus.academic_governance.report.proposal_tracker import proposal_tracker
from campus.academic_governance.seed import seed_body_types, seed_proposal_types
from campus.curriculum.doctype.curriculum.curriculum import create_new_version
from campus.curriculum.effective import effective_curriculum, pick_curriculum
from campus.iqac.registry import data_point
from campus.tests.factories import make_company
from campus.tests.test_regulation import enroll, make_program, make_regulation, make_student, make_year, year_name
from campus.tests.utils import CampusTestCase

COLLEGE = "Proposal Test College"
ABBR = "ACPR"
PROGRAM = "Proposal Test BE"
DEPARTMENT = "Proposal CSE"
OTHER_DEPARTMENT = "Proposal Mech"
IQAC_USER = "proposal-iqac@example.com"
ROUTE = ["Board of Studies", "Academic Council", "Governing Body"]


def candidate(name, version, *batches):
	return frappe._dict(name=name, version=version, batches=set(batches))


class TestPickCurriculum(UnitTestCase):
	def test_a_curriculum_listing_the_batch_wins_over_the_default(self):
		v1, v2 = candidate("v1", 1), candidate("v2", 2, "2026")
		self.assertEqual(pick_curriculum([v1, v2], "2026"), "v2")

	def test_a_batch_it_does_not_list_gets_the_default(self):
		v1, v2 = candidate("v1", 1), candidate("v2", 2, "2026")
		self.assertEqual(pick_curriculum([v1, v2], "2022"), "v1")

	def test_no_batch_gets_the_default(self):
		self.assertEqual(pick_curriculum([candidate("v1", 1), candidate("v2", 2, "2026")], None), "v1")

	def test_the_highest_version_wins_among_equals(self):
		self.assertEqual(pick_curriculum([candidate("v1", 1), candidate("v3", 3), candidate("v2", 2)], "2022"), "v3")
		self.assertEqual(pick_curriculum([candidate("v2", 2, "2026"), candidate("v3", 3, "2026")], "2026"), "v3")

	def test_nothing_applies_when_every_curriculum_is_batch_limited_elsewhere(self):
		self.assertIsNone(pick_curriculum([candidate("v2", 2, "2026")], "2022"))
		self.assertIsNone(pick_curriculum([], "2022"))


class TestAcademicProposals(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, ABBR)
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("proposal_test")
		self.addCleanup(frappe.db.rollback, save_point="proposal_test")
		self.addCleanup(frappe.set_user, "Administrator")
		seed_body_types()
		seed_proposal_types()
		for year in ("2022", "2023", "2026"):  # 2023: a batch of the version-precedence tests
			make_year(year)
		self.department = self.make_department(DEPARTMENT)
		self.other_department = self.make_department(OTHER_DEPARTMENT)
		self.employees = [self.employee() for _ in range(3)]
		self.nominees = [
			frappe.get_doc({"doctype": "External Member", "member_name": f"Nominee {n}", "email": f"nominee{n}.{frappe.generate_hash(length=5)}@example.com"}).insert().name
			for n in range(3)
		]  # fmt: skip
		self.bodies = {
			"Board of Studies": self.make_body("Test BoS", "Board of Studies", self.department),
			"Academic Council": self.make_body("Test AC", "Academic Council"),
			"Governing Body": self.make_body("Test GB", "Governing Body"),
		}
		self.setup_curriculum()

	# fixtures
	def make_department(self, name):
		full = f"{name} - {ABBR}"
		if not frappe.db.exists("Department", full):
			frappe.get_doc({"doctype": "Department", "department_name": name, "company": COLLEGE}).insert()
		return full

	def employee(self):
		return frappe.get_doc(
			{
				"doctype": "Employee", "first_name": "Prop", "last_name": frappe.generate_hash(length=6), "gender": "Male",
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": COLLEGE,
				"personal_email": f"{frappe.generate_hash(length=8)}@example.com",
			}
		).insert().name  # fmt: skip

	def make_body(self, name, body_type, department=None):
		start = add_days(today(), -500)
		members = [{"category": "Internal", "employee": e, "from_date": start} for e in self.employees]
		for nominee in self.nominees if body_type == "Academic Council" else self.nominees[:1]:
			members.append({"category": "University Nominee", "external_member": nominee, "from_date": start})
		return frappe.get_doc(
			{"doctype": "Body", "body_name": name, "company": COLLEGE, "body_type": body_type, "department": department, "members": members}
		).insert().name  # fmt: skip

	def make_course(self, name):
		if not frappe.db.exists("Course", name):
			frappe.get_doc({"doctype": "Course", "course_name": name, "oc_company": COLLEGE}).insert()
		return name

	def course_row(self, course, semester=1, credits=None, l=3, p=2):
		values = {"semester": semester, "course": course, "category": "PCC", "lecture_periods": l, "tutorial_periods": 0, "practical_periods": p}
		if credits is not None:
			values.update(credits_override=1, credits=credits)
		return values

	def setup_curriculum(self):
		program = make_program(PROGRAM, COLLEGE)
		frappe.db.set_value("Program", program, {"program_abbreviation": "PTB", "oc_total_semesters": 8})
		self.regulation = make_regulation("R2026", COLLEGE, [PROGRAM], "2026").name
		frappe.get_doc(
			{
				"doctype": "Curriculum Rule", "regulation": self.regulation, "lecture_credit_per_period": 1,
				"tutorial_credit_per_period": 1, "practical_credit_per_period": 0.5, "min_total_credits": 165, "max_total_credits": 170,
			}
		).insert()  # fmt: skip
		self.core, self.elective = self.make_course("PT Core"), self.make_course("PT New Elective")
		v1 = frappe.get_doc(
			{
				"doctype": "Curriculum", "program": PROGRAM, "regulation": self.regulation, "status": "Draft",
				"courses": [self.course_row(self.core), self.course_row("PT Bulk", 2, credits=163)],
			}
		)  # fmt: skip
		self.make_course("PT Bulk")
		v1.insert()
		for status in ("Approved", "Effective"):
			v1.status = status
			v1.save()
		self.v1 = v1.name
		self.v2 = create_new_version(self.v1)
		draft = frappe.get_doc("Curriculum", self.v2)
		draft.append("courses", {**self.course_row(self.elective, 3, credits=2, l=0, p=0), "is_elective": 1})
		draft.save()

	def make_proposal(self, type_name="New Elective", **values):
		fields = {
			"doctype": "Academic Proposal", "title": "Add PT New Elective", "proposal_type": type_name, "company": COLLEGE,
			"department": self.department, "regulation": self.regulation, "curriculum": self.v2,
			"batches": [{"academic_year": year_name("2026")}], "courses": [{"course": self.elective}],
		}  # fmt: skip
		return frappe.get_doc({**fields, **values}).insert()

	def meeting(self, stage_body, days_ago, proposal, decision="Approved", resolve=True, present=None):
		"""A quorate meeting of the body (Board of Studies etc.) with a resolution on `proposal`."""
		body = self.bodies[stage_body]
		meeting = frappe.get_doc({"doctype": "Body Meeting", "body": body, "meeting_date": add_days(today(), -days_ago), "venue": "Hall"}).insert()
		present = [self.employees[0], self.nominees[0]] if present is None else present
		for row in meeting.attendance:
			row.present = int((row.employee or row.external_member) in present)
		meeting.save()
		if resolve:
			meeting.append("resolutions", {"resolution_text": "Resolved", "decision": decision, "proposal": proposal.name})
			meeting.save()
		return meeting

	def submit(self, proposal):
		"""Submit to the route, then backdate the submission so the test's earlier meetings are not 'before' it."""
		proposal.submit_to_route()
		frappe.db.set_value("Academic Proposal", proposal.name, "submitted_on", add_days(today(), -30))
		proposal.reload()

	def resolve_through(self, proposal, last_stage_index):
		"""Hold quorate meetings and advance the proposal through the stages up to and including `last_stage_index`."""
		self.submit(proposal)
		for index in range(last_stage_index + 1):
			self.meeting(ROUTE[index], 10 - index, proposal)
			proposal.reload()
			proposal.advance_stage()
		proposal.reload()
		return proposal

	# types
	def test_the_five_types_are_seeded_with_the_bos_ac_gb_route_and_idempotently(self):
		seed_proposal_types()
		names = set(frappe.get_all("Proposal Type", pluck="name"))
		self.assertTrue({"New Course", "Syllabus Revision", "New Elective", "Regulation Change", "New Programme"} <= names)
		for name in ("New Elective", "Regulation Change"):
			self.assertEqual([r.body_type for r in frappe.get_doc("Proposal Type", name).route], ROUTE)

	def test_a_type_needs_a_route_of_distinct_bodies(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Proposal Type", "type_name": "No Route Type"}).insert()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Proposal Type", "type_name": "Dup Route Type", "route": [{"body_type": "Academic Council"}, {"body_type": "Academic Council"}]}).insert()

	# the full route (AC1, AC2)
	def test_the_full_route_through_bos_ac_and_gb_makes_curriculum_v2_effective_for_2026(self):
		proposal = self.make_proposal()
		self.assertEqual((proposal.status, proposal.current_stage), ("Draft", 0))
		self.submit(proposal)
		self.assertEqual((proposal.status, proposal.current_stage, proposal.current_body_type), ("In Route", 1, "Board of Studies"))

		bos = self.meeting("Board of Studies", 10, proposal)
		proposal.reload()
		proposal.advance_stage()
		proposal.reload()
		self.assertEqual((proposal.status, proposal.current_stage, proposal.current_body_type), ("In Route", 2, "Academic Council"))
		self.assertEqual(proposal.stage_resolutions[0].resolution_no, bos.resolutions[0].resolution_no)

		self.meeting("Academic Council", 9, proposal)
		proposal.reload()
		proposal.advance_stage()
		gb = self.meeting("Governing Body", 8, proposal)
		proposal.reload()
		proposal.advance_stage()
		proposal.reload()

		resolution_no = gb.resolutions[0].resolution_no
		self.assertEqual((proposal.status, proposal.approving_resolution), ("Approved", resolution_no))
		self.assertEqual(proposal.approved_on, getdate(gb.meeting_date))
		self.assertEqual([r.body_type for r in proposal.stage_resolutions], ROUTE)
		v2 = frappe.get_doc("Curriculum", self.v2)
		self.assertEqual((v2.status, v2.approving_resolution), ("Effective", resolution_no))
		self.assertEqual([r.academic_year for r in v2.applicable_batches], [year_name("2026")])
		self.assertEqual(frappe.db.get_value("Curriculum", self.v1, "status"), "Effective")  # v1 still serves the other batches

	def test_the_effective_version_is_resolved_per_batch(self):
		self.resolve_through(self.make_proposal(), 2)
		self.assertEqual(effective_curriculum(PROGRAM, self.regulation, year_name("2026")), self.v2)
		self.assertEqual(effective_curriculum(PROGRAM, self.regulation, year_name("2022")), self.v1)
		self.assertEqual(effective_curriculum(PROGRAM, self.regulation, None), self.v1)

	def test_a_curriculum_proposal_must_list_its_batches(self):
		proposal = self.make_proposal()
		proposal.batches = []
		proposal.save()
		with self.assertRaises(frappe.ValidationError):
			self.submit(proposal)  # a curriculum proposal must say which batches it is effective for

	def test_the_registration_resolver_is_the_same_function(self):
		from campus.curriculum import api as curriculum_api

		self.assertIs(curriculum_api.effective_curriculum, effective_curriculum)

	# blocks (AC1)
	def test_it_cannot_move_to_the_next_body_without_a_resolution(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		with self.assertRaisesRegex(frappe.ValidationError, "Board of Studies"):
			proposal.advance_stage()
		proposal.reload()
		self.assertEqual((proposal.status, proposal.current_stage), ("In Route", 1))

	def test_a_resolution_on_another_proposal_does_not_count(self):
		proposal, other = self.make_proposal(), self.make_proposal(title="Other")
		self.submit(proposal)
		self.meeting("Board of Studies", 5, other)
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()

	def test_a_resolution_of_the_wrong_body_does_not_count(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		self.meeting("Academic Council", 5, proposal)  # the proposal is still at the Board of Studies
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()

	def test_a_board_of_studies_of_another_department_does_not_count(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		frappe.db.set_value("Body", self.bodies["Board of Studies"], "department", self.other_department)
		self.meeting("Board of Studies", 5, proposal)
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()

	def test_a_deferred_resolution_does_not_move_the_proposal(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		self.meeting("Board of Studies", 5, proposal, decision="Deferred")
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()

	def test_a_meeting_without_quorum_cannot_carry_the_resolution(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		with self.assertRaisesRegex(frappe.ValidationError, "(?i)quorum"):
			self.meeting("Governing Body", 5, proposal, present=[self.employees[0]])  # the university nominee is mandatory
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()

	def test_a_cancelled_meeting_resolution_does_not_count(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		meeting = self.meeting("Board of Studies", 5, proposal)
		meeting.status = "Cancelled"
		meeting.save()
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()

	def test_a_resolution_cannot_predate_the_previous_stage(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		self.meeting("Board of Studies", 5, proposal)
		proposal.reload()
		proposal.advance_stage()
		self.meeting("Academic Council", 9, proposal)  # held before the Board of Studies resolved
		proposal.reload()
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()

	def test_a_rejection_ends_the_route_without_touching_the_curriculum(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		self.meeting("Board of Studies", 5, proposal, decision="Rejected")
		proposal.reload()
		proposal.advance_stage()
		proposal.reload()
		self.assertEqual(proposal.status, "Rejected")
		self.assertEqual(frappe.db.get_value("Curriculum", self.v2, "status"), "Draft")
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()

	def test_a_failed_final_approval_leaves_nothing_half_done(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		frappe.db.set_value("Curriculum Rule", {"regulation": self.regulation}, "max_total_credits", 100)  # v2 now breaks the credit range
		for index in range(3):
			self.meeting(ROUTE[index], 10 - index, proposal)
			proposal.reload()
			if index < 2:
				proposal.advance_stage()
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()
		proposal.reload()
		self.assertEqual((proposal.status, proposal.current_stage, len(proposal.stage_resolutions)), ("In Route", 3, 2))
		self.assertEqual(frappe.db.get_value("Curriculum", self.v2, "status"), "Draft")

	# regulation change
	def test_a_regulation_change_makes_the_amended_regulation_effective(self):
		from campus.campus_platform.doctype.regulation.regulation import amend_as_new_version

		amended = amend_as_new_version(self.regulation)
		proposal = self.make_proposal("Regulation Change", title="Amend R2026", regulation=amended, curriculum=None, batches=[], courses=[])
		self.resolve_through(proposal, 2)
		self.assertEqual(proposal.status, "Approved")
		regulation = frappe.get_doc("Regulation", amended)
		self.assertEqual((regulation.status, regulation.approving_resolution), ("Effective", proposal.approving_resolution))
		self.assertEqual(frappe.db.get_value("Regulation", self.regulation, "status"), "Retired")

	def test_a_regulation_change_needs_an_unapproved_regulation(self):
		proposal = self.make_proposal("Regulation Change", curriculum=None, batches=[], courses=[])
		with self.assertRaises(frappe.ValidationError):
			self.submit(proposal)  # R2026 is already Effective

	# integrity
	def test_a_curriculum_type_needs_a_curriculum_of_the_regulation(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_proposal(curriculum=None)
		other = make_regulation("R2027", COLLEGE, [PROGRAM], "2026", status="Draft").name
		with self.assertRaises(frappe.ValidationError):
			self.make_proposal(regulation=other)

	def test_a_locked_curriculum_cannot_be_proposed(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_proposal(curriculum=self.v1)

	def test_the_subject_cannot_change_once_the_route_has_started(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		proposal.reload()
		proposal.curriculum = self.v1
		with self.assertRaises(frappe.ValidationError):
			proposal.save()

	def test_stage_and_status_are_server_owned(self):
		proposal = self.make_proposal()
		proposal.status, proposal.current_stage = "Approved", 3
		proposal.append("stage_resolutions", {"stage": 1, "body_type": "Board of Studies", "resolution_no": "FAKE/2026/001", "decision": "Approved"})
		proposal.save()
		proposal.reload()
		self.assertEqual((proposal.status, proposal.current_stage, len(proposal.stage_resolutions)), ("Draft", 0, 0))

	def test_an_approved_proposal_is_read_only(self):
		proposal = self.resolve_through(self.make_proposal(), 2)
		proposal.title = "Changed afterwards"
		with self.assertRaises(frappe.ValidationError):
			proposal.save()
		with self.assertRaises(frappe.ValidationError):
			proposal.delete()

	def test_the_meeting_link_points_at_academic_proposal(self):
		self.assertEqual(frappe.get_meta("Meeting Resolution").get_field("proposal").fieldtype, "Link")
		self.assertEqual(frappe.get_meta("Meeting Resolution").get_field("proposal").options, "Academic Proposal")
		self.assertEqual(frappe.get_meta("Meeting Agenda Item").get_field("proposal").options, "Academic Proposal")
		proposal = self.make_proposal()
		meeting = self.meeting("Board of Studies", 5, proposal)
		self.assertEqual(meeting.resolutions[0].proposal, proposal.name)
		meeting.append("resolutions", {"resolution_text": "x", "decision": "Approved", "proposal": "PROP-NOPE"})
		with self.assertRaises(frappe.LinkValidationError):
			meeting.save()

	def test_stale_proposal_references_from_the_old_data_stub_are_cleared(self):
		proposal = self.make_proposal()
		meeting = self.meeting("Board of Studies", 5, proposal)
		frappe.db.set_value("Meeting Resolution", {"parent": meeting.name}, "proposal", "PROP-STUB-1")
		setup.clear_stale_proposal_references()
		self.assertFalse(frappe.db.get_value("Meeting Resolution", {"parent": meeting.name}, "proposal"))
		frappe.db.set_value("Meeting Resolution", {"parent": meeting.name}, "proposal", proposal.name)
		setup.clear_stale_proposal_references()
		self.assertEqual(frappe.db.get_value("Meeting Resolution", {"parent": meeting.name}, "proposal"), proposal.name)

	# audit trail (AC3)
	def test_iqac_sees_the_comment_trail_and_the_versions(self):
		if not frappe.db.exists("User", IQAC_USER):
			frappe.get_doc({"doctype": "User", "email": IQAC_USER, "first_name": "Iqac", "send_welcome_email": 0, "roles": [{"role": "IQAC Coordinator"}]}).insert()
		proposal = self.make_proposal()
		proposal.add_comment("Comment", "BoS wants a lab component")
		proposal.title = "Add PT New Elective (revised)"
		proposal.append("attachments", {"title": "Draft syllabus", "file": "/files/draft-syllabus.pdf"})
		proposal.save(ignore_version=False)  # tests skip versions by default
		frappe.set_user(IQAC_USER)
		trail = proposals.audit_trail(proposal.name)
		self.assertEqual([c["content"] for c in trail["comments"]], ["BoS wants a lab component"])
		changed = {row[0] for version in trail["versions"] for row in version["changed"]}
		self.assertIn("title", changed)
		self.assertTrue(any(version["data"]["added"] for version in trail["versions"]))  # the attachment row

	def test_a_user_who_cannot_read_the_proposal_gets_no_trail(self):
		proposal = self.make_proposal()
		user = "proposal-nobody@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "Nobody", "send_welcome_email": 0, "roles": [{"role": "Employee"}]}).insert()
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			proposals.audit_trail(proposal.name)

	# reports
	def test_the_tracker_lists_proposals_with_their_stage(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		done = self.resolve_through(self.make_proposal(title="Finished"), 0)
		columns, rows = proposal_tracker.execute({"company": COLLEGE})
		by_name = {r["proposal"]: r for r in rows}
		self.assertEqual(by_name[proposal.name]["stage"], "1/3 Board of Studies")
		self.assertEqual(by_name[done.name]["stage"], "2/3 Academic Council")
		self.assertEqual(by_name[proposal.name]["status"], "In Route")
		self.assertTrue(columns)
		_, only_approved = proposal_tracker.execute({"company": COLLEGE, "status": "Approved"})
		self.assertEqual(only_approved, [])
		_, other_department = proposal_tracker.execute({"company": COLLEGE, "department": self.other_department})
		self.assertEqual(other_department, [])
		self.assertEqual(proposal_tracker.execute({}), (proposal_tracker.columns(), []))

	# AQAR data points
	def test_aqar_data_points_count_programmes_revised_and_courses_introduced(self):
		revision = self.make_proposal("Syllabus Revision", title="Revise core", courses=[{"course": self.core}])
		new = self.make_proposal("New Course", title="New course", curriculum=None, batches=[], courses=[{"course": self.elective}, {"course": "PT Bulk"}])
		pending = self.make_proposal("New Course", title="Pending", curriculum=None, batches=[], courses=[{"course": "PT Bulk"}])
		self.resolve_through(revision, 2)
		self.resolve_through(new, 2)
		pending.submit_to_route()
		year = frappe.db.get_value("Academic Year", year_name("2026"), ["year_start_date", "year_end_date"], as_dict=True)
		frappe.db.set_value("Academic Proposal", {"name": ["in", [revision.name, new.name]]}, "approved_on", year.year_start_date)

		revised = data_point("syllabus_revised_programmes", COLLEGE, year_name("2026"))
		self.assertEqual((revised["value"], revised["records"]), (1, [{"doctype": "Program", "name": PROGRAM}]))
		introduced = data_point("new_courses_introduced", COLLEGE, year_name("2026"))
		self.assertEqual(introduced["value"], 2)
		self.assertEqual(data_point("new_courses_introduced", COLLEGE, year_name("2022"))["value"], 0)  # approved in another year
		self.assertEqual(data_point("syllabus_revised_programmes", COLLEGE, year_name("2026"), self.other_department)["value"], 0)
		self.assertEqual(data_point("syllabus_revised_programmes", COLLEGE, year_name("2026"), self.department)["value"], 1)
		self.assertEqual(governance.proposal_courses("Other College", year_name("2026"), "New Course"), [])

	# fix round 1
	def test_a_default_version_supersedes_only_default_versions(self):
		self.resolve_through(self.make_proposal(), 2)  # v2 Effective for 2026 only; v1 is the default
		v3 = frappe.get_doc("Curriculum", create_new_version(self.v2))
		for status in ("Approved", "Effective"):
			v3.status = status
			v3.save()
		self.assertEqual(frappe.db.get_value("Curriculum", self.v1, "status"), "Superseded")
		self.assertEqual(frappe.db.get_value("Curriculum", self.v2, "status"), "Effective")
		self.assertEqual(effective_curriculum(PROGRAM, self.regulation, year_name("2026")), self.v2)
		self.assertEqual(effective_curriculum(PROGRAM, self.regulation, year_name("2022")), v3.name)

	def make_effective(self, name, *years):
		doc = frappe.get_doc("Curriculum", name)
		doc.set("applicable_batches", [{"academic_year": year_name(y)} for y in years])
		for status in ("Approved", "Effective"):
			doc.status = status
			doc.save()
		return doc

	def test_an_older_version_can_become_effective_for_a_batch_the_newer_one_does_not_cover(self):
		v3 = create_new_version(self.v1)
		self.make_effective(v3, "2023")
		self.make_effective(self.v2, "2026")  # older than v3, but no shared batch
		self.assertEqual(frappe.db.get_value("Curriculum", self.v2, "status"), "Effective")
		self.assertEqual(frappe.db.get_value("Curriculum", self.v1, "status"), "Effective")

	def test_an_older_version_cannot_become_effective_over_a_newer_one_for_the_same_batch(self):
		v3 = create_new_version(self.v1)
		self.make_effective(v3, "2026")
		with self.assertRaisesRegex(frappe.ValidationError, "newer version"):
			self.make_effective(self.v2, "2026", "2023")

	def test_stage_one_needs_a_resolution_not_before_the_submission(self):
		proposal = self.make_proposal()
		proposal.submit_to_route()
		self.assertEqual(getdate(proposal.submitted_on), getdate(today()))
		self.meeting("Board of Studies", 5, proposal)  # held before the proposal was submitted
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()
		self.meeting("Board of Studies", 0, proposal)
		proposal.reload()
		proposal.advance_stage()
		self.assertEqual(proposal.current_stage, 2)

	def test_submission_date_is_server_owned(self):
		proposal = self.make_proposal()
		proposal.submitted_on = today()
		proposal.save()
		proposal.reload()
		self.assertFalse(proposal.submitted_on)

	def test_a_numbered_resolution_cannot_be_pointed_at_another_proposal(self):
		proposal, other = self.make_proposal(), self.make_proposal(title="Other")
		meeting = self.meeting("Board of Studies", 5, proposal)
		meeting.resolutions[0].proposal = other.name
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be edited"):
			meeting.save()

	def test_a_board_of_studies_needs_a_department(self):
		with self.assertRaisesRegex(frappe.ValidationError, "(?i)department"):
			self.make_body("Rootless BoS", "Board of Studies")

	def test_a_board_of_studies_of_no_department_is_never_matched_even_if_present_in_old_data(self):
		proposal = self.make_proposal()
		self.submit(proposal)
		frappe.db.set_value("Body", self.bodies["Board of Studies"], "department", None)
		self.meeting("Board of Studies", 5, proposal)
		with self.assertRaises(frappe.ValidationError):
			proposal.advance_stage()

	def test_course_registration_follows_the_batch_curriculum(self):
		self.resolve_through(self.make_proposal(), 2)
		for batch, expected in (("2022", self.v1), ("2026", self.v2)):
			student = make_student(f"Prop{batch}", COLLEGE, batch)
			enroll(student, PROGRAM, batch)
			frappe.db.set_value("Student", student.name, "oc_regulation", self.regulation)
			registration = frappe.new_doc("Course Registration")
			registration.student = student.name
			registration.set_context()
			self.assertEqual(registration.curriculum, expected, batch)
