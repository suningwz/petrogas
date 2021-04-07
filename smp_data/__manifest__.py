# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-

{
    'name': "Petrogas Company Data",

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
    # for the full list
    'category': 'tools',
    'version': '0.1',

    # any module necessary for this one to work correctly
    # 'depends': ['smp_inventory','smp_sale', 'account'],
    'depends': [],

    # always loaded
    'data': [
        "data/data.xml",
        # "data/external_layout_clean_petrogas.xml",

        # "report/external_layout_clean.xml",

        "report/smp_picking_report.xml",
        "report/reclassement_report.xml",
        "report/transfert_report.xml",
        "report/smp_account_move.xml",

    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
