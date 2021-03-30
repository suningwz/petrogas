# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo import models, fields, api, exceptions, _


class SaleCharges(models.Model):
    _name = 'sale.charges'
    _description = 'management of price structures'
    _order = 'start_date desc'

    active = fields.Boolean(default=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], string='State', default='draft')
    start_date = fields.Date(string="Start Date", default=lambda x: date.today(), required=True)
    end_date = fields.Date(string="End date", readonly=True, default=None)
    reference = fields.Char(string="Ref.", required=False)
    value = fields.Float(string="Value", digits=(10, 4), required=True)
    location_id = fields.Many2one('stock.location', string="Location", required=True)
    product_id = fields.Many2one('product.product', string='Product', domain=[('type', '=', 'product')], required=True)
    regime_id = fields.Many2one('regime.douanier', string='Customs Duty', required=True)
    rubrique_id = fields.Many2one('product.product', string="Charge", domain=[('type', '=', 'service')], required=True)
    uom_id = fields.Many2one('uom.uom', string="Unit")
    partner_id = fields.Many2one('res.partner', domain=[('supplier', '=', True)], help="Identify the supplier.")

    _sql_constraints = [('unique_price_structure_couple',
                         'UNIQUE(start_date,rubrique_id,product_id,location_id,regime_id)',
                         'The couple date, product, charge and custom duty must be unique !!')]

    @api.multi
    @api.depends('product_id')
    def  _onchange_product_id(self):
         self.uom_id = self.product_id.uom_id

    @api.multi
    def copy(self, default=None):
        default = dict(default or {})
        default.update({
            'reference': '_copy',
            'start_date': date.today(),
            'end_date': False,
        })
        return super(SaleCharges, self).copy(default)

    @api.multi
    def confirm(self):
        for record in self.sorted(key=lambda r: r.start_date, reverse=False):
            previous_records = record._get_previous_lines()
            next_records = record._get_next_lines()

            if next_records:
                raise exceptions.except_orm(_('Erreur'), _("""Lines concerning the item %s, the cost %s and whose date is greater than %s
                    already exist. If you wish to insert a record between two existing sections please
                    first put in draft the costs concerned""") % (record.product_id.product_tmpl_id.name, record.rubrique_id.product_tmpl_id.name, record.start_date))

                # raise exceptions.except_orm('Erreur', """Des lignes concernant l'article %s,  le frais %s et dont la date est supérieur au %s
                #     existent déjà. Si vous souhaitez insérer un enregistrement entre deux rubrique existant veuillez
                #     tout d'abords mettre en brouillons les frais concernés.""" % (record.product_id.product_tmpl_name, record.rubrique_id.product_tmpl_name, record.start_date))

            # TODO : Check if the last record dont have an end date
            if previous_records:
                last_record = previous_records[0]
                last_record.end_date = record.start_date - timedelta(days=1)
            record.state = 'done'
        return True

    @api.multi
    def cancel(self):
        self.write({'end_date': None, 'state': 'draft'})
        return True


    def _get_previous_lines(self):
        self.ensure_one()
        records = self.search([['start_date','<',self.start_date],
                               ['product_id', '=', self.product_id.id],
                               ['location_id', '=', self.location_id.id],
                               ['regime_id', '=', self.regime_id.id],
                               ['rubrique_id', '=', self.rubrique_id.id],
                               ('active', '=', True),
                               ('state', '=', 'done')

                               ]).sorted(key=lambda r: r.start_date, reverse=True)
        return records

    def _get_next_lines(self):
        records = self.search([['start_date', '>', self.start_date],
                               ['product_id', '=',self.product_id.id],
                               ['location_id', '=', self.location_id.id],
                               ['regime_id', '=', self.regime_id.id],
                               ['rubrique_id', '=', self.rubrique_id.id],
                               ['state', '=', 'done'],
                               ('active', '=', True)
                               ]).sorted(key=lambda r: r.start_date, reverse=True)

        return records

    @api.model
    def get_all_specics_structures(self, start_date, product_id, location_id, regime_id):
        records = self.search([('product_id', '=', product_id.id),
                               ('location_id', '=', location_id.id),
                               ('regime_id', '=', regime_id.id),
                               ('start_date', '<=', start_date),
                               '|', ('end_date', '=', None), ('end_date', '>=', start_date),
                                ('active', '=', True),
                                ('state', '=', 'done')
                               ])
        #TODO: Est-ce que deux rubrique valide?
        return records

    @api.multi
    def get_account_move_line(self, quantity, sens_out, ref):
        self.ensure_one()

        value = self.env.user.company_id.currency_id.round(abs(quantity * self.value))


        credit_line_vals = {
            'name': self.rubrique_id.name,
            'ref':  ref + ' / ' + self.rubrique_id.name,
            'partner_id': self.partner_id.id if self.partner_id else None,
            'product_id': self.product_id.id,
            'quantity': quantity,
            'product_uom_id': self.product_id.uom_id.id,
            'account_id': self.rubrique_id.property_account_income_id.id if sens_out else self.rubrique_id.property_account_expense_id.id,
            'debit': 0,
            'credit': value,
        }

        debit_line_vals = {
            'name': self.rubrique_id.name,
            'ref':  ref + ' / ' + self.rubrique_id.name,
            'partner_id': self.partner_id.id if self.partner_id else None,
            'product_id': self.product_id.id,
            'quantity': quantity,
            'product_uom_id': self.product_id.uom_id.id,
            'account_id': self.rubrique_id.property_account_expense_id.id if sens_out else self.rubrique_id.property_account_income_id.id,
            'debit': value,
            'credit': 0
        }

        rslt = [credit_line_vals, debit_line_vals]

        return rslt

    @api.onchange('product_id')
    def onchange_product_id(self):
        self.ensure_one()
        self.uom_id = self.product_id.uom_id
