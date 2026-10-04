"""Install and migrate hooks for OneBook Campus."""

from campus.campus_platform.company_scope import setup_company_fields


def after_install():
	setup_company_fields()


def after_migrate():
	setup_company_fields()
