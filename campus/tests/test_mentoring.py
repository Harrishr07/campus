"""L-09 (M05-13) Mentoring: Counselling Notes are read by the author, the student's current mentor, Student
Counsellors, the HOD of the student's department and the Principal; a confidential note only by its author and its
designated counsellor. Parent Interactions are for the mentor, the class advisor and office roles, never a guardian.
Follow-up reminders go once through the messaging bus without the note text; the faculty portal escapes output; the
activity report shows counts only.
"""

import io
import zipfile
from unittest import mock

import frappe
from frappe.core.doctype.file.utils import find_file_by_url
from frappe.desk import notifications
from frappe.desk.form import linked_with
from frappe.utils import add_days, set_request, today
from frappe.website.serve import get_response_without_exception_handling

from campus.campus_platform import restricted_records
from campus.faculty import portal_mentoring
from campus.student_services import mentoring
from campus.student_services.report.mentoring_activity import mentoring_activity
from campus.tests import demo
from campus.tests.factories import make_user
from campus.tests.utils import CampusTestCase

NOTE, INTERACTION = "Counselling Note", "Parent Interaction"
MENTOR_A, MENTOR_B = demo.email("faculty_1"), demo.email("faculty_2")
HOD, PRINCIPAL, GUARDIAN = demo.email("hod_cse"), demo.email("principal"), demo.email("guardian_1")
COUNSELLOR = "campus-l09-counsellor@example.com"
SECRET = "SECRET-NOTE-TEXT"


