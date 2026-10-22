"""M06-04 integration tests: dummy numbers, answer script bundles, double valuation, third valuation and the
final ESE mark on the map, written back to the Mark Sheet Entry by an Exam Confidential job. Examiners never reach a
register number or a name, and nothing they do touches a mark sheet."""

from unittest.mock import patch

import frappe
from frappe.desk import reportview
from frappe.desk.search import search_link

from campus.examinations import dummy_numbers, valuation, valuation_rules, valuation_write_back
from campus.tests.test_attendance_condonation import inline_bulk
from campus.tests.test_exam_seating import make_room
from campus.tests.test_results import COE_USER, FACULTY, ExamFixture, make_login
from campus.tests.test_verification import request_as

CONFIDENTIAL_USER = "exam-confidential@example.com"
SYSTEM_MANAGER = "exam-sysmgr@example.com"
VAL1, VAL2, VAL3 = "exam-val1@example.com", "exam-val2@example.com", "exam-val3@example.com"
COURSE = "EXM TH"  # ESE out of 60 in both regulations; third valuation above 15% (9 marks)
MAP = "Dummy Number Map"


class ValuationFixture(ExamFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for user, role in (
			(CONFIDENTIAL_USER, "Exam Confidential"), (SYSTEM_MANAGER, "System Manager"),
			(VAL1, "Examiner"), (VAL2, "Examiner"), (VAL3, "Examiner"),
		):  # fmt: skip
			make_login(user, role)

	def setUp(self):
		super().setUp()
		self.plan = self.seat([(self.s22.name, 0), (self.s26.name, 0), (self.s_ab.name, 1)])
		self.generated = self.generate()
		self.d22, self.d26 = self.dummy_of(self.s22.name), self.dummy_of(self.s26.name)

	def seat(self, students):
		room = make_room("Exm Val Hall", 2, 2, [], company=self.session.company).name
		plan = frappe.new_doc("Seating Plan")
		plan.update({"exam_session": self.session.name, "exam_date": "2022-12-01", "slot": "FN", "halls": [{"room": room}]})
		for i, (student, absent) in enumerate(students):
			row, column = divmod(i, 2)
			plan.append("seats", {"room": room, "seat_row": row + 1, "seat_column": column + 1,
				"seat_label": f"R{row + 1}C{column + 1}", "student": student, "course": COURSE, "absent": absent})  # fmt: skip
		plan.flags.generating = True  # stands in for Generate Seating
		return plan.insert()

	def generate(self):
		frappe.set_user(CONFIDENTIAL_USER)
		try:
			return dummy_numbers.generate(self.session.name, COURSE)
		finally:
			frappe.set_user("Administrator")

	def write_back(self):
		"""Exam Confidential's write-back job, run inline (the real runner commits per chunk)."""
		frappe.set_user(CONFIDENTIAL_USER)
		try:
			with patch.object(valuation_write_back, "run_bulk", inline_bulk):
				return valuation_write_back.write_back_pending(self.session.name, COURSE)
		finally:
			frappe.set_user("Administrator")

	def final_of(self, dummy):
		return frappe.db.get_value(MAP, {"dummy_number": dummy}, ["finalised", "final_ese", "ese_written"])

	def dummy_of(self, student):
		return frappe.db.get_value(MAP, {"exam_session": self.session.name, "student": student}, "dummy_number")

	def bundle(self, dummies=None, expected=None, received=1, maxima=(30, 30)):
		dummies = dummies or [self.d22, self.d26]
		expected = expected or len(dummies)
		frappe.set_user(COE_USER)
		doc = frappe.get_doc(
			{
				"doctype": "Answer Script Bundle", "exam_session": self.session.name, "course": COURSE, "packet_no": "P1",
				"expected_count": expected, "status": "Complete" if received and expected == len(dummies) else "Open",
				"scripts": [{"dummy_number": d, "received": received} for d in dummies],
				"questions": [{"question": f"Q{i}", "max_marks": m} for i, m in enumerate(maxima, 1)],
			}
		).insert()  # fmt: skip
		frappe.set_user("Administrator")
		return doc

	def allocate(self, bundle, valuation_round, examiner, **extra):
		frappe.set_user(COE_USER)
		try:
			return frappe.get_doc(
				{
					"doctype": "Valuation Allocation", "bundle": bundle.name, "valuation_round": str(valuation_round),
					"examiner_type": "External", "examiner": examiner, "deadline": "2022-12-20", **extra,
				}
			).insert()  # fmt: skip
		finally:
			frappe.set_user("Administrator")

	def value(self, allocation, dummy, q1, q2, user):
		frappe.set_user(user)
		try:
			return valuation.submit_marks(allocation.name, dummy, q_1=q1, q_2=q2)
		finally:
			frappe.set_user("Administrator")

	def double_valued(self):
		"""d22: 40 vs 50 (16.7%: third valuation); d26: 40 vs 48 (13.3%: final 44)."""
		bundle = self.bundle()
		first, second = self.allocate(bundle, 1, VAL1), self.allocate(bundle, 2, VAL2)
		for dummy, (v1, v2) in ((self.d22, (40, 50)), (self.d26, (40, 48))):
			self.value(first, dummy, 20, v1 - 20, VAL1)
			self.value(second, dummy, 20, v2 - 20, VAL2)
		return bundle

	def valued_d26(self):
		"""A bundle of d26 alone, valued 40 and 48 (final 44): d22 is left unbundled."""
		bundle = self.bundle([self.d26])
		first, second = self.allocate(bundle, 1, VAL1), self.allocate(bundle, 2, VAL2)
		self.value(first, self.d26, 20, 20, VAL1)
		self.value(second, self.d26, 20, 28, VAL2)
		return bundle

	def valued_all(self):
		"""Both scripts in one bundle, within the threshold: d22 40/46 (final 43), d26 40/48 (final 44)."""
		bundle = self.bundle()
		first, second = self.allocate(bundle, 1, VAL1), self.allocate(bundle, 2, VAL2)
		for dummy, v2 in ((self.d22, 46), (self.d26, 48)):
			self.value(first, dummy, 20, 20, VAL1)
			self.value(second, dummy, 20, v2 - 20, VAL2)
		return bundle

	def sheet_of(self, student):
		return frappe.db.get_value("Mark Sheet Entry Row", {"student": student, "parent": ["in", self.sheets()]}, "parent")

	def sheet_ese(self, student):
		row = frappe.db.get_value(
			"Mark Sheet Entry Row",
			{"parenttype": "Mark Sheet Entry", "student": student, "parent": ["in", self.sheets()]},
			["ese", "ese_from_valuation"],
			as_dict=True,
		)
		return (row.ese, row.ese_from_valuation)

	def sheets(self):
		return frappe.get_all(
			"Mark Sheet Entry",
			{"exam_session": self.session.name, "course_offering": ["in", [self.offerings22[COURSE], self.offerings26[COURSE]]]},
			pluck="name",
		)

	def round3(self, bundle):
		return frappe.get_doc("Valuation Allocation", {"bundle": bundle.name, "valuation_round": "3"})


class TestDummyNumbers(ValuationFixture):
	def test_seated_students_present_get_random_unique_numbers_and_absentees_none(self):
		self.assertEqual(self.generated, 2)
		self.assertIsNone(self.dummy_of(self.s_ab.name))  # absent from the exam
		self.assertNotEqual(self.d22, self.d26)
		for number in (self.d22, self.d26):
			self.assertTrue(number.isdigit() and len(number) == 8, number)

	def test_regeneration_keeps_the_numbers(self):
		frappe.set_user(CONFIDENTIAL_USER)
		self.assertEqual(dummy_numbers.generate(self.session.name, COURSE), 0)
		self.assertEqual((self.dummy_of(self.s22.name), self.dummy_of(self.s26.name)), (self.d22, self.d26))

	def test_only_exam_confidential_generates_and_only_by_post(self):
		for user in (COE_USER, SYSTEM_MANAGER, VAL1):
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				dummy_numbers.generate_dummy_numbers(self.session.name, COURSE)
		fn = dummy_numbers.generate_dummy_numbers
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["POST"])
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[valuation.submit_marks], ["POST"])

	def test_the_map_keeps_no_version_history(self):
		self.assertFalse(frappe.get_meta(MAP).track_changes)
		self.assertFalse(frappe.db.exists("Version", {"ref_doctype": MAP}))


