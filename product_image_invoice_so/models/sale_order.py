# -*- coding: utf-8 -*-
from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    print_image = fields.Boolean(
        string='Print Image',
        help="""If ticked, you can see the product image in report of sale order/quotation"""
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


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    image_small = fields.Binary(
        string='Product Image',
        related='product_id.image_small'
    )
