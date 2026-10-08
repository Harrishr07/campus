"""M06-04 integration tests: dummy numbers, answer script bundles, double valuation, third valuation and the
final ESE mark written back to the Mark Sheet Entry. Examiners never reach a register number or a name."""

from unittest.mock import patch

import frappe
from frappe.desk import reportview
from frappe.desk.search import search_link

from campus.examinations import dummy_numbers, valuation
from campus.tests.test_exam_seating import make_room
from campus.tests.test_results import COE_USER, ExamFixture, make_login

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
		self.seat([(self.s22.name, 0), (self.s26.name, 0), (self.s_ab.name, 1)])
		frappe.set_user(CONFIDENTIAL_USER)
		self.generated = dummy_numbers.generate(self.session.name, COURSE)
		frappe.set_user("Administrator")
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

	def dummy_of(self, student):
		return frappe.db.get_value(MAP, {"exam_session": self.session.name, "student": student}, "dummy_number")

	def bundle(self, dummies=None, expected=None, received=1):
		dummies = dummies or [self.d22, self.d26]
		frappe.set_user(COE_USER)
		doc = frappe.get_doc(
			{
				"doctype": "Answer Script Bundle", "exam_session": self.session.name, "course": COURSE, "packet_no": "P1",
				"expected_count": expected or len(dummies),
				"scripts": [{"dummy_number": d, "received": received} for d in dummies],
				"questions": [{"question": "Q1", "max_marks": 30}, {"question": "Q2", "max_marks": 30}],
			}
		).insert()  # fmt: skip
		frappe.set_user("Administrator")
		return doc

	def allocate(self, bundle, valuation_round, examiner):
		frappe.set_user(COE_USER)
		doc = frappe.get_doc(
			{
				"doctype": "Valuation Allocation", "bundle": bundle.name, "valuation_round": str(valuation_round),
				"examiner_type": "External", "examiner": examiner, "deadline": "2022-12-20",
			}
		).insert()  # fmt: skip
		frappe.set_user("Administrator")
		return doc

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
		self.assertEqual(self.sheet_ese(self.s26.name), (44, 1))  # (40 + 48) / 2

	def test_the_third_valuation_settles_the_mark_by_the_closest_two(self):
		bundle = self.double_valued()
		third = self.round3(bundle)
		frappe.set_user(COE_USER)
		third.examiner = VAL3
		third.save()
		self.value(third, self.d22, 20, 27, VAL3)  # 47: (50 + 47) / 2 = 48.5 -> 49
		self.assertEqual(self.sheet_ese(self.s22.name), (49, 1))
		self.assertEqual(frappe.db.get_value(MAP, {"dummy_number": self.d22}, "final_ese"), 49)

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
		self.assertEqual(self.sheet_ese(self.s22.name), (45, 1))

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


class TestFinalMarkLock(ValuationFixture):
	def test_a_valued_ese_cannot_be_overwritten_on_the_mark_sheet(self):
		self.double_valued()
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