class TestPermissionIsolation(ValuationFixture):
	def assert_map_closed(self, user):
		frappe.set_user(user)
		name = frappe.db.get_value(MAP, {"dummy_number": self.d22})
		self.assertFalse(frappe.has_permission(MAP, "read", doc=name, user=user))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(MAP, name).check_permission("read")
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(MAP, fields=["student", "dummy_number"])
		with self.assertRaises(frappe.PermissionError):
			frappe.client.get_value(MAP, ["student"], {"dummy_number": self.d22})
		with self.assertRaises(frappe.PermissionError):
			reportview.execute(MAP, fields=["student", "dummy_number"])
		with self.assertRaises(frappe.PermissionError):
			search_link(MAP, self.d22)

	def test_examiners_and_other_roles_cannot_reach_the_map_by_any_path(self):
		for user in (VAL1, COE_USER, SYSTEM_MANAGER):
			self.assert_map_closed(user)

	def test_a_custom_docperm_does_not_open_the_map_to_a_non_confidential_user(self):
		frappe.get_doc({"doctype": "Custom DocPerm", "parent": MAP, "role": "System Manager", "read": 1}).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=MAP)
		self.addCleanup(frappe.clear_cache, doctype=MAP)
		frappe.set_user(SYSTEM_MANAGER)
		self.assertFalse(frappe.has_permission(MAP, "read", doc=frappe.db.get_value(MAP, {"dummy_number": self.d22})))
		self.assertEqual(frappe.get_list(MAP, pluck="name"), [])

	def test_exam_confidential_joins_dummy_to_register_number(self):
		frappe.set_user(CONFIDENTIAL_USER)
		rows = frappe.get_list(MAP, {"exam_session": self.session.name}, ["student", "dummy_number"])
		self.assertEqual({r.dummy_number: r.student for r in rows}, {self.d22: self.s22.name, self.d26: self.s26.name})

	def test_the_map_cannot_be_shared(self):
		name = frappe.db.get_value(MAP, {"dummy_number": self.d22})
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be shared"):
			frappe.share.add_docshare(MAP, name, VAL1, read=1, flags={"ignore_share_permission": 1})

	def test_nothing_an_examiner_reads_carries_a_register_number_or_a_name(self):
		bundle = self.double_valued()
		allocation = frappe.get_doc("Valuation Allocation", {"bundle": bundle.name, "valuation_round": "1"})
		frappe.set_user(VAL1)
		entries = frappe.get_list("Valuation Entry", fields=["*"])
		self.assertEqual(len(entries), 2)
		seen = [frappe.as_json(entries), frappe.as_json(frappe.get_list("Valuation Allocation", fields=["*"]))]
		for entry in entries:
			doc = frappe.get_doc("Valuation Entry", entry.name)
			doc.check_permission("read")
			seen += [frappe.as_json(doc.as_dict()), frappe.get_print("Valuation Entry", doc.name)]
		allocation.check_permission("read")
		seen += [frappe.as_json(allocation.as_dict()), frappe.get_print("Valuation Allocation", allocation.name)]
		seen.append(frappe.as_json(valuation.my_allocations()))
		text = "\n".join(seen)
		self.assertIn(self.d22, text)
		for student in (self.s22, self.s26):
			self.assertNotIn(student.name, text)
			self.assertNotIn(student.student_name, text)

	def test_an_examiner_reads_only_their_own_allocations_and_entries(self):
		bundle = self.double_valued()
		frappe.set_user(VAL2)
		entries = frappe.get_list("Valuation Entry", fields=["valuation_round"])
		self.assertEqual({e.valuation_round for e in entries}, {"2"})
		mine = frappe.get_list("Valuation Allocation", pluck="name")
		first = frappe.db.get_value("Valuation Allocation", {"bundle": bundle.name, "valuation_round": "1"})
		self.assertNotIn(first, mine)
		self.assertFalse(frappe.has_permission("Valuation Allocation", "read", doc=first, user=VAL2))
		self.assertFalse(frappe.has_permission("Answer Script Bundle", "read", doc=bundle.name, user=VAL2))

	def test_an_examiner_cannot_post_marks_on_another_examiners_allocation(self):
		bundle = self.bundle()
		first = self.allocate(bundle, 1, VAL1)
		with self.assertRaises(frappe.PermissionError):
			self.value(first, self.d22, 20, 20, VAL2)

	def test_a_dummy_number_outside_the_allocation_is_refused_without_naming_anyone(self):
		bundle = self.bundle([self.d22])
		first = self.allocate(bundle, 1, VAL1)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.value(first, self.d26, 20, 20, VAL1)
		self.assertNotIn(self.s26.name, str(caught.exception))

	def test_a_rule_lookup_error_reaches_the_examiner_without_the_student(self):
		bundle = self.bundle([self.d22])
		first = self.allocate(bundle, 1, VAL1)

		def failing(student, course):
			frappe.throw(f"The Exam Rule Set of the regulation of {student} has no Theory course type.")

		with patch.object(valuation, "student_limits", failing), self.assertRaises(frappe.ValidationError) as caught:
			self.value(first, self.d22, 20, 20, VAL1)
		self.assertIn(self.d22, str(caught.exception))
		self.assertNotIn(self.s22.name, str(caught.exception) + frappe.as_json(frappe.local.message_log))


