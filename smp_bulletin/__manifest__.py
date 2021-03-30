# -*- coding: utf-8 -*-
{
    'name': "smp_bulletin",

    'summary': """
        Permet l'audit et la régularisation des charges logistique.
    """,

    'description': """
        Permet l'audit et la régularisation des charges logistique.
    """,

    'author': "Disruptsol",
    'website': "http://www.disruptsol.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Accounting',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['multi_step_wizard', 'smp_inventory'],

    # always loaded
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',

        'data/ir_sequence_data.xml',
        'data/bulletin.xml',

        'views/charge_rule.xml',
        'views/bulletin.xml',
        'views/charge_rule_category.xml',
        'views/stock_move_charges.xml',
        # 'views/templates.xml',
        'report/bulletin_report.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        # 'demo/demo.xml',
    ],

    'installable': True,
    'application': True,
    'auto_install': False,
}