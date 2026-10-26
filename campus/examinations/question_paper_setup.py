"""M06-03 Question paper setup (after_install / after_migrate): the dedicated file key, the default settings, the
seed moderation policy (Exam Confidential of the paper's college; the setter and requester never approve), and the
removal of Version rows that would copy confidential fields into a table System Managers read."""

import os

import frappe
from cryptography.fernet import Fernet
from frappe.installer import update_site_config

from campus.examinations.question_paper_files import (
	KEY_CONFIG,
	KEY_ENV,
	KEY_FILE_CONFIG,
	QUESTION_PAPER,
	SEALED_SUFFIX,
	key,
)

SETTINGS = "Question Paper Settings"
DEFAULT_SETTINGS = {
	"download_lead_minutes": 30,
	"slot_minutes": 180,
	"forenoon_starts_at": "10:00:00",
	"afternoon_starts_at": "14:00:00",
}
MODERATION_POLICY = "Question Paper Moderation"
UNVERSIONED = ("Question Bank Item", "Question Paper", "QP Setter Nomination")


def setup_question_papers():
	ensure_key()
	seed_settings()
	seed_approval_policy()
	drop_confidential_versions()


def ensure_key():
	"""True when a question paper key is configured. A missing key is generated into site_config only while no
	sealed file exists: a new key would make every sealed paper unreadable, so then it is refused, loudly."""
	if key():
		if not frappe.conf.get(KEY_FILE_CONFIG) and not os.environ.get(KEY_ENV):
			print(f"campus: the question paper key is in site_config ({KEY_CONFIG}), so site backups carry it. "
				f"Move it to the {KEY_ENV} environment variable or a file outside sites/ named by {KEY_FILE_CONFIG}.")  # fmt: skip
		return True
	if frappe.db.exists(
		"File", {"attached_to_doctype": QUESTION_PAPER, "file_url": ["like", f"%{SEALED_SUFFIX}"]}
	):
		print(f"campus: no question paper key is configured but sealed papers exist; NOT generating a new key. "
			f"Restore the key ({KEY_ENV}, {KEY_FILE_CONFIG} or {KEY_CONFIG}).")  # fmt: skip
		return False
	value = Fernet.generate_key().decode()
	update_site_config(KEY_CONFIG, value)
	frappe.conf[KEY_CONFIG] = value
	return True


def seed_settings():
	"""Fill each empty setting with its default (a fresh site has none)."""
	current = frappe.db.get_singles_dict(SETTINGS)
	missing = {field: value for field, value in DEFAULT_SETTINGS.items() if current.get(field) in (None, "")}
	if missing:
		frappe.db.set_single_value(SETTINGS, missing)


def seed_approval_policy():
	if frappe.db.exists("Approval Policy", {"document_type": "Question Paper"}):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": MODERATION_POLICY, "document_type": "Question Paper", "enabled": 1,
			"levels": [{"title": "Moderator", "approver_type": "Role", "approver": "Exam Confidential", "limit_to_company": 1,
				"min_approvals": 1, "sla_hours": 48}],
		}
	).insert(ignore_permissions=True)  # fmt: skip


def drop_confidential_versions():
	frappe.db.delete("Version", {"ref_doctype": ["in", UNVERSIONED]})
