"""Install and migrate hooks for OneBook Campus."""

from campus.campus_platform.company_scope import setup_company_fields
from campus.campus_platform.module_packs import seed_module_packs


def after_install():
	setup_company_fields()
	seed_module_packs()


def after_migrate():
	setup_company_fields()
	seed_module_packs()
