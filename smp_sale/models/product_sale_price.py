# -*- coding: utf-8 -*-
from datetime import date,timedelta
from odoo import models, fields, api, exceptions, _

READONLY_STATES = {
    'draft': [('readonly', False)],
    'done': [('readonly', True)],
}


class ProductSalePrice(models.Model):
    _name = 'product.sale.price'
    _description = 'Correspond à la matrice des prix de vente'
    _order = 'start_date desc'

    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], string='State', default='draft')
    start_date = fields.Date(string="Start Date", default=lambda x: date.today(), required=True, states=READONLY_STATES)
    end_date = fields.Date(string="End date", readonly=True)
    value = fields.Float(string="Value", digits=(10, 2), required=True, states=READONLY_STATES)
    location_id = fields.Many2one('stock.location', string="Location", domain=[('usage', '=', 'internal')], required=True, states=READONLY_STATES)
    product_id = fields.Many2one('product.product', string='Product', domain=[('apply_price_structure', '=', True)], required=True, states=READONLY_STATES)
    regime_id = fields.Many2one('regime.douanier', string='Customs Duty', required=True, states=READONLY_STATES)
    uom_id = fields.Many2one('uom.uom', string="Unit", required=True, states=READONLY_STATES)
    quantity_to_confirm = fields.Boolean("Delivery to confirm", default=False, help="""Si coché le champs 
        le champs quantité livré sera éditable sur les bons de livraison généré à partir 
        de bon de commande et dont la facturation de l'article est configuré sur les quantités commandées.""")
    # quantity_to_confirm = fields.Boolean("Quantité Livrée à confirmer", default=False, help="""Si coché le champs
    #     le champs quantité livré sera éditable sur les bons de livraison généré à partir
    #     de bon de commande et dont la facturation de l'article est configuré sur les quantités commandées.""", states=READONLY_STATES)
    inter_uom_factor = fields.Float('Conversion factor', states=READONLY_STATES)

    _sql_constraints = [('unique_poduct_price_sale_couple',
                         'UNIQUE(start_date,product_id,location_id,regime_id)',
                         'The couple start date, product, regime and location must be unique !!'),
                        ('unique_product_price_sale_couple_valid',
                         'UNIQUE(product_id,location_id,regime_id,end_date)',
                         'A valid sale price must be unique !!')
                        ]



    @api.multi
    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.update({
            'start_date': date.today(),
            'end_date': False,
        })
        return super(ProductSalePrice, self).copy(default)

    def confirm(self):
        for line in self.sorted(key=lambda l: l.start_date):
            # self.ensure_one()
            print(line.start_date)
            previous_records = line._get_previous_lines()
            next_records = line._get_next_lines()

            if next_records:
                raise exceptions.except_orm('Erreur',"""Des lignes dont la date est supérieur au %s
                    existent déjà. Si vous souhaitez insérer un enregistrement entre deux rubrique existant veuillez 
                    utiliser le module de régularisation!!!""" % line.start_date)

            # TODO : Check if the last record dont have an end date
            if previous_records:
                last_record = previous_records[0]
                last_record.end_date = line.start_date - timedelta(days=1)
            line.state = 'done'
        return True

    def reopen(self):
        for r in self:
            r.end_date = None
            r.state = 'draft'

    def reorder(self):
        for line in self:
            # self.ensure_one()
            previous_records = line._get_previous_lines()
            next_records = line._get_next_lines()

            if next_records:
                raise exceptions.except_orm('Erreur',"""Des lignes dont la date est supérieur au %s
                    existent déjà. Si vous souhaitez insérer un enregistrement entre deux rubrique existant veuillez 
                    utiliser le module de régularisation!!!""" % line.start_date)

            # TODO : Check if the last record dont have an end date
            if previous_records:
                last_record = previous_records[0]
                last_record.end_date = line.start_date - timedelta(days=1)
            line.state = 'done'
        return True

    def _get_previous_lines(self):
        self.ensure_one()
        records = self.search([['start_date', '<', self.start_date],
                                                   ['product_id', '=', self.product_id.id],
                                                   ['location_id', '=', self.location_id.id],
                                                   ['regime_id', '=', self.regime_id.id],
                                                   ['state', '=', 'done']], limit=1, order="start_date desc").sorted(key=lambda r: r.start_date, reverse=True)

        return records

    def _get_next_lines(self):
        records = self.search([['start_date', '>', self.start_date],
                                                   ['product_id', '=', self.product_id.id],
                                                   ['location_id', '=', self.location_id.id],
                                                   ['regime_id', '=', self.regime_id.id],
                                                   ['state', '=', 'done']
                                                   ]).sorted(key=lambda r: r.start_date, reverse=True)
        return records

    @api.model
    def get_specific_records(self, start_date, product_id, location_id, regime_id):
        records = self.search([['product_id', '=', product_id.id],
                               ['location_id', '=', location_id.id],
                               ['regime_id', '=', regime_id.id],
                               ['start_date', '<=', start_date],
                               ['end_date', '=', False],
                               ['state', '=', 'done']
                           ]).sorted(key=lambda r: r.start_date)

        if not records:
            records = self.search([['product_id', '=', product_id.id],
                                       ['location_id', '=', location_id.id],
                                       ['regime_id', '=', regime_id.id],
                                       ['start_date', '<=', start_date],
                                       ['end_date', '>=', start_date],
                                       ['state', '=', 'done']
                                       ]).sorted(key=lambda r: r.start_date)
            if records:
                records = records[0]
            else:
                raise exceptions.UserError(_(""" No Structered Sale Price Was Founded."""))
        if records:
            if len(records) > 1:
                raise exceptions.UserError(_(""" Several valid sale prices was founded. ID: %s""") % str(', '.join(records.ids)))
            # records.ensure_one()
        return records

    def get_products(self, start_date, location_id, regime_id):
        start_date = str(date.strftime(start_date, '%Y-%m-%d'))
        sql = """ SELECT DISTINCT product_id 
            FROM product_sale_price 
            WHERE   
                location_id = %s
                AND regime_id = %s
                AND start_date <= '%s'
                AND (end_date >= '%s' OR end_date IS NULL)
                AND state = 'done'
            """ % (location_id.id, regime_id.id, start_date, start_date)
        print('khjlkhlkhlk: ', regime_id.id, ' * ', location_id.id)
        self.env.cr.execute(sql)
        # self.env.cr.execute(sql % (location_id.id, regime_id.id, start_date, start_date))
        products = [i['product_id'] for i in self.env.cr.dictfetchall()]
        products = self.env['product.product'].search([('id', 'in', products)])
        return products

    @api.onchange('product_id')
    def onchange_product_id(self):
        self.ensure_one()
        self.uom_id = self.product_id.uom_id

    # @api.onchange('uom_id')
    # def onchange_product_id(self):
    #     if self.uom_id and self.uom_id.category_id != self.product_id.uom_id.category_id:
