# -*- coding: utf-8 -*-
# © 2019 DisruptSol
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, api, fields, tools, _
from odoo.exceptions import ValidationError
from _collections import defaultdict
from datetime import  date
import xlsxwriter as xls
import io, base64
import pandas as pd


class CouponValueAnalysis(models.Model):
    _name = 'coupon.value.analysis'
    _description = 'Coupon Value Analysis'
    _auto = False

    date = fields.Date("Date")
    product_id = fields.Many2one('product.product', 'Product',readonly=True)
    location_id = fields.Many2one('stock.location', 'Emplacement', readonly=True)
    product_qty =  fields.Float("Quantité",readonly=True)
    value_unit =  fields.Float("Coupon Value",readonly=True)
    value = fields.Float("Value",readonly=True)
    state = fields.Float("Status",readonly=True)
    charges_not_in_stock = fields.Float("Autres Charges",readonly=True)

    @api.model_cr
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)

        query = """
            
        )
        """
        self.env.cr.execute(query)