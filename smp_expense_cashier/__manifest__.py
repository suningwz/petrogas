# -*- coding: utf-8 -*-
{
    'name': "smp_expense_cashier",

    'summary': """
        Gestion des caisses et des dépenses""",

    'description': """
        Mise en place de la gestion des caisses et de dépenses.
    """,

    'author': "Disruptsol",
    'website': "http://www.disruptsol.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Accounting',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base','hr_expense', 'account_payment_group'],

    # always loaded
    'data': [
        'data/ir_sequence_data.xml',
        # 'security/ir.model.access.csv',
        'views/hr_expense.xml',
        'views/account_bank_invoice.xml',

        "report/cash_bank_statement_report.xml"
        # 'views/templates.xml',
    ],


    'installable': True,
    'application': False,
    'auto_install': False,
}