# -*- coding: utf-8 -*-

{
    'name': "smp_hr_payroll",

    'summary': """
        Mise en place des fonctionnalités de paies
            """,

    'description': """
        Mise en place des fonctionnalités de paies
        """,

    'author': "DisruptSol",
    # 'website': "http://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'hr',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['hr_payroll', 'hr_payroll_account'],

    # always loaded
    'data': [

        'security/ir.model.access.csv',
        # 'security/security.xml',

        # 'data/res.users.csv',
        # 'data/hr.department.csv',
        # 'data/hr.job.csv',
        # 'data/hr.employee.csv',
        'data/hr_loan_seq.xml',

        'views/hr_job.xml',
        'views/hr_salay_rule.xml',
        'views/hr_employee.xml',
        'views/salary_advance.xml',
        'views/hr_loan.xml',
        'views/hr_loan_type.xml',
        'views/account_payment_group.xml',
        'views/hr_contract.xml',
        'views/hr_payslip.xml',

        'wizard/res_config.xml',
        'wizard/payslip_report_view.xml',

        'report/salary_advance_report.xml',
        'report/loan_report.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
