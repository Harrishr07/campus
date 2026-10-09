"""M06-04 Valuation Entry: one examiner's question-wise marks for one script (dummy number) in one round.

Only the allocation's examiner enters it, for a script of that allocation, once per round. The question
pattern and maxima come from the bundle. On submit campus.examinations.valuation decides the third valuation
or the final mark. It carries no student field: the dummy-to-student join stays on the server.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from campus.examinations import valuation


class ValuationEntry(Document):
	def validate(self):
		alloc = frappe.get_doc(valuation.ALLOCATION, self.allocation)
		if not alloc.examiner or alloc.examiner != frappe.session.user:
			raise frappe.PermissionError(_("Only the allocated examiner enters these marks."))
		self.update({f: alloc.get(f) for f in ("valuation_round", "exam_session", "course", "bundle", "examiner")})
		alloc.check_course_teacher()  # the rule or the teaching may have changed since the allocation
		if self.dummy_number not in {s.dummy_number for s in alloc.scripts}:
			frappe.throw(_("Script {0} is not in this allocation.").format(self.dummy_number))
		script = valuation.lock_script(self)  # the round and result-lock checks below run one at a time per script
		self.check_once_per_round()
		self.validate_marks()
		valuation.check_script(self, script)

	def check_once_per_round(self):
		filters = {"dummy_number": self.dummy_number, "valuation_round": self.valuation_round, "docstatus": ["<", 2]}
		if any(n != self.name for n in frappe.qb.get_query(self.doctype, filters=filters, fields=["name"], for_update=True).run(pluck=True)):
			frappe.throw(_("Script {0} is already valued in round {1}.").format(self.dummy_number, self.valuation_round))

	def validate_marks(self):
		pattern = {q.question: flt(q.max_marks) for q in valuation.bundle_questions(self.bundle)}
		if not self.marks or [r.question for r in self.marks] != list(pattern):
			frappe.throw(_("Enter marks for each question of the bundle: {0}.").format(", ".join(pattern)))
		for row in self.marks:
			row.max_marks = pattern[row.question]
			if not 0 <= flt(row.marks) <= row.max_marks:
				frappe.throw(_("{0}: marks lie within 0-{1}.").format(row.question, row.max_marks))
		self.total = sum(flt(r.marks) for r in self.marks)

	def on_submit(self):
		valuation.after_valuation(self)

	def before_cancel(self):
		frappe.throw(_("A submitted valuation cannot be cancelled."))