class TestThirdValuation(ValuationFixture):
	def test_a_difference_above_the_threshold_allocates_a_third_valuation(self):  # AC2
		bundle = self.double_valued()
		third = self.round3(bundle)
		self.assertEqual([s.dummy_number for s in third.scripts], [self.d22])
		self.assertEqual(third.status, "Unassigned")
		self.assertEqual(self.sheet_ese(self.s22.name), (35, 0))  # no final mark yet: the fixture's ESE stands

	def test_a_difference_within_the_threshold_gives_the_final_mark_at_once(self):
		self.double_valued()
		self.assertEqual(self.final_of(self.d26), (1, 44, 0))  # (40 + 48) / 2, on the map only
		self.assertEqual(self.sheet_ese(self.s26.name), (35, 0))  # the examiner's request wrote no mark sheet

	def test_the_third_valuation_settles_the_mark_by_the_closest_two(self):
		bundle = self.double_valued()
		third = self.round3(bundle)
		frappe.set_user(COE_USER)
		third.examiner = VAL3
		third.save()
		self.value(third, self.d22, 20, 27, VAL3)  # 47: (50 + 47) / 2 = 48.5 -> 49
		self.assertEqual(self.final_of(self.d22), (1, 49, 0))
		self.assertEqual(self.sheet_ese(self.s22.name), (35, 0))
		self.assertEqual(self.write_back(), 2)
		self.assertEqual((self.sheet_ese(self.s22.name), self.sheet_ese(self.s26.name)), ((49, 1), (44, 1)))
		self.assertEqual(self.final_of(self.d22), (1, 49, 1))

	def test_the_configured_rule_applies(self):
		rule_set = frappe.db.get_value("Exam Rule Set", {"regulation": frappe.db.get_value("Student", self.s22.name, "oc_regulation")})
		frappe.db.set_value("Exam Rule Set", rule_set, "final_valuation_method", "Average of Third and Nearer")
		bundle = self.bundle([self.d22])
		first, second = self.allocate(bundle, 1, VAL1), self.allocate(bundle, 2, VAL2)
		self.value(first, self.d22, 10, 10, VAL1)  # 20
		self.value(second, self.d22, 15, 15, VAL2)  # 30: 16.7% apart
		third = self.round3(bundle)
		frappe.set_user(COE_USER)
		third.examiner = VAL3
		third.save()
		self.value(third, self.d22, 30, 30, VAL3)  # 60: nearer is 30 -> 45 (closest two would give 25)
		self.assertEqual(self.final_of(self.d22), (1, 45, 0))

	def test_one_examiner_cannot_value_a_bundle_twice(self):
		bundle = self.bundle()
		self.allocate(bundle, 1, VAL1)
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.allocate(bundle, 2, VAL1)

	def test_a_script_is_valued_once_per_round(self):
		bundle = self.bundle()
		first = self.allocate(bundle, 1, VAL1)
		self.value(first, self.d22, 20, 20, VAL1)
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.value(first, self.d22, 20, 21, VAL1)

	def test_question_marks_must_lie_within_their_maximum(self):
		bundle = self.bundle()
		first = self.allocate(bundle, 1, VAL1)
		with self.assertRaises(frappe.ValidationError):
			self.value(first, self.d22, 31, 0, VAL1)


