# -*- coding: utf-8 -*-
{
    'name': 'Product image in Sale order and Invoice',
    'summary': """Product image in (sale order line and report) - (account invoice line and report)""",
    'author': 'CML',
    'category': 'Sales',
    'website': '',
    'version': '0.1',
    'depends': [
        'sale',
        'account',
    ],
    'data': [
        'views/sale_order_view.xml',
        'views/report_sale_order.xml',
        'views/account_invoice_view.xml',
        'views/report_account_invoice.xml'
    ],
    'images': [
        'static/description/icon.png'
    ],
    'price': 15,
    'license': 'AGPL-3',
    'currency': 'EUR',
}
