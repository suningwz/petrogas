# -*- coding: utf-8 -*-
from datetime import date,timedelta
from odoo import models, fields, api, exceptions


class SaleDma(models.Model):
    _name = 'sale.dma'
    _description = 'Découvert client autorisé'
    _order = 'start_date desc'

    state = fields.Selection([('draft', 'Draft'), ('done', 'Valide'), ('invalid', 'Invalide')], string='State', default='draft')
    start_date = fields.Date(string="Start Date", default=lambda x: date.today(), required=True)
    end_date = fields.Date(string="End date", readonly=True)
    value = fields.Float(string="Value", digits=(10, 4), required=True)
    partner_id = fields.Many2one('res.partner', string="Client", domain=[['customer', '=', True]], required=True)

    _sql_constraints = [('unique_sale_dma_couple',
                         'UNIQUE(start_date,partner_id)',
                         'Le couple start_date et partner_id doit-être unique !!')]

    @api.multi
    def copy(self, default=None):
        default = dict(default or {})
        default.update({
            'start_date': date.today(),
            'end_date': False,
        })
        return super(SaleDma, self).copy(default)

    def confirm(self):
        self.ensure_one()
        previous_records = self._get_previous_lines()
        next_records = self._get_next_lines()

        if next_records:
            raise exceptions.except_orm('Erreur',"""Des lignes dont la date est supérieur au %s
                existent déjà pour le même client. Si vous souhaitez insérer un enregistrement entre deux rubrique existant veuillez 
                utiliser le module de régularisation!!!""" % self.start_date)

        # TODO : Check if the last record dont have an end date
        if previous_records:
            last_record = previous_records[0]
            last_record.end_date = self.start_date - timedelta(days=1)
        self.state = 'done'
        self.partner_id.debit_limit = self.value
        return True

    def _get_previous_lines(self):
        self.ensure_one()
        records = self.search([['start_date', '<', self.start_date],
                                                   ['partner_id', '=', self.partner_id.id],
                                                   ['state', '=', 'done']
                                                   ]).sorted(key=lambda r: r.start_date)
        return records

    def _get_next_lines(self):
        self.ensure_one()
        records = self.search([['start_date', '>', self.start_date],
                                                   ['partner_id', '=', self.partner_id.id],
                                                   ['state', '=', 'done']
                                                   ]).sorted(key=lambda r: r.start_date, reverse=True)

        return records

    @api.model
    def get_specific_dma(self, start_date, partner_id):
        records = self.search([['partner_id', '=', partner_id.id],
                               ['start_date', '<=', start_date],
                               '|', ['end_date', '=', None], ['end_date', '>=', start_date],
                               ])
        return records

    # @api.multi


# class ResPartner(models.Model):
#     _inherit = 'res.partner'
#
#     sale_dma = fields.Float()