class TestEntryChecks(ValuationFixture):
	def test_the_ese_maximum_message_names_no_maximum(self):
		bundle = self.bundle(maxima=(40, 40))
		first = self.allocate(bundle, 1, VAL1)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.value(first, self.d22, 40, 30, VAL1)  # 70 > the ESE maximum 60
		self.assertNotIn("60", str(caught.exception))

	def test_the_course_teacher_rule_is_checked_again_at_entry(self):
		rule_sets = frappe.get_all("Exam Rule Set", {"regulation": ["in", [
			frappe.db.get_value("Student", s.name, "oc_regulation") for s in (self.s22, self.s26)]]}, pluck="name")  # fmt: skip
		for name in rule_sets:
			frappe.db.set_value("Exam Rule Set", name, "allow_course_teacher_as_examiner", 1)
		frappe.get_doc("User", FACULTY).add_roles("Examiner")
		bundle = self.bundle()
		employee = frappe.db.get_value("Employee", {"user_id": FACULTY})
		first = self.allocate(bundle, 1, None, examiner_type="Internal", employee=employee)
		for name in rule_sets:
			frappe.db.set_value("Exam Rule Set", name, "allow_course_teacher_as_examiner", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "teaches"):
			self.value(first, self.d22, 20, 20, FACULTY)


