# -*- coding: utf-8 -*-
{
    'name': "smp_sale",

    'summary': """
        Mise en place des fonctionnalité suivantes:
            * Rajouts des frais de ventes et d'achats.
            * Rajouts des régimes douanier de vente et d'achats
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
    'depends': ['base_setup', 'smp_regime_douanier','sale','sale_management', 'product', 'smp_inventory'],

    # always loaded
    'data': [
        "data/inventory_parameter.xml",
        "data/ir_sequence_data.xml",

        'security/security.xml',
        'security/ir.model.access.csv',

        'views/account_invoice_view.xml',
        'views/pricelist.xml',
        'views/product_sale_price.xml',
        'views/product_views.xml',
        'views/res_partner.xml',
        'views/sale_dma.xml',
        'views/sale_order.xml',
        'views/stock_picking.xml',
        # 'views/stock_rule_views.xml',
        'views/stock_view.xml',
        'views/transport.xml',

    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}