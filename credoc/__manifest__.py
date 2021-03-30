{
    'name': "credoc",

    'summary': """Gestion des lignes de crédit""",

    'description': """
        Mise en place des fonctionnalités de gestion des crédits docummentaire.
            * Permet de créer une ligne de crédit
            * D'affecter une ligne de crédit au BC, BL et Facture Fournisseur.
    """,

    'author': "DisruptSOl",
    # 'website': "http://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'accounting',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['percent_field', 'account', 'purchase_stock', 'stock', 'currency_rate_inverted', 'smp_inventory'],

    # always loaded
    'data': [
        'data/ir_sequence_date.xml',
        'data/credoc.xml',

        'security/security.xml',
        'security/ir.model.access.csv',

        'views/credoc.xml',
        'views/purchase_order.xml',
        'views/stock_picking.xml',
        'views/invoice.xml',

    ],
    # only loaded in demonstration mode
    'demo': [
        # 'demo/demo.xml',
    ],
    # "post_init_hook": "post_init_hook",
    'application': False,
    'installable': True,
}
# -*- coding: utf-8 -*-