class TestMarkSheetScope(ValuationFixture):
	ACADEMICS = "exam-academics@example.com"
	DEAN = "exam-dean@example.com"

	def sheet(self, course):
		return frappe.db.get_value("Mark Sheet Entry", {"exam_session": self.session.name, "course_offering": self.offerings22[course]})

	def test_academics_users_and_instructors_read_only_their_offerings(self):
		make_login(self.ACADEMICS, "Academics User")
		make_login(self.DEAN, "Dean Academics")
		taught, other = self.sheet(COURSE), self.sheet("EXM LB")
		self.assertTrue(frappe.has_permission("Mark Sheet Entry", "read", doc=taught, user=FACULTY))
		self.assertFalse(frappe.has_permission("Mark Sheet Entry", "read", doc=other, user=FACULTY))
		self.assertFalse(frappe.has_permission("Mark Sheet Entry", "read", doc=taught, user=self.ACADEMICS))
		frappe.set_user(self.ACADEMICS)
		self.assertEqual(frappe.get_list("Mark Sheet Entry", pluck="name"), [])
		frappe.set_user(FACULTY)
		self.assertNotIn(other, frappe.get_list("Mark Sheet Entry", pluck="name"))
		frappe.set_user(self.DEAN)
		self.assertTrue({taught, other} <= set(frappe.get_list("Mark Sheet Entry", pluck="name")))
		self.assertTrue(frappe.has_permission("CIA Schedule", "read", user=self.ACADEMICS))  # only the sheets narrow


class TestFinalMarkLock(ValuationFixture):
	def test_a_valued_ese_cannot_be_overwritten_on_the_mark_sheet(self):
		self.valued_all()
		self.write_back()
		name = frappe.db.get_value("Mark Sheet Entry Row", {"student": self.s26.name, "parent": ["in", self.sheets()]}, "parent")
		sheet = frappe.get_doc("Mark Sheet Entry", name)
		next(r for r in sheet.marks if r.student == self.s26.name).ese = 55
		frappe.set_user(COE_USER)
		with self.assertRaisesRegex(frappe.ValidationError, "valuation"):
			sheet.save()

	def test_marks_lock_after_the_result_run(self):
		bundle = self.bundle([self.d22])
		first, second = self.allocate(bundle, 1, VAL1), self.allocate(bundle, 2, VAL2)
		self.value(first, self.d22, 20, 20, VAL1)
		self.run_session()
		with self.assertRaisesRegex(frappe.ValidationError, "locked"):
			self.value(second, self.d22, 20, 22, VAL2)


class TestBundles(ValuationFixture):
	def test_a_bundle_with_missing_scripts_cannot_be_marked_complete(self):  # AC3
		bundle = self.bundle([self.d22], expected=2)
		frappe.set_user(COE_USER)
		bundle.status = "Complete"
		with self.assertRaisesRegex(frappe.ValidationError, "missing"):
			bundle.save()
		bundle.reload()
		bundle.append("scripts", {"dummy_number": self.d26, "received": 0})
		bundle.status = "Complete"
		with self.assertRaisesRegex(frappe.ValidationError, "missing"):
			bundle.save()
		bundle.reload()
		bundle.append("scripts", {"dummy_number": self.d26, "received": 1})
		bundle.status = "Complete"
		bundle.save()
		self.assertEqual(bundle.status, "Complete")

	def test_scripts_must_be_dummy_numbers_of_the_course_and_in_one_bundle_only(self):
		with self.assertRaises(frappe.ValidationError):
			self.bundle(["99999999"])
		self.bundle([self.d22])
		with self.assertRaisesRegex(frappe.ValidationError, "another bundle"):
			self.bundle([self.d22])

	def test_movements_are_logged_with_the_user(self):
		bundle = self.bundle()
		frappe.set_user(COE_USER)
		bundle.append("movements", {"from_location": "Exam cell", "to_location": "Valuation camp"})
		bundle.save()
		self.assertEqual(bundle.movements[0].moved_by, COE_USER)
		self.assertTrue(bundle.movements[0].moved_on)
		bundle.movements[0].to_location = "Elsewhere"
		with self.assertRaisesRegex(frappe.ValidationError, "movement"):
			bundle.save()


class TestExaminerPortal(ValuationFixture):
	def test_the_portal_lists_only_the_examiners_allocated_scripts(self):
		from campus.www.campus_portal import valuation as page

		bundle = self.bundle()
		self.allocate(bundle, 1, VAL1)
		frappe.set_user(VAL1)
		context = frappe._dict()
		page.get_context(context)
		self.assertEqual([s.dummy_number for a in context.allocations for s in a.scripts], sorted([self.d22, self.d26]))
		frappe.set_user(VAL2)
		context = frappe._dict()
		page.get_context(context)
		self.assertEqual(context.allocations, [])

	def test_guests_are_sent_to_login(self):
		from campus.www.campus_portal import valuation as page

		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			page.get_context(frappe._dict())
		self.assertTrue(frappe.local.flags.redirect_location.startswith("/login"))


