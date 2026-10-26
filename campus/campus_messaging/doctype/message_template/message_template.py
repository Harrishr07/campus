"""M16-01 Message Template: one event key, its channels and per-language bodies.

Authoring is System Manager-only by design: templates render in a background context with the full
referenced document available, so whoever writes one can read any field of that document.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from jinja2 import Environment, TemplateSyntaxError


class MessageTemplate(Document):
	def validate(self):
		channels = [row.channel for row in self.channels]
		if len(set(channels)) != len(channels):
			frappe.throw(_("Each channel can be listed only once."))
		languages = [row.language for row in self.bodies]
		if "en" not in languages:
			frappe.throw(_("An English (en) body is required as the fallback language."))
		if len(set(languages)) != len(languages):
			frappe.throw(_("Each language can have only one body."))
		self.validate_jinja()

	def validate_jinja(self):
		sources = [(_("Body ({0})").format(r.language), r.body) for r in self.bodies]
		sources += [(_("Subject ({0})").format(r.language), r.subject) for r in self.bodies if r.subject]
		sources += [
			(_("Variable"), "{{ " + v.strip() + " }}")
			for v in (self.variables or "").splitlines()
			if v.strip()
		]
		env = Environment()
		for label, source in sources:
			try:
				env.parse(source)
			except TemplateSyntaxError as e:
				frappe.throw(_("{0} has a template error: {1}").format(label, e.message))
