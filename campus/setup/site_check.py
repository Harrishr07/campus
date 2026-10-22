"""PR-05 Site checklist: reports whether a site is fit to run a college, one line per item.

    bench --site <site> execute campus.setup.site_check.run                      # production profile
    bench --site <site> execute campus.setup.site_check.run --kwargs '{"profile": "development"}'

Items marked FAIL stop a production go-live; WARN items are reported only. The production profile exits non-zero
when any item fails; the development profile never does (it reports the same lines). Reads only: nothing is
changed. See docs/usage/production-checklist.md.
"""

import os
import sys
import time

import frappe
from frappe.utils import add_to_date, now_datetime

OK, WARN, FAIL = "OK", "WARN", "FAIL"
BACKUP_MAX_AGE_DAYS = 2
ERROR_LOG_LIMIT = 10  # Error Log rows in the last day above which the site is not healthy


def run(profile="production"):
	"""Print the checklist; in the production profile exit 1 when an item fails. Returns [(item, status, detail)]."""
	results = [(name, *check()) for name, check in CHECKS]
	for name, status, detail in results:
		print(f"{status:5} {name}: {detail}")
	failed = [name for name, status, _detail in results if status == FAIL]
	if failed and profile == "production":
		print(f"{len(failed)} item(s) failing: {', '.join(failed)}")
		sys.exit(1)
	return results


def flag(ok, detail, bad=FAIL):
	return (OK if ok else bad), detail


def check_developer_mode():
	return flag(not frappe.conf.developer_mode, "developer_mode is " + ("on" if frappe.conf.developer_mode else "off"))


def check_allow_tests():
	return flag(not frappe.conf.allow_tests, "allow_tests is " + ("on" if frappe.conf.allow_tests else "off"))


def check_telemetry():
	enabled = frappe.get_system_settings("enable_telemetry")
	return flag(not enabled, "telemetry is " + ("on" if enabled else "off"), bad=WARN)


def check_request_recorder():
	from frappe.recorder import RECORDER_INTERCEPT_FLAG

	recording = bool(frappe.cache.get_value(RECORDER_INTERCEPT_FLAG))
	return flag(not recording, "request recorder is " + ("recording" if recording else "off"))


def check_scheduler():
	from frappe.utils.scheduler import is_scheduler_inactive

	inactive = is_scheduler_inactive(verbose=False)
	return flag(not inactive, "scheduler is " + ("inactive" if inactive else "enabled"))


def check_email_account():
	accounts = frappe.get_all("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, pluck="name")
	return flag(bool(accounts), f"default outgoing account: {accounts[0]}" if accounts else "no default outgoing Email Account")


def check_whatsapp():
	account = frappe.db.get_single_value("WhatsApp Settings", "default_outgoing_account")
	active = bool(account) and frappe.db.get_value("WhatsApp Account", account, "status") == "Active"
	return flag(active, f"default outgoing WhatsApp Account: {account}" if active else "no active default outgoing WhatsApp Account")


def check_backups():
	"""Backups are encrypted and kept (backup_limit); site_config carries the encryption_key a restore needs."""
	problems = []
	if not frappe.get_system_settings("encrypt_backup"):
		problems.append("backups are not encrypted")
	if not frappe.get_system_settings("backup_limit"):
		problems.append("backup_limit is 0")
	if not frappe.conf.get("encryption_key"):
		problems.append("no encryption_key in site_config (passwords cannot be restored)")
	return flag(not problems, "; ".join(problems) or "encrypted, limited, encryption_key present")


def check_backup_age():
	folder = frappe.utils.get_site_path(frappe.conf.get("backup_path", "private/backups"))
	files = [os.path.getmtime(os.path.join(folder, f)) for f in os.listdir(folder)] if os.path.isdir(folder) else []
	if not files:
		return WARN, "no backup file found"
	age_days = (time.time() - max(files)) / 86400
	return flag(age_days <= BACKUP_MAX_AGE_DAYS, f"latest backup {age_days:.1f} days old", bad=WARN)


def check_error_log():
	count = frappe.db.count("Error Log", {"creation": [">", add_to_date(now_datetime(), days=-1)]})
	return flag(count <= ERROR_LOG_LIMIT, f"{count} Error Log rows in the last day (limit {ERROR_LOG_LIMIT})")


def check_mail_queue():
	count = frappe.db.count("Email Queue", {"status": "Error", "modified": [">", add_to_date(now_datetime(), days=-1)]})
	return flag(count == 0, f"{count} outgoing mails in Error in the last day")


CHECKS = (
	("developer_mode", check_developer_mode),
	("allow_tests", check_allow_tests),
	("telemetry", check_telemetry),
	("request_recorder", check_request_recorder),
	("scheduler", check_scheduler),
	("email_account", check_email_account),
	("whatsapp", check_whatsapp),
	("backups", check_backups),
	("backup_age", check_backup_age),
	("error_log", check_error_log),
	("mail_queue", check_mail_queue),
)  # fmt: skip
