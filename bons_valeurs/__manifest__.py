# -*- coding: utf-8 -*-
{
    'name': "Star Oil Group - Bons Valeurs",

    'summary': """
        Mise en Place des bons valeurs.
        """,

    'description': """
        Long description of module's purpose
    """,

    'author': "Star Oil Group",
    'website': "http://www.staroilgroup.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['smp_sale'],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'data/receipt_sequence.xml',

        'security/security.xml',
        'security/ir.model.access.csv',

        'views/coupon_value.xml',
        'views/sale_order.xml',
        'views/coupon_printing_order.xml',
        'views/coupon_delivery_order.xml',
        'views/coupon_return_order.xml',

        "report/coupon_template.xml",
        "report/page_format.xml",

    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}