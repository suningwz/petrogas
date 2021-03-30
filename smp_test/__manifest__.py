# -*- coding: utf-8 -*-

{
    'name': "smp_test",

    'summary': """
        Test
            """,

    'description': """
        Importation des données initiaux pour  SMP
        """,

    'author': "DisruptSol",
    # 'website': "http://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'tools',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['modules_trigger'],

    # always loaded
    'data': [
        # "data/inventory_parameter.xml",

    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
