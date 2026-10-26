"""M06-04 Answer Script Bundle: a packet of answer scripts of one course, listed by dummy number, with the
question pattern its examiners mark against and a movement log.

Every script must be a dummy number of the course in the session and sit in one bundle only; the check runs
on the server against the confidential map and names dummy numbers only. A bundle is Complete only when the
expected number of scripts is received. The expected count is fixed once saved, and the scripts (and the
Complete status) once the bundle is allocated. Logged movements are never changed; the question pattern is
fixed once valuation starts.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, flt, get_datetime, now_datetime

from campus.examinations import dummy_numbers, valuation_rules


class AnswerScriptBundle(Document):
	def validate(self):
		if cint(self.expected_count) <= 0:
			frappe.throw(_("Enter the expected number of scripts."))
		self.check_frozen()
		self.validate_scripts()
		self.validate_questions()
		self.log_movements()
		if self.status == "Complete":
			missing = valuation_rules.missing_scripts(self.expected_count, [s.received for s in self.scripts])
			if missing:
				frappe.throw(
					_("{0} of {1} scripts are missing: the bundle cannot be complete.").format(
						missing, self.expected_count
					)
				)

	def check_frozen(self):
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if cint(self.expected_count) != cint(before.expected_count):
			frappe.throw(_("The expected number of scripts is fixed once the bundle is saved."))
		if frappe.db.exists("Valuation Allocation", {"bundle": self.name}) and (
			script_list(self) != script_list(before) or self.status != before.status
		):
			frappe.throw(_("The scripts of an allocated bundle are fixed."))

	def validate_scripts(self):
		numbers = [s.dummy_number for s in self.scripts]
		if len(numbers) != len(set(numbers)):
			frappe.throw(_("A script is listed twice."))
		if len(numbers) > cint(self.expected_count):
			frappe.throw(_("The bundle lists more scripts than expected."))
		kept = set() if self.is_new() else {s.dummy_number for s in self.get_doc_before_save().scripts}
		unknown = (
			set(numbers) - kept - set(dummy_numbers.numbers_of(self.exam_session, self.course))
		)  # kept may be void now
		if unknown:
			frappe.throw(
				_("Not scripts of this course in this session: {0}").format(", ".join(sorted(unknown)))
			)
		elsewhere = frappe.get_all(
			"Answer Script Bundle Script",
			{
				"parenttype": self.doctype,
				"dummy_number": ["in", numbers or [""]],
				"parent": ["!=", self.name],
			},
			pluck="dummy_number",
		)
		if elsewhere:
			frappe.throw(_("Already in another bundle: {0}").format(", ".join(sorted(elsewhere))))

	def validate_questions(self):
		names = [q.question for q in self.questions]
		if len(names) != len(set(names)) or any(flt(q.max_marks) <= 0 for q in self.questions):
			frappe.throw(_("Each question appears once, with a positive maximum."))
		if self.is_new() or not frappe.db.exists(
			"Valuation Entry", {"bundle": self.name, "docstatus": ["<", 2]}
		):
			return
		before = [(q.question, flt(q.max_marks)) for q in self.get_doc_before_save().questions]
		if [(q.question, flt(q.max_marks)) for q in self.questions] != before:
			frappe.throw(_("The question pattern is fixed once valuation has started."))

	def log_movements(self):
		before = {} if self.is_new() else {m.name: m for m in self.get_doc_before_save().movements}
		kept = {m.name for m in self.movements if m.name in before}
		if kept != set(before) or any(
			movement_key(m) != movement_key(before[m.name]) for m in self.movements if m.name in before
		):
			frappe.throw(_("A logged movement cannot be changed or removed."))
		for movement in self.movements:
			if movement.name not in before:
				movement.moved_on, movement.moved_by = now_datetime(), frappe.session.user


def script_list(doc):
	return [(s.dummy_number, cint(s.received)) for s in doc.scripts]


def movement_key(movement):
	"""A movement as stored, whatever types a client posted it with (datetime or string, None or "")."""
	moved_on = movement.moved_on and get_datetime(movement.moved_on).replace(microsecond=0)
	return (
		moved_on,
		*(
			cstr(movement.get(f))
			for f in ("from_location", "to_location", "handed_to", "moved_by", "remarks")
		),
	)