class MentoringFixture(CampusTestCase):
	demo_scale = "small"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.guardian = frappe.db.get_value("Guardian", {"user": GUARDIAN})
		cls.guarded = frappe.db.get_value("Student Guardian", {"guardian": cls.guardian, "parenttype": "Student"}, "parent")
		enrolled = frappe.get_all("Program Enrollment", {"program": "B.E. CSE", "docstatus": 1}, pluck="student", order_by="student")
		cls.a_student, cls.b_student, cls.c_student = [s for s in enrolled if s != cls.guarded][:3]
		cls.other_guardian = frappe.get_doc({"doctype": "Guardian", "guardian_name": "L09 Other Guardian"}).insert().name
		student = frappe.get_doc("Student", cls.a_student)
		student.append("guardians", {"guardian": cls.other_guardian, "guardian_name": "L09 Other Guardian", "relation": "Mother"})
		student.save()
		for student, mentor in ((cls.a_student, "faculty_1"), (cls.guarded, "faculty_1"), (cls.b_student, "faculty_2")):
			frappe.db.set_value("Student", student, "oc_mentor", demo.employee_of(mentor))
		for user in (MENTOR_A, MENTOR_B):
			frappe.get_doc("User", user).add_roles(mentoring.MENTOR_ROLE)
		make_user(COUNSELLOR, [demo.ENGINEERING])
		frappe.get_doc("User", COUNSELLOR).add_roles(mentoring.COUNSELLOR_ROLE)
		mentoring.seed_follow_up_template()

	def setUp(self):
		frappe.db.savepoint("mentoring_test")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="mentoring_test")

	def as_user(self, user, fn, *args, **kwargs):
		frappe.set_user(user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def add_note(self, user, student, **values):
		doc = {"doctype": NOTE, "student": student, "category": "Academic", "notes": SECRET, **values}
		return self.as_user(user, lambda: frappe.get_doc(doc).insert().name)

	def add_interaction(self, user, student, guardian, **values):
		doc = {"doctype": INTERACTION, "student": student, "guardian": guardian, "mode": "Phone", "outcome": "Discussed attendance", **values}
		return self.as_user(user, lambda: frappe.get_doc(doc).insert().name)

	def listed(self, user, doctype, names):
		return set(self.as_user(user, frappe.get_list, doctype, filters={"name": ["in", names]}, pluck="name"))

	def can(self, user, doctype, name, ptype="read"):
		return self.as_user(user, frappe.has_permission, doctype, ptype, name)


class TestCounsellingNoteAccess(MentoringFixture):
	def test_mentor_a_cannot_read_mentor_bs_mentee_notes(self):
		mine, theirs = self.add_note(MENTOR_A, self.a_student), self.add_note(MENTOR_B, self.b_student)
		self.assertEqual(self.listed(MENTOR_A, NOTE, [mine, theirs]), {mine})
		self.assertEqual(self.listed(MENTOR_B, NOTE, [mine, theirs]), {theirs})
		self.assertFalse(self.can(MENTOR_A, NOTE, theirs))
		with self.assertRaises(frappe.PermissionError):
			self.as_user(MENTOR_A, frappe.client.get, NOTE, theirs)

	def test_the_note_records_its_author_mentor_company_and_department(self):
		note = frappe.get_doc(NOTE, self.add_note(MENTOR_A, self.a_student))
		self.assertEqual((note.author, note.mentor, note.company), (MENTOR_A, demo.employee_of("faculty_1"), demo.ENGINEERING))
		self.assertEqual(note.department, frappe.db.get_value("Program", "B.E. CSE", "department"))

	def test_the_author_and_the_new_mentor_both_read_after_reallocation(self):
		note = self.add_note(MENTOR_A, self.a_student)
		frappe.db.set_value("Student", self.a_student, "oc_mentor", demo.employee_of("faculty_2"))
		self.assertTrue(self.can(MENTOR_A, NOTE, note))
		self.assertTrue(self.can(MENTOR_B, NOTE, note))
		self.assertFalse(self.can(MENTOR_B, NOTE, note, "write"))  # only the author edits

	def test_a_teacher_cannot_write_a_note_about_someone_elses_mentee(self):
		with self.assertRaises(frappe.PermissionError):
			self.add_note(MENTOR_A, self.b_student)

	def test_hod_principal_and_counsellors_read_open_notes_only(self):
		open_note = self.add_note(MENTOR_A, self.a_student)
		confidential = self.add_note(MENTOR_A, self.a_student, is_confidential=1, counsellor=COUNSELLOR)
		for user in (HOD, PRINCIPAL):
			self.assertEqual(self.listed(user, NOTE, [open_note, confidential]), {open_note}, user)
			self.assertFalse(self.can(user, NOTE, confidential), user)
			self.assertFalse(self.can(user, NOTE, open_note, "write"), user)
		self.assertEqual(self.listed(COUNSELLOR, NOTE, [open_note, confidential]), {open_note, confidential})
		self.assertFalse(self.can(MENTOR_B, NOTE, open_note))

	def test_a_confidential_note_is_hidden_from_the_current_mentor_and_hod_unless_designated(self):
		frappe.get_doc("User", HOD).add_roles(mentoring.COUNSELLOR_ROLE)
		other = make_counsellor("campus-l09-counsellor-2@example.com")
		hidden = self.add_note(COUNSELLOR, self.a_student, is_confidential=1, counsellor=other)
		designated = self.add_note(COUNSELLOR, self.a_student, is_confidential=1, counsellor=HOD)
		self.assertEqual(self.listed(HOD, NOTE, [hidden, designated]), {designated})
		self.assertFalse(self.can(HOD, NOTE, hidden))
		self.assertFalse(self.can(MENTOR_A, NOTE, hidden))  # the student's mentor, but not the author
		self.assertEqual(self.listed(other, NOTE, [hidden, designated]), {hidden})

	def test_the_designated_counsellor_must_hold_the_counsellor_role(self):
		with self.assertRaises(frappe.ValidationError):
			self.add_note(MENTOR_A, self.a_student, is_confidential=1, counsellor=MENTOR_B)

	def test_an_action_owner_must_be_able_to_read_the_note(self):
		with self.assertRaises(frappe.ValidationError):
			self.add_note(MENTOR_A, self.a_student, actions=[{"action": "Meet parents", "action_owner": MENTOR_B, "due_date": today()}])
		note = self.add_note(MENTOR_A, self.a_student, actions=[{"action": "Meet parents", "action_owner": MENTOR_A, "due_date": today()}])
		self.assertEqual(frappe.get_doc(NOTE, note).actions[0].action_owner, MENTOR_A)

	def test_a_note_cannot_be_shared(self):
		note = self.add_note(MENTOR_A, self.a_student)
		with self.assertRaises(frappe.PermissionError):
			frappe.share.add_docshare(NOTE, note, MENTOR_B, read=1, flags={"ignore_share_permission": True})
		self.assertFalse(self.can(MENTOR_B, NOTE, note))

	def test_a_former_mentor_who_is_not_the_author_loses_access(self):
		note = self.add_note(COUNSELLOR, self.a_student)
		self.assertTrue(self.can(MENTOR_A, NOTE, note))
		frappe.db.set_value("Student", self.a_student, "oc_mentor", demo.employee_of("faculty_2"))
		self.assertFalse(self.can(MENTOR_A, NOTE, note))
		self.assertEqual(self.listed(MENTOR_A, NOTE, [note]), set())
		self.assertTrue(self.can(MENTOR_B, NOTE, note))

	def test_the_hod_of_another_department_sees_nothing(self):
		hod = make_ece_hod()
		note, interaction = self.add_note(MENTOR_A, self.a_student), self.add_interaction(MENTOR_A, self.a_student, self.other_guardian)
		self.assertEqual(self.listed(hod, NOTE, [note]), set())
		self.assertEqual(self.listed(hod, INTERACTION, [interaction]), set())
		self.assertFalse(self.can(hod, NOTE, note))
		self.assertFalse(self.can(hod, INTERACTION, interaction))

	def test_author_mentor_company_and_department_stay_as_written(self):
		name = self.add_note(MENTOR_A, self.a_student)
		before = frappe.db.get_value(NOTE, name, ["mentor", "company", "department"])
		def tamper(values):
			doc = frappe.get_doc(NOTE, name)
			doc.update(values)
			doc.save()
		self.as_user(MENTOR_A, tamper, {"mentor": demo.employee_of("faculty_2"), "department": demo.department_name(demo.ECE_DEPARTMENT, demo.ENGINEERING)})
		tamper({"company": demo.ARTS})  # as Administrator: the author's own User Permissions would refuse the save
		self.assertEqual(frappe.db.get_value(NOTE, name, ["mentor", "company", "department"]), before)
		try:
			tamper({"student": self.b_student})
		except frappe.CannotChangeConstantError:
			pass
		self.assertEqual(frappe.db.get_value(NOTE, name, "student"), self.a_student)

	def test_the_designated_counsellor_must_belong_to_the_notes_company(self):
		arts = "campus-l09-arts-counsellor@example.com"
		make_user(arts, [demo.ARTS])
		frappe.get_doc("User", arts).add_roles(mentoring.COUNSELLOR_ROLE)
		with self.assertRaises(frappe.ValidationError):
			self.add_note(MENTOR_A, self.a_student, is_confidential=1, counsellor=arts)

	def test_a_guardian_reads_no_note(self):
		note = self.add_note(MENTOR_A, self.guarded)
		with self.assertRaises(frappe.PermissionError):  # the Guardian role has no right on the doctype at all
			self.listed(GUARDIAN, NOTE, [note])
		self.assertFalse(self.can(GUARDIAN, NOTE, note))


class TestParentInteractionAccess(MentoringFixture):
	def test_the_guardian_must_be_linked_to_the_student(self):
		with self.assertRaises(frappe.ValidationError):
			self.add_interaction(MENTOR_A, self.a_student, self.guardian)
		name = self.add_interaction(MENTOR_A, self.a_student, self.other_guardian)
		self.assertEqual(frappe.db.get_value(INTERACTION, name, "recorded_by"), MENTOR_A)

	def test_mentor_advisor_and_office_read_but_not_another_mentor(self):
		name = self.add_interaction(MENTOR_A, self.a_student, self.other_guardian)
		frappe.db.set_value("Student", self.a_student, "oc_class_advisor", demo.email("faculty_3"))
		frappe.get_doc("User", demo.email("faculty_3")).add_roles("Class Advisor")
		for user in (MENTOR_A, demo.email("faculty_3"), PRINCIPAL, HOD):
			self.assertEqual(self.listed(user, INTERACTION, [name]), {name}, user)
		self.assertEqual(self.listed(MENTOR_B, INTERACTION, [name]), set())
		self.assertFalse(self.can(MENTOR_B, INTERACTION, name))

	def test_a_teacher_cannot_record_an_interaction_for_someone_elses_mentee(self):
		with self.assertRaises(frappe.PermissionError):
			self.add_interaction(MENTOR_B, self.a_student, self.other_guardian)

	def test_a_guardian_of_another_student_sees_nothing(self):
		other = self.add_interaction(MENTOR_A, self.a_student, self.other_guardian)
		own = self.add_interaction(MENTOR_A, self.guarded, self.guardian)
		with self.assertRaises(frappe.PermissionError):
			self.listed(GUARDIAN, INTERACTION, [other, own])
		self.assertFalse(self.can(GUARDIAN, INTERACTION, other))
		self.assertFalse(self.can(GUARDIAN, INTERACTION, own))  # guardians read no interaction, not even their own

	def test_the_follow_up_owner_must_already_read_the_interaction(self):
		for owner in (GUARDIAN, MENTOR_B):
			with self.assertRaises(frappe.ValidationError):
				self.add_interaction(MENTOR_A, self.guarded, self.guardian, follow_up_owner=owner, follow_up_due=today())
		name = self.add_interaction(MENTOR_A, self.guarded, self.guardian, follow_up_owner=PRINCIPAL, follow_up_due=today())
		self.assertEqual(frappe.db.get_value(INTERACTION, name, "follow_up_owner"), PRINCIPAL)

	def test_only_the_current_mentor_advisor_and_office_edit(self):
		name = self.add_interaction(MENTOR_A, self.a_student, self.other_guardian)
		frappe.db.set_value("Student", self.a_student, {"oc_mentor": demo.employee_of("faculty_2"), "oc_class_advisor": demo.email("faculty_3")})
		self.assertTrue(self.can(MENTOR_A, INTERACTION, name))  # the recorder still reads it
		self.assertFalse(self.can(MENTOR_A, INTERACTION, name, "write"))
		for user in (MENTOR_B, demo.email("faculty_3"), PRINCIPAL):
			self.assertTrue(self.can(user, INTERACTION, name, "write"), user)
		self.assertFalse(self.can(HOD, INTERACTION, name, "write"))


class TestFollowUpReminders(MentoringFixture):
	def reminders(self, names):
		return frappe.get_all(
			"Message Log", {"event_key": mentoring.FOLLOW_UP_EVENT, "reference_name": ["in", names], "status": ["!=", "Skipped"]},
			["reference_name", "recipient", "dedupe_token", "message", "subject"],
		)  # fmt: skip

	def test_follow_ups_due_are_reminded_once_without_the_note_text(self):
		action = {"action": "Bring the parents in", "action_owner": MENTOR_A, "due_date": today()}
		note = self.add_note(MENTOR_A, self.a_student, follow_up_date=today(), actions=[action])
		interaction = self.add_interaction(MENTOR_A, self.guarded, self.guardian, follow_up_owner=MENTOR_A, follow_up_due=today())
		later = self.add_note(MENTOR_A, self.a_student, follow_up_date=add_days(today(), 3))
		done = self.add_interaction(MENTOR_A, self.guarded, self.guardian, follow_up_owner=MENTOR_A, follow_up_due=today(), follow_up_done=1)
		mentoring.send_follow_up_reminders()
		first = self.reminders([note, interaction, later, done])
		for log in frappe.get_all("Message Log", {"event_key": mentoring.FOLLOW_UP_EVENT, "reference_name": ["in", [note, interaction]]}, pluck="name"):
			frappe.db.set_value("Message Log", log, "status", "Sent")  # the test site has no mail account; a failed send may retry
		mentoring.send_follow_up_reminders()
		self.assertEqual(len(self.reminders([note, interaction, later, done])), len(first))
		keys = {(log.reference_name, log.recipient) for log in first}
		self.assertEqual(keys, {(note, f"User:{MENTOR_A}"), (interaction, f"User:{MENTOR_A}")})
		self.assertEqual(len({(log.reference_name, log.dedupe_token) for log in first}), 3)  # note follow-up, action, interaction
		for log in first:
			self.assertNotIn(SECRET, (log.message or "") + (log.subject or ""))
			self.assertNotIn("Bring the parents in", log.message or "")


class TestMentoringPortal(MentoringFixture):
	def page(self, student):
		frappe.set_user(MENTOR_A)
		set_request(method="GET", path="/campus-portal/faculty/mentees")
		with mock.patch.dict(frappe.local.form_dict, {"student": student}):
			return frappe.safe_decode(get_response_without_exception_handling().get_data())

	def test_the_mentee_page_escapes_notes_and_interactions(self):
		self.add_note(MENTOR_A, self.a_student, notes="Said <b>no</b> to the plan")
		self.add_interaction(MENTOR_A, self.a_student, self.other_guardian, outcome="Father <i>agreed</i>")
		frappe.db.set_value("Student Guardian", {"parent": self.a_student, "guardian": self.other_guardian}, "guardian_name", "<em>Mum</em>")
		html = self.page(self.a_student)
		for raw in ("<b>no</b>", "<i>agreed</i>", "<em>Mum</em>"):
			self.assertNotIn(raw, html)
		for escaped in ("&lt;b&gt;no&lt;/b&gt;", "&lt;i&gt;agreed&lt;/i&gt;", "&lt;em&gt;Mum&lt;/em&gt;"):
			self.assertIn(escaped, html)
		self.assertIn('data-method="campus.faculty.portal_mentoring.add_note"', html)

	def test_another_mentors_mentee_is_refused(self):
		self.add_note(MENTOR_B, self.b_student)
		with self.assertRaises(frappe.PermissionError):
			self.as_user(MENTOR_A, portal_mentoring.mentee_record, self.b_student)
		self.assertNotIn(SECRET, self.page(self.b_student))

	def test_the_mentor_adds_a_note_and_an_interaction_from_the_portal(self):
		note = self.as_user(MENTOR_A, portal_mentoring.add_note, self.a_student, "Personal", "Settling in", follow_up_date=today(),
			action="Check in next week", action_due=add_days(today(), 7))  # fmt: skip
		doc = frappe.get_doc(NOTE, note)
		self.assertEqual((doc.author, doc.actions[0].action_owner), (MENTOR_A, MENTOR_A))
		interaction = self.as_user(MENTOR_A, portal_mentoring.add_parent_interaction, self.a_student, self.other_guardian, "Phone", "Agreed")
		record = self.as_user(MENTOR_A, portal_mentoring.mentee_record, self.a_student)
		self.assertEqual([n["name"] for n in record["notes"]], [note])
		self.assertEqual([i["name"] for i in record["interactions"]], [interaction])
		with self.assertRaises(frappe.PermissionError):
			self.as_user(MENTOR_A, portal_mentoring.add_note, self.b_student, "Personal", "x")

	def test_writes_accept_post_only(self):
		for method in (portal_mentoring.add_note, portal_mentoring.add_parent_interaction):
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[method], ["POST"])


