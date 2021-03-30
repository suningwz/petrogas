# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from collections import defaultdict
# from bokeh.plotting import figure
# from bokeh.embed import components


class StockMoveCharges(models.Model):
    _inherit = "stock.move.charges"
    _order = 'date desc'

    # @api.multi
    # @api.depends('bulletin_line_id.regulated_amount')
    # def _compute_set_state(self):
    #     for r in self:
    #         if r.bulletin_line_id:
    #             state = 'done' if r.bulletin_line_id.state == 'done' else 'ongoing'
    #             regularized = True
    #         else:
    #             state = 'open' if r.account_move_line_ids else 'draft'
    #             regularized = False
    #         r.regularized = regularized
    #         r.write({'state': state})

    # @api.multi
    # @api.depends('regulated_amount')
    # def _compute_set_state(self):
    #     for r in self:
    #         if r.bulletin_line_id:
    #             state = 'done' if r.bulletin_line_id.state == 'done' else 'ongoing'
    #             r.bulletin_regulated_amount = 1
    #             r.regulated_amount = 0.0
    #         else:
    #             state = 'open' if r.account_move_line_ids else 'draft'
    #             r.bulletin_regulated_amount = 0.0
    #             regulated_amount = 0.0
    #         r.state = state
    #         # r.write({'state': state, 'bulletin_regulated_amount': bulletin_regulated_amount})



    # @api.multi
    # @api.depends('account_move_line_ids', 'bulletin_line_id', 'bulletin_line_id.state')
    # def _compute_set_state(self):
    #     for r in self:
    #         if r.bulletin_line_id:
    #             state = 'done' if r.bulletin_line_id.state == 'done' else 'ongoing'
    #         else:
    #             state = 'open' if r.account_move_line_ids else 'draft'
    #         r.state = state
    #     return True

    @api.multi
    @api.depends('account_move_line_ids', 'account_move_line_ids.full_reconcile_id', 'bulletin_line_id', 'bulletin_line_id.state')
    def _compute_set_state(self):
        for r in self:
            if r.stock_move_reconciled():
                state = 'done'
            else:
                if r.bulletin_line_id:
                    state = 'done' if r.bulletin_line_id.state == 'done' else 'ongoing'
                else:
                    state = 'open' if r.account_move_line_ids else 'draft'
            r.state = state
        return True




    charge_rule_category_id = fields.Many2one('charge.rule.category', 'Modèle de régularisation')
    bulletin_line_id = fields.Many2one('bulletin.line', 'Ligne de charge', ondelete="set null")
    bulletin_id = fields.Many2one('bulletin.bulletin', 'Bulletin', related='bulletin_line_id.bulletin_id', store=True, ondelete='set null')
    regulated_amount = fields.Float(string="Valeur Régularisé")
    previous_amount = fields.Float(string="Valeur Précédente")
    invoiced = fields.Boolean(string='Invoiced')
    state = fields.Selection([('draft', 'Draft'),
                              ('open', 'Accounting'),
                              ('ongoing', 'Regularization in progress'),
                              ('done', 'Regularized')], string='Statut', compute='_compute_set_state', store=True)

    @api.multi
    def stock_move_reconciled(self):
        if self.account_move_line_ids:
            account_id = self.rubrique_id.property_account_income_id
            account_move_line_id = self.account_move_line_ids.filtered(lambda r: r.account_id == account_id)
            account_move_line_id.ensure_one()
            if account_move_line_id.full_reconcile_id:
                return True
        return False


    @api.multi
    def compute_rule_stock_move_charge(self):
        stock_move_ids = self.mapped('stock_move_id')
        for record in self:
            dict_value = {'stock_move_ids': stock_move_ids,'stock_move_id': record.mapped('stock_move_id'), 'product_qty': sum(record.mapped('product_qty'))}

            for charge_rule_id in record.bulletin_line_id.charge_rule_category_id.charge_rule_ids.sorted(lambda r: r.sequence):
                charge_slip_line_id = record.bulletin_line_id.charge_slip_line_ids.filtered(lambda x: x.charge_rule_id == charge_rule_id)
                charge_slip_line_id.ensure_one()

                # TODO: Check si element nécessaire au calcule sont dans le dict
                if charge_rule_id.is_mandatory_input:
                    result = [charge_slip_line_id.amount]
                else:
                    result = charge_rule_id.compute_rule(dict_value)
                dict_value[charge_rule_id.code] = result[0]
                if not charge_rule_id.is_mandatory_input:
                    charge_slip_line_id.amount += result[0]
                if charge_rule_id.is_mandatory_output:
                    # record.write({'regulated_amount': result[0]})
                    record.regulated_amount = result[0]
                    # record.bulletin_line_id.regulated_amount += result[0]

    @api.multi
    def check_selection_unique_product_id_location_id(self):
        # state = self.mapped('state')
        if list(set(self.mapped('state')))[0] != 'open':
            raise exceptions.UserError("""All operations must be in 'open' state!! """)
        if len(self.mapped('location_id')) > 1:
            raise exceptions.UserError('All operation must be from the same location!! ')
        if len(self.mapped('product_id')) > 1:
            raise exceptions.UserError('All operation must concern the same product_id!! ')
        if len(self.mapped('rubrique_id')) > 1:
            raise exceptions.UserError('All operation must concern the same charge!! ')
        return True

    @api.multi
    def open_stock_move_charge_wizard(self):
        self.check_selection_unique_product_id_location_id()
        # stock_move_ids = self.mapped('stock_move_id')
        if self:
            ChargeWizard = self.env['stock.move.charges.wizard']
            view = self.env.ref('smp_bulletin.smp_stock_move_charges_compute_rule_wizard_form1')
            wiz = ChargeWizard.create({'stock_move_charges_ids': [(4, p.id) for p in self]})
            action = ChargeWizard.get_formview_action()
            action['res_id'] = wiz.id
            action['view_id'] = view.id
            action['target'] = 'new'
            return action

    @api.multi
    def create_bulletin(self):
        self.check_selection_unique_product_id_location_id()
        location_id = self.mapped('location_id')
        product_id = self.mapped('product_id')
        picking_type_ids = self.mapped('picking_type_id')
        rubrique_id = self.mapped('rubrique_id')
        charge_rule_category_id = self.mapped('charge_rule_category_id')

        """Create Bulletin"""
        Bul = self.env['bulletin.bulletin']
        bul_data = {
            'product_id': product_id.id,
            'location_id': location_id.id,
            'product_qty': sum(self.mapped('product_qty')),
            'stock_move_ids': [(4, x.id) for x in self.mapped('stock_move_id')],
            'picking_type_ids': [(4, x.id) for x in picking_type_ids],
        }
        bul_id = Bul.create(bul_data)
        # for x in self:
        #     x.bulletin_id = bul_id
        return bul_id

    @api.multi
    def create_bulletin_line(self):
        self.check_selection_unique_product_id_location_id()
        location_id = self.mapped('location_id')
        product_id = self.mapped('product_id')
        picking_type_ids = self.mapped('picking_type_id')
        rubrique_id = self.mapped('rubrique_id')
        charge_rule_category_id = self.mapped('charge_rule_category_id')
        if self.env.context.get('force_bulletin_id', False):
            bulletin_id = self.env.context.get('force_bulletin_id')
        else:
            bulletin_id = self.mapped('bulletin_id')
            bulletin_id.ensure_one()
            bulletin_id = bulletin_id.id
        """Create Bulletin line"""
        BulLine = self.env['bulletin.line']
        bul_line_data = {
            'rubrique_id': rubrique_id.id,
            'product_qty': sum(self.mapped('product_qty')),
            'value': sum(self.mapped('cost')),
            'charge_rule_category_id': charge_rule_category_id.id,
            'stock_move_charge_ids': [(4, x.id) for x in self],
            'bulletin_id': bulletin_id,
        }
        bul_line_id = BulLine.create([bul_line_data])
        # for x in self:
        #     x.bulletin_line_id = bul_line_id
        return bul_line_id

        # """Create Charge Slip line"""
        # ChargeSlip = self.env['charge.slip.line']
        # charge_slip_data = {
        #     'bulletin_id': None,
        #     'bulletin_line_id': None,
        #     'charge_rule_id': None,
        #     'charge_rule_category_id': None,
        #     'amount': None,
        # }
        # charge_slip_id = ChargeSlip.create([charge_slip_data])


