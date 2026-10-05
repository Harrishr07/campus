"""Install and migrate hooks for OneBook Campus."""

from campus.admissions.setup import ensure_aadhaar_role, setup_admissions
from campus.campus_finance.setup import setup_finance
from campus.campus_messaging.setup import setup_messaging
from campus.campus_platform.company_scope import setup_company_fields
from campus.campus_platform.module_packs import seed_module_packs
from campus.campus_platform.positions import ensure_seed_positions
from campus.campus_platform.regulation_setup import ensure_dean_role, setup_regulation_fields
from campus.campus_platform.verification import ensure_verification_role
from campus.curriculum.setup import setup_curriculum


def before_install():
	ensure_dean_role()  # regulation.json permissions reference it during DocType sync
	ensure_verification_role()  # verifiable_document.json likewise
	ensure_aadhaar_role()  # aadhaar_access_log.json likewise


def after_install():
	ensure_dean_role()
	ensure_verification_role()
	setup_company_fields()
	setup_regulation_fields()
	setup_curriculum()
	setup_admissions()
	seed_module_packs()
	ensure_seed_positions()
	setup_messaging()
	setup_finance()


def after_migrate():
	ensure_dean_role()
	ensure_verification_role()
	setup_company_fields()
	setup_regulation_fields()
	setup_curriculum()
	setup_admissions()
	seed_module_packs()
	ensure_seed_positions()
	setup_messaging()
	setup_finance()
