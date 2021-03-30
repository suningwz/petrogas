# -*- coding: utf-8 -*-

{
    'name': "smp_inventory",

    'summary': """
        Mise en place des fonctionnalité de gestion de stocks.
            """,

    'description': """
        Mise en place des fonctionnalité suivantes:
            * Rajouts sur la fiche des articles des compte de stock, perte, inventaire et de transit.
            * Possibilité de rajouter une valorisation spécifique pour chaque ligne d'inventaire
        """,

    'author': "DisruptSol",
    # 'website': "http://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'stock',
    'version': '0.1',

    # any module necessary for this one to work correctly
    # 'depends': ['account','smp_regime_douanier','stock_account', 'stock', 'purchase'],
    'depends': ['base_setup', 'smp_regime_douanier', 'stock_account', 'purchase'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',

        "data/inventory_parameter.xml",
        "data/ir_sequence_date.xml",
        "data/stock_location.xml",
        "data/picking_type.xml",
        # "data/product.category.csv",
        "data/uom.xml",
        "data/report_paperformat.xml",

        "views/transfert_charges.xml",
        "views/internal_picking.xml",
        'views/product_views.xml',
        'views/sale_charges.xml',
        'views/stock_inventory_views.xml',
        'views/stock_location_views.xml',
        'views/stock_move.xml',
        'views/stock_move_charges.xml',
        "views/stock_quant.xml",
        "views/reclassement_charges.xml",
        "views/reclassement.xml",
        "views/stock_picking.xml",
        "views/purchase_order.xml",
        "views/account_invoice.xml",
        "views/cmp_stock_valuation_views.xml",

        'wizard/stock_move_report.xml',
        "wizard/report_wizard.xml",
        "wizard/sale_analysis_report.xml",

    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
