# -*- coding: utf-8 -*-

{
    'name': "Petrogas Production Data",

    'summary': """
        Import Petrogas Production Data: 
            * Product Category
            * Product
            * Product
            """,

    'description': """
        Import Petrogas Production Data
        """,

    'author': "Petrogas",
    # 'website': "http://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'tools',
    'version': '0.1',

    # any module necessary for this one to work correctly
    # 'depends': ['smp_inventory','smp_sale', 'account'],
    'depends': [],

    # always loaded
    'data': [
        "data/account.journal.csv",
        "data/uom.uom.csv",
        "data/product.category.csv",
        "data/product.product.csv",
        "data/res.partner.category.csv",
        "data/res.partner.csv",
        "data/res.city.csv",
        "data/supplier/res.partner.csv",
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
