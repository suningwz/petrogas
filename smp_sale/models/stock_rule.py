# -*- coding: utf-8 -*-

from collections import OrderedDict
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo.tools.misc import split_every
from psycopg2 import OperationalError

from odoo import api, fields, models, registry, _
from odoo.osv import expression
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_compare, float_round

from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class StockRule(models.Model):
    """ A rule describe what a procurement should do; produce, buy, move, ... """
    _inherit = 'stock.rule'

    @api.depends('action', 'location_id', 'location_src_id', 'picking_type_id', 'procure_method')
    def _get_stock_move_values(self, product_id, product_qty, product_uom, location_id, name, origin, values, group_id):
        move_values = super(StockRule, self)._get_stock_move_values( product_id, product_qty, product_uom, location_id, name, origin, values, group_id)

        if move_values.get('sale_line_id', False):
            sale_order_line = self.env['sale.order.line'].search([('id', '=',move_values.get('sale_line_id'))])[0]
            if sale_order_line.order_id.location_id:
                move_values['location_id'] = sale_order_line.order_id.location_id.id

        return move_values