class TestWriteBack(ValuationFixture):
	def test_the_examiners_request_writes_no_mark_sheet_and_the_job_does(self):
		self.valued_all()
		self.assertEqual(self.sheet_ese(self.s26.name), (35, 0))
		self.assertNotIn(frappe.db.get_value("Mark Sheet Entry", self.sheet_of(self.s26.name), "modified_by"), (VAL1, VAL2))
		self.assertEqual(self.write_back(), 2)
		self.assertEqual((self.sheet_ese(self.s22.name), self.sheet_ese(self.s26.name)), ((43, 1), (44, 1)))
		self.assertEqual(frappe.db.get_value("Mark Sheet Entry", self.sheet_of(self.s26.name), "modified_by"), CONFIDENTIAL_USER)
		self.assertEqual(self.write_back(), 0)  # nothing left pending

	def test_an_unbundled_script_blocks_the_write_back(self):  # else the one written row names its student
		self.valued_d26()
		with self.assertRaisesRegex(frappe.ValidationError, "finalised"):
			self.write_back()
		self.assertEqual(self.sheet_ese(self.s26.name), (35, 0))

	def test_a_bundle_valued_in_round_1_only_blocks_the_write_back(self):
		bundle = self.bundle()
		first = self.allocate(bundle, 1, VAL1)
		for dummy in (self.d22, self.d26):
			self.value(first, dummy, 20, 20, VAL1)
		self.assertEqual(frappe.db.get_value("Valuation Allocation", first.name, "status"), "Completed")
		with self.assertRaisesRegex(frappe.ValidationError, "finalised"):
			self.write_back()

	def test_a_script_voided_after_bundling_does_not_block_completion(self):
		bundle = self.bundle()
		first, second = self.allocate(bundle, 1, VAL1), self.allocate(bundle, 2, VAL2)
		self.value(first, self.d22, 20, 20, VAL1)
		self.value(second, self.d22, 20, 26, VAL2)
		frappe.db.set_value("Seating Plan Seat", {"parent": self.plan.name, "student": self.s26.name}, "absent", 1)
		self.generate()  # d26 is void now
		statuses = frappe.get_all("Valuation Allocation", {"bundle": bundle.name}, pluck="status")
		self.assertEqual(statuses, ["Completed", "Completed"])
		self.assertEqual(self.write_back(), 1)
		self.assertEqual(self.sheet_ese(self.s22.name), (43, 1))
		frappe.set_user(COE_USER)
		bundle.reload()
		bundle.append("movements", {"from_location": "Camp", "to_location": "Exam cell"})
		bundle.save()  # a bundle holding a void script can still log its movements

	def test_the_write_back_waits_for_every_allocation_of_the_course(self):
		self.double_valued()  # d22 is on an Unassigned third valuation
		with self.assertRaisesRegex(frappe.ValidationError, "Completed"):
			self.write_back()
		self.assertEqual(self.sheet_ese(self.s26.name), (35, 0))

	def test_only_exam_confidential_runs_the_write_back_and_only_by_post(self):
		self.valued_all()
		for user in (COE_USER, VAL1, SYSTEM_MANAGER):
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				valuation_write_back.write_back_pending(self.session.name, COURSE)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[valuation_write_back.write_back_pending], ["POST"])

	def test_an_absent_mark_on_the_sheet_is_never_cleared(self):
		self.valued_all()
		row = frappe.db.get_value("Mark Sheet Entry Row", {"student": self.s26.name, "parent": self.sheet_of(self.s26.name)})
		frappe.db.set_value("Mark Sheet Entry Row", row, {"absent": 1, "ese": 0})
		self.assertEqual(self.write_back(), 2)  # both queued, d26 skipped
		self.assertEqual(frappe.db.get_value("Mark Sheet Entry Row", row, ["absent", "ese", "ese_from_valuation"]), (1, 0, 0))
		self.assertEqual(self.final_of(self.d26), (1, 44, 0))
		self.assertIn("absent", frappe.db.get_value(MAP, {"dummy_number": self.d26}, "write_back_issue"))

	def test_an_absent_seat_is_never_overwritten(self):
		self.valued_all()
		frappe.db.set_value("Seating Plan Seat", {"parent": self.plan.name, "student": self.s26.name}, "absent", 1)
		self.write_back()
		self.assertEqual(self.sheet_ese(self.s26.name), (35, 0))
		self.assertEqual(self.final_of(self.d26), (1, 44, 0))
		self.assertIn("absent", frappe.db.get_value(MAP, {"dummy_number": self.d26}, "write_back_issue"))

	def test_a_student_marked_absent_after_generation_loses_the_dummy_number(self):
		frappe.db.set_value("Seating Plan Seat", {"parent": self.plan.name, "student": self.s26.name}, "absent", 1)
		self.generate()
		self.assertEqual(frappe.db.get_value(MAP, {"dummy_number": self.d26}, "void"), 1)
		with self.assertRaisesRegex(frappe.ValidationError, "Not scripts"):
			self.bundle([self.d26])
		frappe.db.set_value("Seating Plan Seat", {"parent": self.plan.name, "student": self.s26.name}, "absent", 0)
		self.generate()
		self.assertEqual(frappe.db.get_value(MAP, {"dummy_number": self.d26}, "void"), 0)  # same number back

	def test_generation_redraws_a_number_taken_meanwhile(self):
		frappe.db.delete(MAP, {"dummy_number": self.d26})
		with patch.object(valuation_rules, "dummy_numbers", side_effect=[[self.d22], ["12345678"]]):
			self.assertEqual(self.generate(), 1)
		self.assertEqual(self.dummy_of(self.s26.name), "12345678")


