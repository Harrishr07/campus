"""Install and migrate hooks for OneBook Campus."""

from campus.campus_platform.company_scope import setup_company_fields
from campus.campus_platform.regulation_setup import ensure_dean_role, setup_regulation_fields
from campus.campus_platform.module_packs import seed_module_packs


def after_install():
	ensure_dean_role()
	setup_company_fields()
	setup_regulation_fields()
	seed_module_packs()


def after_migrate():
	ensure_dean_role()
	setup_company_fields()
	setup_regulation_fields()
	seed_module_packs()
