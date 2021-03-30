# -*- coding: utf-8 -*-
from datetime import date,timedelta
from odoo import models, fields, api, _
from odoo.osv import expression
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # default_regime_id = fields.Many2one('regime.douanier', string='Default Custom Duty')
    # regime_ids = fields.Many2many('regime.douanier', 'rel_partner_regime', 'partner_id', 'regime_id')
    default_location_id = fields.Many2one('stock.location', string='Default Location')
    location_ids = fields.Many2many('stock.location', 'rel_partner_location', 'partner_id', 'location_id')
    code = fields.Char('Code')

    @api.multi
    def name_get(self):
        result = []
        for s in self:
            if s.code:
                name = s.code + ' / ' + s.name
            else:
                name = s.name
            result.append((s.id, name))
        return result

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        ids = []
        if name and len(name) >= 2:
            ids = self.search(['|', ('name', 'ilike', name),('code', 'ilike', name)] + args, limit=limit)
        if not ids:
            ids = self.search([('name', operator, name)] + args, limit=limit)
        return ids.name_get()

