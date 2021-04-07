# -*- coding: utf-8 -*-

{
    'name' : 'Gambian - IAS / IFRS Accounting For Petrogas',
    'author' : 'Star Oil Group',
    'category': 'Localization',
    'description': """
This module implements the accounting chart for gambian area.
===========================================================
    
It allows any company or association to manage its financial accounting.

Countries that use this accounting chart is the following:
-------------------------------------------
    Gambia .
    """,
    'depends': ['smp_accounting',
    ],
    'data': [
        'data/account_data.xml',
        'data/l10n_gambian_chart_data.xml',
        'data/account.account.template.csv',
        'data/account_tax_template_data.xml',
        'data/account_chart_template_data.xml',
    ],
}
