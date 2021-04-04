# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions
from datetime import timedelta, date

READONLY_STATES = {
    'draft': [('readonly', False),],
    'open': [('readonly', True)],
    'closed': [('readonly', True)],
    'cancel': [('readonly', True)],
}

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    credoc_id = fields.Many2one('credoc.credoc', 'Letter Credit')


class StockMove(models.Model):
    _inherit = 'stock.move'

    credoc_id = fields.Many2one('credoc.credoc', 'Letter Credit', related='picking_id.credoc_id')
