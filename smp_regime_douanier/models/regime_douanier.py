# -*- coding: utf-8 -*-
from datetime import date,timedelta
from odoo import models, fields, api, exceptions


class RegimeDouanier(models.Model):
    _name = 'regime.douanier'
    _description = "Liste les type de régime de vente ou d'achat"
    _rec_name = 'code'

    code = fields.Char('Code', size=9, required=True)
    name = fields.Char('Name', size=128, required=True)

    _sql_constraints = [('regime_douanier_unique_name', 'UNIQUE(name,code)', 'The name and the code must be unique !!')]

    @api.multi
    def name_get(self):
        result = []
        for s in self:
            name = s.code + ' / ' + s.name
            result.append((s.id, name))
        return result


class ResPartner(models.Model):
    _inherit = 'res.partner'

    default_regime_id = fields.Many2one('regime.douanier', string='Default Custom Duty')
    regime_ids = fields.Many2many('regime.douanier', 'rel_partner_regime', 'partner_id', 'regime_id')

