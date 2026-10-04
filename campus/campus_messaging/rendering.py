"""M16-01 Template rendering: Jinja with {doc, context, recipient}; language variant with en fallback."""

import frappe

DEFAULT_LANGUAGE = "en"


def pick_body(template, language):
	"""The body row for `language`, else the English one, else the first row."""
	by_language = {row.language: row for row in template.bodies}
	return by_language.get(language) or by_language.get(DEFAULT_LANGUAGE) or template.bodies[0]


def render(template, language, doc, context, recipient):
	"""Return (subject, message, whatsapp_variables) for one recipient."""
	row = pick_body(template, language)
	args = {"doc": doc, "context": context or {}, "recipient": recipient}
	subject = frappe.render_template(row.subject or "", args)
	message = frappe.render_template(row.body, args)
	variables = [
		frappe.render_template("{{ " + line.strip() + " }}", args)
		for line in (template.variables or "").splitlines()
		if line.strip()
	]
	return subject, message, variables