class TestMentoringActivityReport(MentoringFixture):
	def test_counts_only_including_confidential_notes(self):
		frappe.db.set_value("Student", self.c_student, "oc_mentor", demo.employee_of("faculty_1"))  # 3+ mentees
		self.add_note(MENTOR_A, self.a_student)
		self.add_note(MENTOR_A, self.a_student, is_confidential=1, counsellor=COUNSELLOR)
		self.add_interaction(MENTOR_A, self.a_student, self.other_guardian)
		columns, rows = self.as_user(HOD, mentoring_activity.execute, frappe._dict(company=demo.ENGINEERING))
		self.assertTrue(all(c["fieldtype"] in ("Link", "Data", "Int") for c in columns))
		self.assertNotIn("notes", [c["fieldname"] for c in columns])
		row = next(r for r in rows if r["mentor"] == demo.employee_of("faculty_1"))
		self.assertEqual((row["note_count"], row["confidential_count"], row["interaction_count"]), (2, 1, 1))
		self.assertGreaterEqual(row["mentees"], 3)
		self.assertNotIn(SECRET, frappe.as_json(rows))

	def test_the_confidential_count_is_blank_below_three_mentees(self):
		for student in frappe.get_all("Student", {"oc_mentor": demo.employee_of("faculty_2"), "name": ["!=", self.b_student]}, pluck="name"):
			frappe.db.set_value("Student", student, "oc_mentor", demo.employee_of("faculty_3"))
		self.add_note(MENTOR_B, self.b_student, is_confidential=1, counsellor=COUNSELLOR)
		_columns, rows = self.as_user(HOD, mentoring_activity.execute, frappe._dict(company=demo.ENGINEERING))
		row = next(r for r in rows if r["mentor"] == demo.employee_of("faculty_2"))
		self.assertEqual((row["mentees"], row["note_count"], row["confidential_count"]), (1, 1, None))

	def test_an_hod_sees_only_their_departments(self):
		self.add_note(MENTOR_A, self.a_student)
		hod = make_ece_hod()
		frappe.get_doc("User", hod).add_roles(mentoring.HOD_ROLE)
		_columns, rows = self.as_user(hod, mentoring_activity.execute, frappe._dict(company=demo.ENGINEERING))
		self.assertEqual(sum(r["note_count"] for r in rows), 0)  # every note here is about a CSE student
		cse_mentees = frappe.db.count("Student", {"oc_mentor": demo.employee_of("faculty_1")})
		row = next((r for r in rows if r["mentor"] == demo.employee_of("faculty_1")), None)
		self.assertTrue(row is None or row["mentees"] < cse_mentees)

	def test_a_company_outside_the_users_permissions_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(HOD, mentoring_activity.execute, frappe._dict(company=demo.ARTS))


