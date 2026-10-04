"""Install and migrate hooks for OneBook Campus."""

from campus.campus_messaging.setup import setup_messaging
from campus.campus_platform.company_scope import setup_company_fields
from campus.campus_platform.module_packs import seed_module_packs
from campus.campus_platform.positions import ensure_seed_positions
from campus.campus_platform.regulation_setup import ensure_dean_role, setup_regulation_fields
from campus.campus_platform.verification import ensure_verification_role


def before_install():
	ensure_dean_role()  # regulation.json permissions reference it during DocType sync
	ensure_verification_role()  # verifiable_document.json likewise


def after_install():
	ensure_dean_role()
	ensure_verification_role()
	setup_company_fields()
	setup_regulation_fields()
	seed_module_packs()
	ensure_seed_positions()
	setup_messaging()


def after_migrate():
	ensure_dean_role()
	ensure_verification_role()
	setup_company_fields()
	setup_regulation_fields()
	seed_module_packs()
	ensure_seed_positions()
	setup_messaging()
