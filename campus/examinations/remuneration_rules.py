"""M06-04 Examiner remuneration rules (pure): the rate version in force, line amounts, the next payroll date and the
Purchase Invoice lines by service Item."""

from frappe.utils import add_days, flt, getdate


class MissingItem(Exception):
	def __init__(self, activity):
		super().__init__(activity)
		self.activity = activity


def rate_on(rates, on_date):
	"""The rate record (dict with from_date) in force on `on_date`: the latest from_date on or before it; None if none."""
	on_date = getdate(on_date)
	in_force = [r for r in rates if getdate(r["from_date"]) <= on_date]
	return max(in_force, key=lambda r: getdate(r["from_date"])) if in_force else None


def line_amount(quantity, rate):
	return flt(flt(quantity) * flt(rate), 2)


def next_payroll_date(posting_date, last_slip_end):
	"""The claim's date, or the day after the employee's last processed slip if that is later."""
	posting_date = getdate(posting_date)
	if not last_slip_end:
		return posting_date
	return max(posting_date, getdate(add_days(last_slip_end, 1)))


def amount_by_item(lines):
	"""{item: total} in first-seen order (ERPNext refuses a repeated Item); MissingItem names a line without one."""
	totals = {}
	for line in lines:
		if not line.get("item"):
			raise MissingItem(line.get("activity"))
		item = line.get("item")
		totals[item] = flt(totals.get(item, 0) + flt(line.get("amount")), 2)
	return totals
