# -*- coding: utf-8 -*-
{
    'name': "smp_regime_douanier",

    'summary': """
        Mise en place des fonctionnalité suivantes:
            * Rajouts des régimes douanier de vente
            """,

    'description': """
        Mise en place des fonctionnalités de frais de ventes et d'achats en fonction du produit, dépôt et régime.
    """,

    'author': "DisruptSol",
    # 'website': "http://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'sale',
    'version': '0.1',

    # any module necessary for this one to work correctly
    # 'depends': ['stock_account', 'sale_management', 'product', 'stock'],
    'depends': ['sale','stock'],

    # always loaded
    'data': [

        "data/regime.douanier.csv",

        'security/ir.model.access.csv',

        'views/regime_douanier.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}