class TestRestrictedRecordSideDoors(MentoringFixture):
	"""Comments, attachments and Connections counts of mentoring records follow the records' own read rules."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.sysman = "campus-l09-sysman@example.com"
		make_user(cls.sysman, [demo.ENGINEERING])
		frappe.get_doc("User", cls.sysman).add_roles("System Manager", "Website Manager")

	def add_comment(self, user, doctype, name, text):
		comment = {"doctype": "Comment", "comment_type": "Comment", "reference_doctype": doctype, "reference_name": name, "content": text}
		return self.as_user(user, lambda: frappe.get_doc(comment).insert(ignore_permissions=True).name)

	def attach(self, user, note, is_private=0):
		file = {"doctype": "File", "file_name": "l09-note.txt", "content": b"SECRET", "attached_to_doctype": NOTE, "attached_to_name": note, "is_private": is_private}
		return self.as_user(user, lambda: frappe.get_doc(file).insert().name)

	def test_comments_on_a_note_are_hidden_from_system_and_website_managers(self):
		note = self.add_note(MENTOR_A, self.a_student)
		hidden = self.add_comment(MENTOR_A, NOTE, note, SECRET)
		visible = self.add_comment("Administrator", "Student", self.a_student, "Ordinary comment")
		self.assertEqual(self.listed(self.sysman, "Comment", [hidden, visible]), {visible})
		self.assertFalse(self.can(self.sysman, "Comment", hidden))
		self.assertTrue(self.can(self.sysman, "Comment", visible))
		self.assertEqual(self.listed("Administrator", "Comment", [hidden, visible]), {hidden, visible})

	def test_note_files_are_private_and_listed_only_for_readers(self):
		note = self.add_note(MENTOR_A, self.a_student)
		name = self.attach(MENTOR_A, note, is_private=0)
		file = frappe.get_doc("File", name)
		self.assertEqual((file.is_private, file.file_url.startswith("/private/files/")), (1, True))
		self.assertEqual(self.listed(MENTOR_A, "File", [name]), {name})
		for user in (MENTOR_B, self.sysman):
			self.assertEqual(self.listed(user, "File", [name]), set(), user)
			self.assertFalse(self.can(user, "File", name), user)

	def test_unticking_private_on_a_note_file_is_overridden(self):
		name = self.attach(MENTOR_A, self.add_note(MENTOR_A, self.a_student), is_private=1)
		file = frappe.get_doc("File", name)
		file.is_private = 0
		file.save()
		self.assertEqual(frappe.db.get_value("File", name, "is_private"), 1)

	def test_a_former_mentor_cannot_read_a_file_they_uploaded(self):
		note = self.add_note(COUNSELLOR, self.a_student)
		name = self.attach(COUNSELLOR, note)
		frappe.db.set_value("File", name, "owner", MENTOR_A)  # uploaded by the mentor of that time
		frappe.db.set_value("Student", self.a_student, "oc_mentor", demo.employee_of("faculty_2"))
		self.assertFalse(self.can(MENTOR_A, "File", name))

	def test_connections_hide_how_many_records_a_guardian_cannot_read(self):
		self.add_note(MENTOR_A, self.guarded)
		self.add_interaction(MENTOR_A, self.guarded, self.guardian)
		raw = self.as_user(GUARDIAN, linked_with.get, "Student", self.guarded)
		self.assertGreaterEqual(raw[NOTE]["hidden_count"], 1)  # what Frappe alone would reveal
		shown = self.as_user(GUARDIAN, restricted_records.get_linked_docs, "Student", self.guarded)
		self.assertNotIn(NOTE, shown)
		self.assertNotIn(INTERACTION, shown)
		self.assertEqual(frappe.get_hooks("override_whitelisted_methods")["frappe.desk.form.linked_with.get"][-1],
			"campus.campus_platform.restricted_records.get_linked_docs")  # fmt: skip

	def open_counts(self, user, fn, student):
		self.addCleanup(frappe.db.set_execution_timeout, 0)  # get_open_count sets a 1 s statement limit
		result = self.as_user(user, fn, "Student", student, items=[NOTE, INTERACTION, "Program Enrollment"])
		return {d["doctype"]: d["count"] for d in result["count"]["external_links_found"]}

	def test_dashboard_counts_hide_records_a_guardian_cannot_read(self):
		self.add_note(MENTOR_A, self.guarded)
		self.add_interaction(MENTOR_A, self.guarded, self.guardian)
		raw = self.open_counts(GUARDIAN, notifications.get_open_count, self.guarded)
		self.assertGreaterEqual(raw[NOTE], 1)  # what Frappe alone would reveal for caller-chosen items
		shown = self.open_counts(GUARDIAN, restricted_records.get_open_count, self.guarded)
		self.assertNotIn(NOTE, shown)
		self.assertNotIn(INTERACTION, shown)
		self.assertIn("Program Enrollment", shown)  # other counts are left alone
		self.assertEqual(frappe.get_hooks("override_whitelisted_methods")["frappe.desk.notifications.get_open_count"][-1],
			"campus.campus_platform.restricted_records.get_open_count")  # fmt: skip

	def test_dashboard_counts_give_a_reader_their_permitted_count(self):
		self.add_note(MENTOR_A, self.a_student)
		self.add_note(MENTOR_A, self.a_student)
		self.add_note(COUNSELLOR, self.a_student, is_confidential=1, counsellor=COUNSELLOR)
		self.add_interaction(MENTOR_A, self.a_student, self.other_guardian)
		shown = self.open_counts(MENTOR_A, restricted_records.get_open_count, self.a_student)
		self.assertEqual((shown[NOTE], shown[INTERACTION]), (2, 1))

	def test_the_owner_of_a_note_file_cannot_download_it_without_reading_the_note(self):
		note = self.add_note(COUNSELLOR, self.a_student)
		name = self.attach(COUNSELLOR, note)
		frappe.db.set_value("File", name, "owner", MENTOR_A)  # uploaded by the mentor of that time
		frappe.db.set_value("Student", self.a_student, "oc_mentor", demo.employee_of("faculty_2"))
		url = frappe.db.get_value("File", name, "file_url")
		self.assertTrue(self.as_user(COUNSELLOR, find_file_by_url, url))
		self.assertIsNone(self.as_user(MENTOR_A, find_file_by_url, url))

	def test_a_second_file_row_with_the_url_neither_opens_nor_publishes_it(self):
		url = frappe.db.get_value("File", self.attach(MENTOR_A, self.add_note(MENTOR_A, self.a_student)), "file_url")
		copy = {"doctype": "File", "file_name": "copy.txt", "file_url": url, "is_private": 1}
		copy_name = frappe.get_doc(copy).insert().name  # Frappe lets only a reader add a row for a private URL
		frappe.db.set_value("File", copy_name, "owner", MENTOR_B)
		self.assertFalse(self.can(MENTOR_B, "File", copy_name))
		self.assertIsNone(self.as_user(MENTOR_B, find_file_by_url, url))
		with self.assertRaisesRegex(frappe.PermissionError, "cannot be made public"):
			frappe.get_doc({**copy, "file_name": "public.txt", "is_private": 0}).insert(ignore_permissions=True)

	def former_mentors_file(self):
		"""A counsellor's note File owned by mentor A, who is then reallocated away from the student."""
		name = self.attach(COUNSELLOR, self.add_note(COUNSELLOR, self.a_student))
		frappe.db.set_value("File", name, "owner", MENTOR_A)
		frappe.db.set_value("Student", self.a_student, "oc_mentor", demo.employee_of("faculty_2"))
		return name, frappe.db.get_value("File", name, "file_url")

	def zipped(self, user, names):
		self.as_user(user, restricted_records.zip_files, frappe.as_json(names))
		return zipfile.ZipFile(io.BytesIO(frappe.response.pop("filecontent"))).namelist()

	def test_a_former_mentor_owner_cannot_add_a_row_for_the_note_files_url(self):
		_name, url = self.former_mentors_file()
		copy = {"doctype": "File", "file_name": "copy.txt", "file_url": url, "is_private": 1}
		with self.assertRaises(frappe.PermissionError):  # the File permission hook refuses the create
			self.as_user(MENTOR_A, lambda: frappe.get_doc(copy).insert())
		with self.assertRaisesRegex(frappe.PermissionError, "cannot read"):  # and so does before_insert, past it
			self.as_user(MENTOR_A, lambda: frappe.get_doc(copy).insert(ignore_permissions=True))

	def test_a_former_mentor_owner_cannot_zip_the_note_file(self):
		name, _url = self.former_mentors_file()
		self.assertEqual(self.zipped(MENTOR_A, [name]), [])
		self.assertEqual(self.zipped(COUNSELLOR, [name]), [frappe.db.get_value("File", name, "file_name")])
		overrides = frappe.get_hooks("override_whitelisted_methods")
		for path in ("frappe.core.api.file.zip_files", "frappe.core.doctype.file.file.zip_files"):
			self.assertEqual(overrides[path][-1], "campus.campus_platform.restricted_records.zip_files", path)

	def test_the_attached_row_is_not_deleted_while_another_row_carries_its_url(self):
		name = self.attach(MENTOR_A, self.add_note(MENTOR_A, self.a_student))
		url = frappe.db.get_value("File", name, "file_url")
		copy = frappe.get_doc({"doctype": "File", "file_name": "copy.txt", "file_url": url, "is_private": 1}).insert().name
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("File", name)
		frappe.delete_doc("File", copy)
		frappe.delete_doc("File", name)
		self.assertFalse(frappe.db.exists("File", name))

	def test_a_note_file_cannot_be_detached_or_shared(self):
		name = self.attach(MENTOR_A, self.add_note(MENTOR_A, self.a_student))
		file = frappe.get_doc("File", name)
		file.update({"attached_to_doctype": None, "attached_to_name": None})
		with self.assertRaises(frappe.PermissionError):
			file.save()
		with self.assertRaises(frappe.PermissionError):
			frappe.share.add_docshare("File", name, MENTOR_B, read=1, flags={"ignore_share_permission": True})

	def test_connections_show_a_reader_only_their_records_and_no_hidden_count(self):
		mine = self.add_note(MENTOR_A, self.a_student)
		self.add_note(COUNSELLOR, self.a_student, is_confidential=1, counsellor=COUNSELLOR)
		shown = self.as_user(MENTOR_A, restricted_records.get_linked_docs, "Student", self.a_student)
		self.assertEqual(([d["name"] for d in shown[NOTE]["docs"]], shown[NOTE]["hidden_count"]), ([mine], 0))


def make_ece_hod():
	hod = "campus-l09-ece-hod@example.com"
	make_user(hod, [demo.ENGINEERING])
	frappe.get_doc("User", hod).add_roles(mentoring.HOD_ROLE)
	department = demo.department_name(demo.ECE_DEPARTMENT, demo.ENGINEERING)
	if not frappe.db.exists("Position Holder", {"user": hod, "position": "HOD"}):
		frappe.get_doc({"doctype": "Position Holder", "position": "HOD", "scope_value": department, "user": hod, "from_date": "2022-06-01"}).insert()
	return hod


def make_counsellor(email):
	make_user(email, [demo.ENGINEERING])
	frappe.get_doc("User", email).add_roles(mentoring.COUNSELLOR_ROLE)
	return email