class StockMoveChargesWizard(models.TransientModel):
    _name = 'stock.move.charges.wizard'
    _inherit = ['multi.step.wizard.mixin']
    _description = 'Guide de sélection des charges à régulariser'

    bulletin_selection = fields.Selection([('yes', 'Oui'), ('no', 'Non')], default='no',
                                          string="Incoperate Fees in an Existing Bulletin ?")
    bulletin_id = fields.Many2one('bulletin.bulletin', 'Bulletin', ondelete='set null')
    bulletin_line_selection = fields.Selection([('yes', 'Oui'), ('no', 'Non')], default='no',
                                               string="Incoperate Fees in an Existing Bulletin Line ?")
    bulletin_line_id = fields.Many2one('bulletin.line', 'Bulletin Fees Lines', ondelete="set null")
    stock_move_charges_ids = fields.Many2many('stock.move.charges', string="Stock Fees",
                                              default=lambda self: self._default_project_id())
    charge_rule_category_id = fields.Many2one('charge.rule.category', 'Regularization model', required=True)
    charge_slip_line_ids = fields.Many2many('charge.slip.line', string="Regularization model elements")

    @api.model
    def _selection_state(self):
        return [
            ('start', 'Start'),
            ('bulletin_line', 'Configure'),
            ('input', 'Les Entrées'),
            ('final', 'Final'),
        ]

    @api.model
    def _default_project_id(self):
        active_ids = self.env.context.get('active_ids')
        return active_ids

    def state_exit_start(self):
        if self.bulletin_selection == 'no':
            self.bulletin_id = self.stock_move_charges_ids.create_bulletin()

            bulletin_line_id = self.stock_move_charges_ids.with_context(force_bulletin_id=self.bulletin_id.id).create_bulletin_line()
            bulletin_line_id.charge_rule_category_id = self.charge_rule_category_id
            bulletin_line_id['bulletin_id'] = self.bulletin_id
            self.bulletin_line_id = bulletin_line_id

            charge_slip_line_ids = bulletin_line_id.get_charge_slip_line()
            self.charge_slip_line_ids = [(4, x.id) for x in charge_slip_line_ids.filtered(lambda x: x.is_mandatory_input == True)]

            self.bulletin_line_selection = 'no'
        for smc in self.stock_move_charges_ids:
            smc.charge_rule_category_id = self.charge_rule_category_id
        self.state = 'bulletin_line'

    def state_exit_bulletin_line(self):
        if self.bulletin_line_selection == 'no':
            charge_slip_line_ids = self.bulletin_line_id.get_charge_slip_line()
            self.charge_slip_line_ids = [(4, x.id) for x in charge_slip_line_ids.filtered(lambda x: x.is_mandatory_input == True)]

        elif self.bulletin_line_selection == 'yes' and  self.bulletin_selection == 'yes':

            # rajouté nouveau stock_move_charge au bulletin existant
            self.bulletin_id.stock_move_ids = [(4, x.id) for x in self.stock_move_charges_ids.mapped('stock_move_id')]

            # Rajouter les stock_move_charges au bulletin line
            self.bulletin_line_id.stock_move_charge_ids = [(4, x.id) for x in self.stock_move_charges_ids]

            # On met à jours les lignes d'entrées
            self.charge_slip_line_ids = [(4, x.id) for x in self.bulletin_line_id.charge_slip_line_ids]

        else:
            raise exceptions.UserError(_("""Veuillez selectionner Un bulletin !!!"""))

        self.state = 'input'

    def state_exit_input(self):
        self.stock_move_charges_ids.compute_rule_stock_move_charge()
        for line in self.stock_move_charges_ids.mapped('bulletin_line_id'):
            line.regulated_amount = sum(line.stock_move_charge_ids.mapped('regulated_amount'))

        self.bulletin_id.state = 'open'

        """On retourne le bulletin"""
        action = self.bulletin_id.get_formview_action()
        return action

        # self.state = 'final'


