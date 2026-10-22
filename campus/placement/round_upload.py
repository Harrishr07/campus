"""M14-02 Bulk Round Result upload and its template download."""

import frappe
from frappe import _

from campus.placement import export
from campus.placement.api import registered_students


@frappe.whitelist(methods=["POST"])
def load_results(round_result):
	"""Merge the rows of the attached results file into the Round Result (a student already listed is updated).
	Every problem in the file is reported at once with its row number and nothing is saved."""
	doc = frappe.get_doc("Round Result", round_result)
	doc.check_permission("write")
	if not doc.upload_file:
		frappe.throw(_("Attach the results file first."))
	rows = export.read_rows(doc.upload_file)
	problems = file_problems(rows, set(registered_students(doc.drive)))
	if problems:
		frappe.throw("<br>".join(problems[:20]) + ("<br>" + _("... and {0} more").format(len(problems) - 20) if len(problems) > 20 else ""))
	listed = {row.student: row for row in doc.results}
	for _number, student, result, remarks in rows:
		if student in listed:
			listed[student].result, listed[student].remarks = result, remarks
		else:
			doc.append("results", {"student": student, "result": result, "remarks": remarks})
	doc.save()
	return len(rows)


def file_problems(rows, registered):
	"""Messages for rows whose student is not registered, whose result is unknown or whose student repeats."""
	problems, seen = [], set()
	for number, student, result, _remarks in rows:
		if student not in registered:
			problems.append(_("Row {0}: {1} is not registered for the drive").format(number, frappe.utils.escape_html(student)))
		elif student in seen:
			problems.append(_("Row {0}: {1} is listed twice").format(number, student))
		if result not in export.RESULTS:
			problems.append(_("Row {0}: result {1} is not one of {2}").format(number, frappe.utils.escape_html(result), ", ".join(export.RESULTS)))
		seen.add(student)
	return problems


@frappe.whitelist()
def download_template(round_result):
	"""CSV of the drive's registered students with the round's current results, for filling in and loading back."""
	frappe.has_permission("Round Result", "read", round_result, throw=True)
	frappe.response["result"] = export.template_rows(round_result)
	frappe.response["doctype"] = round_result
	frappe.response["type"] = "csv"