class TestCourseTeacherAsExaminer(ValuationFixture):
	def rule_sets(self):
		regulations = {frappe.db.get_value("Student", s.name, "oc_regulation") for s in (self.s22, self.s26)}
		return frappe.get_all("Exam Rule Set", {"regulation": ["in", list(regulations)]}, pluck="name")

	def test_a_teacher_of_the_course_is_refused_unless_the_rule_allows(self):
		bundle = self.bundle()
		employee = frappe.db.get_value("Employee", {"user_id": FACULTY})
		with self.assertRaisesRegex(frappe.ValidationError, "teaches"):
			self.allocate(bundle, 1, None, examiner_type="Internal", employee=employee)
		for name in self.rule_sets():
			frappe.db.set_value("Exam Rule Set", name, "allow_course_teacher_as_examiner", 1)
		self.assertEqual(self.allocate(bundle, 1, None, examiner_type="Internal", employee=employee).examiner, FACULTY)

	def test_the_rule_is_a_record_field_off_by_default(self):
		self.assertEqual({frappe.db.get_value("Exam Rule Set", n, "allow_course_teacher_as_examiner") for n in self.rule_sets()}, {0})


class TestBundleFreeze(ValuationFixture):
	def test_expected_count_is_fixed_after_insert(self):
		bundle = self.bundle([self.d22], expected=2)
		frappe.set_user(COE_USER)
		bundle.expected_count = 1
		with self.assertRaisesRegex(frappe.ValidationError, "expected"):
			bundle.save()

	def test_an_incomplete_bundle_cannot_be_allocated(self):
		bundle = self.bundle([self.d22], expected=2)
		with self.assertRaisesRegex(frappe.ValidationError, "Complete"):
			self.allocate(bundle, 1, VAL1)

	def test_the_scripts_are_fixed_once_allocated(self):
		bundle = self.bundle()
		self.allocate(bundle, 1, VAL1)
		frappe.set_user(COE_USER)
		bundle.reload()
		bundle.scripts[0].received = 0
		bundle.status = "Open"
		with self.assertRaisesRegex(frappe.ValidationError, "allocated"):
			bundle.save()
		bundle.reload()
		bundle.remove(bundle.scripts[1])
		with self.assertRaisesRegex(frappe.ValidationError, "allocated"):
			bundle.save()

	def test_the_movement_log_resaves_from_its_string_form(self):
		bundle = self.bundle()
		frappe.set_user(COE_USER)
		bundle.append("movements", {"from_location": "Exam cell", "to_location": "Camp"})
		bundle.save()
		posted = frappe.get_doc(frappe.parse_json(frappe.as_json(bundle.as_dict())))  # what a desk save sends back
		posted.movements[0].handed_to = ""
		posted.append("movements", {"from_location": "Camp", "to_location": "Exam cell"})
		posted.save()
		self.assertEqual(len(posted.movements), 2)


class TestEntryOncePerRound(ValuationFixture):
	def test_a_second_draft_entry_for_the_round_is_refused(self):
		bundle = self.bundle()
		first = self.allocate(bundle, 1, VAL1)
		frappe.set_user(VAL1)
		entry = {"doctype": "Valuation Entry", "allocation": first.name, "dummy_number": self.d22,
			"marks": [{"question": "Q1", "marks": 10}, {"question": "Q2", "marks": 10}]}  # fmt: skip
		frappe.get_doc(entry).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			frappe.get_doc(entry).insert()


class TestPortalRoute(ValuationFixture):
	def test_the_valuation_route_renders_the_examiners_scripts(self):
		from frappe.website.serve import get_response

		bundle = self.bundle()
		self.allocate(bundle, 1, VAL1)
		frappe.set_user(VAL1)
		request_as("10.0.0.31", "/campus-portal/valuation")
		self.addCleanup(setattr, frappe.local, "request", None)
		frappe.local.form_dict = frappe._dict()
		frappe.local.response = frappe._dict()
		response = get_response("campus-portal/valuation")
		body = response.get_data(as_text=True)
		self.assertEqual(response.status_code, 200)
		self.assertIn(self.d22, body)
		self.assertIn("campus.examinations.valuation.submit_marks", body)
		for student in (self.s22, self.s26):
			self.assertNotIn(student.name, body)
			self.assertNotIn(student.student_name, body)
