# -*- coding: utf-8 -*-

from datetime import datetime
from dateutil import relativedelta
from itertools import groupby
from operator import itemgetter
from collections import defaultdict


from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError
from odoo.osv import expression
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools.float_utils import float_compare, float_round, float_is_zero

#
class StockQuant(models.Model):
    _inherit = 'stock.quant'

    # company_currency_id = fields.Many2one('res.currency', readonly=True, default=lambda self: self.env.user.company_id.currency_id)
    company_currency_id = fields.Many2one('res.currency', related='company_id.currency_id',
                                          string="Company Currency", readonly=True,
                                          help='Utility field to express amount currency', store=True)
    cost = fields.Float('Cost', help='Cost unit per unit and location', readonly=True, default = 0.0000)
    # total_amount = fields.Monetary('Cost', 'Stock value per  location', readonly=True, currency_field='company_currency_id',  digits=dp.get_precision('Account'))
    total_amount = fields.Monetary("Total", compute='_compute_amount', store=True, currency_field='company_currency_id', digits=dp.get_precision('Account'), default=0.0)

    @api.multi
    @api.depends('quantity', 'cost')
    def _compute_amount(self):
        for quant in self:
            quant.total_amount = quant.cost * quant.quantity

    # @api.model
