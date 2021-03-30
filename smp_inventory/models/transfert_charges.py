# -*- coding: utf-8 -*-
from datetime import date,timedelta
from odoo import models, fields, api, exceptions


class TransfertCharges(models.Model):
    _name = 'transfert.charges'
    _description = 'management of price structures'
    _order = 'start_date desc'

    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], string='State', default='draft')
    start_date = fields.Date(string="Start Date", default=lambda x: date.today(), required=True, states={'done': [('readonly', True)]})
    end_date = fields.Date(string="End date", readonly=True)
    value = fields.Float(string="Value", digits=(10, 4), required=True, states={'done': [('readonly', True)]})
    location_src_id = fields.Many2one('stock.location', string="Location Source", required=True,
                                      domain=[('usage', '=', 'internal')], states={'done': [('readonly', True)]})
    location_dest_id = fields.Many2one('stock.location', string="Location Destination", required=True,
                                       domain=[('usage', '=', 'internal')], states={'done': [('readonly', True)]})
    product_id = fields.Many2one('product.product', string='Product', domain=[('type', '=', 'product')], required=True, states={'done': [('readonly', True)]})
    rubrique_id = fields.Many2one('product.product', string="Rubriques", domain=[('type', '=', 'service')],
                                  required=True, states={'done': [('readonly', True)]})
    type = fields.Selection([('in', 'In'), ('out', 'Out')], string='Type de frais', default='out', states={'done': [('readonly', True)]})
    uom_id = fields.Many2one('uom.uom', string="Unit", required=True, states={'done': [('readonly', True)]})

    _sql_constraints = [('unique_price_structure_couple',
                         'UNIQUE(start_date,rubrique_id,product_id,location_src_id,location_dest_id)',
                         'Le couple dates, article, location source, location destination et rubrique doit-être unique !!')]

    @api.multi
    @api.onchange('product_id')
    def onchange_product_id(self):
        self.ensure_one()
        self.uom_id = self.product_id.uom_id

    @api.multi
    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.update({
            'start_date': date.today(),
            'end_date': False,
        })
        return super(TransfertCharges, self).copy(default)

    @api.multi
    def confirm(self):
        for record in self:
            previous_records = record._get_previous_lines()
            next_records = record._get_next_lines()
    
            if next_records:
                raise exceptions.except_orm('Erreur',"""Des lignes dont la date est supérieur au %s
                    existent déjà. Si vous souhaitez insérer un enregistrement entre deux rubrique existant veuillez 
                    utiliser le module de régularisation!!!""" % record.start_date)
    
            # TODO : Check if the last record dont have an end date
            if previous_records:
                last_record = previous_records[0]
                last_record.end_date = record.start_date - timedelta(days=1)
            record.state = 'done'
        return True

    def _get_previous_lines(self):
        self.ensure_one()
        records = self.env['transfert.charges'].search([['start_date', '<', self.start_date],
                                                       ['product_id', '=', self.product_id.id],
                                                       ['location_src_id', '=', self.location_src_id.id],
                                                       ['location_dest_id', '=', self.location_dest_id.id],
                                                       ['type', '=', self.type],
                                                       ['rubrique_id', '=',self.rubrique_id.id]
                                                        ]).sorted(key=lambda r: r.start_date)
        return records

    def _get_next_lines(self):
        self.ensure_one()
        records = self.env['transfert.charges'].search([['start_date', '>', self.start_date],
                                                        ['product_id', '=', self.product_id.id],
                                                        ['location_src_id', '=', self.location_src_id.id],
                                                        ['location_dest_id', '=', self.location_dest_id.id],
                                                        ['type', '=', self.type],
                                                        ['rubrique_id', '=', self.rubrique_id.id]
                                                        ]).sorted(key=lambda r: r.start_date, reverse=True)

        return records

    @api.model
    def _get_all_specics_structures(self, start_date, product_id, location_src_id, location_dest_id, sens):
        records = self.search([['product_id', '=', product_id.id],
                               ['location_src_id', '=', location_src_id.id],
                               ['location_dest_id', '=', location_dest_id.id],
                               ['type', '=', sens],
                               ['start_date', '<=', start_date],
                               ['end_date', '=', False],
                               ])

        return records

    def _get_account_move_line(self, quantity, ref):
        self.ensure_one()
        value = self.env.user.company_id.currency_id.round(abs(quantity * self.value))

        vals = {
            'name': self.rubrique_id.name,
            'ref': ref + ' / ' + self.rubrique_id.name,
            # 'partner_id': self.partner_id.id if self.partner_id else None,
            'product_id': self.product_id.id,
            'quantity': quantity,
            'product_uom_id': self.product_id.uom_id.id,
            'account_id': self.rubrique_id.property_account_expense_id.id,
            'debit': 0 ,
            'credit': value,
        }

        return [vals]

