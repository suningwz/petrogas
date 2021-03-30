# -*- coding: utf-8 -*-
from odoo import models, fields


class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    print_image = fields.Boolean(
        string='Print Image',
        help="""If invoice, you can see the product image in report of Invoice"""
    )
    image_sizes = fields.Selection(
        selection=[
            ('image', 'Big sized Image'),
            ('image_medium', 'Medium Sized Image'),
            ('image_small', 'Small Sized Image')
        ],
        string='Image Sizes',
        default="image_small",
        help="Image size to be displayed in report"
    )


class AccountInvoiceLine(models.Model):
    _inherit = 'account.invoice.line'

    image_small = fields.Binary(
        string='Product Image',
        related='product_id.image_small'
    )
