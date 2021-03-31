# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-

{
    'name': "smp_data",

    'summary': """
        Importation des données initiaux pour  Star Oil Gambia:
            * Partenaire
            * Article et categorie d'article
            """,

    'description': """
        Importation des données initiaux pour  SO Gambia
        """,

    'author': "DisruptSol",
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
        "data/uom.uom.csv",
        "data/product.category.csv",
        "data/account.journal.csv",
        "data/res.partner.category.csv",
        # "data/res.partner.csv",
        # "data/product.product.csv",
        # "data/data.xml",

        "report/smp_picking_report.xml",
        "report/reclassement_report.xml",
        "report/transfert_report.xml",
        "report/smp_account_move.xml",

    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
