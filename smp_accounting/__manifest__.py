# -*- coding: utf-8 -*-

{
    'name': 'Account Fiscal Extention',
    'version': '12.0.1.0.0',
    'category': 'Accounting',
    'author': 'Disruptsol',
    'summary': 'Account Fiscal Features Extension',
    'depends': ['account', 'report_xlsx', 'account_parent', 'web'],
    'data': [
        'views/account_fiscal_year_view.xml',
        'views/account_account_view.xml',
        'views/account_move_line_view.xml',

        'wizard/accounting_report_wizard_view.xml',

        'report/report_smp_accounting.xml',

        'security/ir.model.access.csv',
    ],
    'demo': [],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'price': 0.0,
    'currency': 'EUR',
    # 'images': ['images/main_screenshot.png'],
}
