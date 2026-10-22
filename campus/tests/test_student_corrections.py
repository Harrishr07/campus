"""L-08 (M05-11, NFR history preservation) Student record correction workflow and the student 360 view: a correction
is applied only on approval and keeps a Version, a rejected one changes nothing, a student raises only the portal
categories, locked fields refuse direct edits except for the override role, and each 360 section shows only to the
roles that can read its source (mentoring only the notes the viewer may read)."""

import json
from unittest.mock import patch

import frappe

from campus.campus_platform.approvals import approve, reject, request_approval
from campus.student_services import corrections, portal, student_360
from campus.tests import demo
from campus.tests.factories import make_user
from campus.tests.test_mentoring import MENTOR_A, MENTOR_B, MentoringFixture

DOCTYPE = corrections.DOCTYPE
OFFICE, COE, PRINCIPAL = demo.email("admissions"), demo.email("coe"), demo.email("principal")
STUDENT_USER, GUARDIAN_USER = demo.email("student_1"), demo.email("guardian_1")
ACCOUNTS = demo.email("accounts")
ADMIN_USER = "campus-l08-sysmgr@example.com"
NEW_MOBILE, NEW_AADHAAR = "9876543210", "234123412346"
EVIDENCE = ("proof.png", b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\xdacd`\xf8_\x0f\x00\x02\x87\x01\x80\xebG\xba\x92\x00\x00\x00\x00IEND\xaeB`\x82')  # a 1x1 PNG


def versions(student):
	return frappe.get_all("Version", {"ref_doctype": "Student", "docname": student}, "data", order_by="creation asc")


class CorrectionFixture(MentoringFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.student = cls.guarded  # the guardian_1 login's ward; student_1 is linked to the same record
		frappe.db.set_value("Student", cls.student, {"user": STUDENT_USER, "enabled": 1}, update_modified=False)
		if not frappe.db.exists("Position Holder", {"position": "COE", "user": COE}):
			frappe.get_doc(
				{"doctype": "Position Holder", "position": "COE", "scope_value": demo.ENGINEERING, "user": COE, "from_date": "2022-06-01"}
			).insert()
		corrections.seed_policies()
		make_user(ADMIN_USER, [demo.ENGINEERING])
		frappe.get_doc("User", ADMIN_USER).add_roles("System Manager")

	def correction(self, category="Contact", field="student_mobile_number", value=NEW_MOBILE, **values):
		doc = {"doctype": DOCTYPE, "student": self.student, "category": category, "field_name": field, "new_value": value, "reason": "Wrong entry", **values}
		return self.as_user(OFFICE, lambda: frappe.get_doc(doc).insert())

	def send(self, doc):
		return self.as_user(OFFICE, request_approval, DOCTYPE, doc.name)

	def status(self, doc):
		return frappe.db.get_value(DOCTYPE, doc.name, "status")

	def value(self, field="student_mobile_number"):
		return frappe.db.get_value("Student", self.student, field)


class TestCorrectionWorkflow(CorrectionFixture):
	def test_applied_only_after_approval_and_a_version_is_kept(self):
		before, count = self.value(), len(versions(self.student))
		doc = self.correction()
		self.assertEqual((doc.status, doc.old_value), ("Draft", before or ""))
		request = self.send(doc)
		self.assertEqual(self.status(doc), "Pending")
		self.assertEqual(self.value(), before)  # nothing changes while it waits
		self.as_user(COE, approve, request)
		doc.reload()
		self.assertEqual((doc.status, self.value()), ("Applied", NEW_MOBILE))
		self.assertEqual(len(versions(self.student)), count + 1)
		changed = json.loads(versions(self.student)[-1].data)["changed"]
		self.assertIn(["student_mobile_number", before, NEW_MOBILE], changed)
		self.assertTrue(doc.version and doc.applied_on and doc.applied_by == COE)

	def test_rejected_correction_changes_nothing(self):
		before, count = self.value(), len(versions(self.student))
		doc = self.correction()
		self.as_user(COE, reject, self.send(doc), "Not supported by the proof")
		self.assertEqual(self.status(doc), "Rejected")
		self.assertEqual((self.value(), len(versions(self.student))), (before, count))

	def test_a_correction_cannot_be_applied_by_editing_or_submitting_it(self):
		doc = self.correction()
		with self.assertRaises(frappe.ValidationError):
			self.as_user(OFFICE, lambda: frappe.get_doc(DOCTYPE, doc.name).submit())
		self.assertEqual(self.value() != NEW_MOBILE, True)

	def test_pending_correction_is_frozen(self):
		doc = self.correction()
		self.send(doc)
		doc.reload()
		doc.new_value = "9000000000"
		with self.assertRaises(frappe.ValidationError):
			self.as_user(OFFICE, doc.save)

	def test_identity_correction_needs_the_principal_after_the_coe_and_never_shows_the_number(self):
		doc = self.correction("Identity Document", "oc_aadhaar", NEW_AADHAAR, evidence="/private/files/aadhaar.pdf")
		self.assertEqual(doc.new_value, "XXXX-XXXX-2346")
		request = self.send(doc)
		self.as_user(COE, approve, request)
		self.assertEqual(self.status(doc), "Pending")  # the higher approver is still to act
		self.as_user(PRINCIPAL, approve, request)
		self.assertEqual(self.status(doc), "Applied")
		self.assertEqual(self.value("oc_aadhaar_masked"), "XXXX-XXXX-2346")
		self.assertNotIn(NEW_AADHAAR, "".join(v.data for v in versions(self.student)))
		self.assertFalse(frappe.db.exists("__Auth", {"doctype": DOCTYPE, "name": doc.name}))

	def test_identity_and_academic_corrections_need_evidence(self):
		doc = self.correction("Academic Identifier", "oc_roll_no", "ROLL-L08-1")
		with self.assertRaises(frappe.ValidationError):
			self.send(doc)
		self.assertEqual(self.status(doc), "Draft")

	def test_a_duplicate_register_number_is_refused_when_raised(self):
		other = frappe.db.get_value("Student", {"oc_register_no": ["is", "set"], "name": ["!=", self.student]}, "oc_register_no")
		with self.assertRaises(frappe.ValidationError):
			self.correction("Academic Identifier", "oc_register_no", other, evidence="/private/files/x.pdf")

	def test_lifecycle_status_and_fields_outside_the_category_are_not_correctable(self):
		for category, field in (("Personal", "oc_academic_status"), ("Contact", "date_of_birth"), ("Personal", "oc_detained")):
			with self.assertRaises(frappe.ValidationError):
				self.correction(category, field, "Active")

	def test_evidence_must_be_private(self):
		with self.assertRaises(frappe.ValidationError):
			self.correction(evidence="/files/public.pdf")

	def test_guardian_correction_changes_the_guardian_of_the_student_only(self):
		guardian = frappe.db.get_value("Student Guardian", {"parent": self.student, "parenttype": "Student"}, "guardian")
		doc = self.correction("Guardian", "mobile_number", NEW_MOBILE, guardian=guardian, evidence="/private/files/g.pdf")
		self.as_user(COE, approve, self.send(doc))
		self.assertEqual(frappe.db.get_value("Guardian", guardian, "mobile_number"), NEW_MOBILE)
		with self.assertRaises(frappe.ValidationError):
			self.correction("Guardian", "mobile_number", NEW_MOBILE, guardian=self.other_guardian, evidence="/private/files/g.pdf")


class TestPortalCorrections(CorrectionFixture):
	def raise_as(self, user, category, field, value=NEW_MOBILE, upload=None, **kwargs):
		with patch.object(portal, "uploaded_file", return_value=upload):
			return self.as_user(user, corrections.raise_correction, category, field, value, "Wrong entry", **kwargs)

	def test_student_raises_a_contact_correction_that_waits_for_approval(self):
		row = self.raise_as(STUDENT_USER, "Contact", "student_mobile_number")
		self.assertEqual(row["status"], "Pending")
		self.assertNotEqual(self.value(), NEW_MOBILE)
		self.as_user(COE, approve, frappe.db.get_value("Approval Request", {"reference_name": row["name"]}))
		self.assertEqual(self.value(), NEW_MOBILE)

	def test_guardian_raises_for_the_ward_and_evidence_is_kept_private(self):
		row = self.raise_as(GUARDIAN_USER, "Personal", "nationality", "Indian", upload=EVIDENCE)
		self.assertTrue(frappe.db.get_value(DOCTYPE, row["name"], "evidence").startswith("/private/"))

	def test_personal_correction_without_evidence_is_refused_and_nothing_is_left(self):
		count = frappe.db.count(DOCTYPE)
		with self.assertRaises(frappe.ValidationError):
			self.raise_as(STUDENT_USER, "Personal", "nationality", "Indian")
		self.assertEqual(frappe.db.count(DOCTYPE), count)

	def test_student_cannot_raise_identity_academic_or_disallowed_fields(self):
		for category, field in (("Identity Document", "oc_aadhaar"), ("Academic Identifier", "oc_roll_no"),
				("Personal", "oc_academic_status"), ("Contact", "oc_register_no"), ("Personal", "customer")):  # fmt: skip
			with self.assertRaises(frappe.ValidationError, msg=field):
				self.raise_as(STUDENT_USER, category, field, "X123", upload=EVIDENCE)

	def test_a_student_cannot_correct_another_student(self):
		with self.assertRaises(frappe.PermissionError):
			self.raise_as(STUDENT_USER, "Contact", "student_mobile_number", student=self.a_student)

	def test_portal_view_shows_the_students_own_record_without_mentoring(self):
		self.add_note(MENTOR_A, self.student)
		view = self.as_user(STUDENT_USER, student_360.portal_view)
		self.assertEqual(view.student, self.student)
		self.assertIn("status", view)
		self.assertNotIn("mentoring", view)
		self.assertNotIn(self.student, [n for n in json.dumps(view, default=str).split('"') if n.startswith("CN-")])
		ward = self.as_user(GUARDIAN_USER, student_360.portal_view)
		self.assertEqual(ward.student, self.student)
		with self.assertRaises(frappe.PermissionError):
			self.as_user(STUDENT_USER, student_360.portal_view, self.a_student)


class TestLockedFields(CorrectionFixture):
	def edit(self, user, field, value):
		def save():
			doc = frappe.get_doc("Student", self.student)
			doc.set(field, value)
			doc.save()
		return self.as_user(user, save)

	def test_locked_field_refuses_a_direct_edit_and_the_override_role_can(self):
		self.assertIn("oc_roll_no", corrections.locked_fields())
		with self.assertRaises(frappe.PermissionError):
			self.edit(OFFICE, "oc_roll_no", "ROLL-L08-2")
		with self.assertRaises(frappe.PermissionError):
			self.edit(OFFICE, "date_of_birth", "2001-01-01")
		self.edit(ADMIN_USER, "oc_roll_no", "ROLL-L08-2")
		self.assertEqual(self.value("oc_roll_no"), "ROLL-L08-2")

	def test_unlocked_fields_and_the_correction_service_still_save(self):
		self.edit(OFFICE, "city", "Madurai")
		self.assertEqual(self.value("city"), "Madurai")
		doc = self.correction("Academic Identifier", "oc_roll_no", "ROLL-L08-3", evidence="/private/files/r.pdf")
		self.as_user(COE, approve, self.send(doc))
		self.as_user(PRINCIPAL, approve, frappe.db.get_value("Approval Request", {"reference_name": doc.name}))
		self.assertEqual(self.value("oc_roll_no"), "ROLL-L08-3")

	def test_settings_reject_a_field_with_no_workflow(self):
		settings = frappe.get_doc(corrections.SETTINGS)
		settings.locked_fields = "oc_academic_status"
		with self.assertRaises(frappe.ValidationError):
			settings.save()


class Test360View(CorrectionFixture):
	def sections(self, user, student=None):
		return set(self.as_user(user, student_360.desk_view, student or self.student)["sections"])

	def test_office_sees_the_record_sections_but_not_mentoring(self):
		sections = self.sections(OFFICE)
		self.assertTrue({"profile", "lifecycle", "enrollments", "corrections"} <= sections)
		self.assertNotIn("mentoring", sections)

	def test_sections_follow_the_viewers_read_rights(self):
		for user in (OFFICE, PRINCIPAL, MENTOR_A, ADMIN_USER):
			sections = self.sections(user)
			for key, doctype, _build in student_360.SECTIONS:
				allowed = self.as_user(user, frappe.has_permission, doctype, "read")
				self.assertEqual(key in sections, bool(allowed), f"{user} {key}")

	def test_profile_masks_the_aadhaar_and_never_includes_it(self):
		profile = self.as_user(OFFICE, student_360.desk_view, self.student)["sections"]["profile"]
		self.assertNotIn("oc_aadhaar", profile)

	def test_a_user_who_cannot_read_the_student_gets_nothing(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(STUDENT_USER, student_360.desk_view, self.a_student)

	def test_mentoring_lists_only_notes_the_viewer_can_read(self):
		note = self.add_note(MENTOR_A, self.a_student)
		secret = self.add_note(MENTOR_A, self.a_student, is_confidential=1)
		for viewer, expected in ((MENTOR_A, {note, secret}), (PRINCIPAL, {note})):
			mentoring = self.as_user(viewer, student_360.desk_view, self.a_student)["sections"]["mentoring"]
			self.assertEqual(set(mentoring["counselling_notes"]["names"]), expected, viewer)
			self.assertEqual(mentoring["counselling_notes"]["count"], len(expected))
			self.assertNotIn("SECRET-NOTE-TEXT", json.dumps(mentoring))

	def test_another_mentor_cannot_open_the_360_of_a_mentee_they_cannot_read(self):
		if not self.as_user(MENTOR_B, frappe.has_permission, "Student", "read", self.a_student):
			with self.assertRaises(frappe.PermissionError):
				self.as_user(MENTOR_B, student_360.desk_view, self.a_student)
		else:
			mentoring = self.as_user(MENTOR_B, student_360.desk_view, self.a_student)["sections"].get("mentoring") or {}
			self.assertEqual(mentoring.get("counselling_notes", {"count": 0})["count"], 0)

	def test_corrections_and_lifecycle_history_appear_in_the_360(self):
		doc = self.correction()
		view = self.as_user(OFFICE, student_360.desk_view, self.student)["sections"]
		self.assertIn(doc.name, [row.name for row in view["corrections"]])
		self.assertTrue(view["lifecycle"]["history"])


class TestPortalPages(CorrectionFixture):
	def test_profile_and_corrections_pages_show_the_students_own_data(self):
		from campus.www.campus_portal import corrections as corrections_page, profile as profile_page

		row = TestPortalCorrections.raise_as(self, STUDENT_USER, "Contact", "student_mobile_number")
		for page in (profile_page, corrections_page):
			frappe.set_user(STUDENT_USER)
			context = frappe._dict()
			page.get_context(context)
			self.assertEqual(context.student, self.student)
		self.assertIn(row["name"], [c["name"] for c in context.corrections])
		self.assertEqual([g["category"] for g in context.fields], ["Personal", "Contact", "Guardian"])
