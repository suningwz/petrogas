# -*- coding: utf-8 -*-

from datetime import datetime
from dateutil import relativedelta
from itertools import groupby
from operator import itemgetter

from odoo import api, fields, models, tools, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError
from odoo.osv import expression
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools.float_utils import float_compare, float_round, float_is_zero
from collections import defaultdict


class StockMoveCharges(models.Model):
    _name = "stock.move.charges"
    _description = "Cost Landing"

    @api.depends('account_move_line_ids')
    def compute_set_state(self):
        for r in self:
            if r.account_move_line_ids:
                r.state = 'open'
            else:
                r.state = 'draft'


    # date = fields.Datetime('Date', related='stock_move_id.date_expected.date()',store=True)
    date = fields.Date('Date', compute='set_date', store=True)
    location_id = fields.Many2one('stock.location', 'Location', compute='get_location',store=True)
    stock_move_id = fields.Many2one('stock.move', 'Operation', ondelete='CASCADE', store=True)
    product_id = fields.Many2one('product.product', 'Product', related='stock_move_id.product_id', store=True)
    product_qty = fields.Float(string='Quantity', related='stock_move_id.product_qty', store=True)
    picking_type_id = fields.Many2one('stock.picking.type', "Operation type", related='stock_move_id.picking_type_id',
                                      store=True, compute='_compute_set_state')
    rubrique_id = fields.Many2one('product.product', 'Charge')
    cost_unit = fields.Float('Coût Unitaire', digits=dp.get_precision('Product Price'))
    cost = fields.Float('Coût Total', digits=dp.get_precision('Product Price'))
    account_move_line_ids = fields.One2many('account.move.line', 'charge_id')
    state = fields.Selection([('draft', 'Draft'), ('open', 'Accounting')], string='Statut', store=True)
    sale_charge_id = fields.Many2one('sale.charges', 'Sale Fees', copy=False)
    transfert_charge_id = fields.Many2one('transfert.charges', string='Transfert Fees', copy=False)
    reclassement_charge_id = fields.Many2one('reclassement.charges', string='   Reclassement Fees', copy=False)
    purchase_charge_id = fields.Many2one('purchase.order.cost.line', string="Purchase fees", copy=False)

    # @api.multi

    _sql_constraints = [('check_cost_charge', 'CHECK(cost > 0)', 'Cost is required and must be greater than 0.')]

    @api.multi
    @api.depends('stock_move_id')
    def get_location(self):
        for r in self:
            if r.stock_move_id and r.stock_move_id._is_in():
                r.location_id = r.stock_move_id.location_dest_id
            elif r.stock_move_id and r.stock_move_id._is_out():
                r.location_id = r.stock_move_id.location_id

    @api.multi
    @api.depends('stock_move_id')
    def set_date(self):
        for r in self:
            if r.stock_move_id:
                r.date = r.stock_move_id.date_expected.date()
            else:
                r.date = None

    @api.multi
    def unlink(self):
        user = self.env.user
        group = self.env['res.groups'].search([('id', '=', self.env.ref('smp_bulletin.group_bulletin_manager').id)])
        if not user in group.users:
            raise UserError(_("""You are not allowed to delete stock charges! Please contact your supervisor!"""))

        if all(self.mapped('account_move_line_ids.reconciled')):
            raise UserError(_("""Please cancel the reconcilliation before deleting a stock charge."""))

        stock_move_id = self.mapped('stock_move_id')
        stock_move_id.mapped('account_move_ids').button_cancel()
        self.with_context(check_move_validity=False).mapped('account_move_line_ids').unlink()
        super(StockMoveCharges, self).unlink()
        stock_move_id.update_account_entry_move()
        return True


    @api.model
    def prepare_sale_charges_account_move_line(self, quantity, stock_move_id):
        stock_move_id.ensure_one()
        # stock_move_id = self.stock_move_id
        res = []
        if stock_move_id._context.get('forced_ref'):
            ref = stock_move_id._context['forced_ref']
        else:
            ref = stock_move_id.picking_id.name

        location_id = stock_move_id.location_id if stock_move_id._is_out() else stock_move_id.location_dest_id

        if not stock_move_id.origin_returned_move_id:
            sale_charges_ids = stock_move_id.env['sale.charges'].get_all_specics_structures(stock_move_id.date,
                                                                                            stock_move_id.product_id,
                                                                                            location_id,
                                                                                            stock_move_id.picking_id.regime_id)
        facteur = 1

        if stock_move_id.origin_returned_move_id:
            sale_charges_ids = stock_move_id.origin_returned_move_id.charges_ids.mapped('sale_charge_id')
            facteur = 1


        if sale_charges_ids:
            for charge in sale_charges_ids:
                cost = self.env.user.company_id.currency_id.round(abs(quantity * charge.value))
                charge_id = self.create([{
                    'stock_move_id': stock_move_id.id,
                    'rubrique_id': charge.rubrique_id.id,
                    'sale_charge_id': charge.id,
                    'cost': facteur * cost,
                }])
                account_move_lines = charge.get_account_move_line(quantity, stock_move_id._is_out(), ref)
                for line in account_move_lines:
                    line['charge_id'] = charge_id.id
                res += [(0, 0, line_vals) for line_vals in account_move_lines]

        # Create charge of transport
        if stock_move_id.has_transport_charge() and not stock_move_id.origin_returned_move_id:
            transport_aml_dict = stock_move_id.create_transport_account_move_line()
            if transport_aml_dict:
                res += [(0, 0, v) for k, v in transport_aml_dict.items()]
        return res

    @api.multi
    def prepare_transfert_charges_account_move_line(self, quantity, stock_move_id):
        stock_move_id.ensure_one()
        res = []
        ref = stock_move_id._context.get('forced_ref', False)
        ref = ref and ref or stock_move_id.origin

        for charge in stock_move_id.charges_ids:
            line = charge.transfert_charge_id._get_account_move_line(quantity, ref)
            line[0]['charge_id'] = charge.id
            res += [(0, 0, line_vals) for line_vals in line]

        # Create charge of transport
        if stock_move_id.has_transport_charge():
            transport_aml_dict = stock_move_id.create_transport_account_move_line()
            if transport_aml_dict:
                res += [(0, 0, v) for k, v in transport_aml_dict.items()]
        return res

    def prepare_reclassement_charges_account_move_line(self, quantity,  stock_move_id):
        stock_move_id.ensure_one()

        res = []
        ref = stock_move_id._context.get('forced_ref', False)
        ref = ref and ref or stock_move_id.origin

        for charge in stock_move_id.charges_ids:
            line = charge.reclassement_charge_id._get_account_move_line(quantity, ref)
            line[0]['charge_id'] = charge.id
            res += [(0, 0, line_vals) for line_vals in line]
        return res

    @api.model
    def create_purchase_charges(self, stock_move_id):
        stock_move_id.ensure_one()
        if stock_move_id.purchase_line_id and stock_move_id.purchase_line_id.po_cost_line_ids:
            res = []
            if stock_move_id.origin_returned_move_id:
                stock_move_return_id = stock_move_id.origin_returned_move_id
                for charge in stock_move_return_id.charges_ids:
                    cost = stock_move_id.product_qty * charge_id.cost / stock_move_return_id.product_qty
                    charge_id = stock_move_id.charges_ids.create({
                        'rubrique_id': charge.rubrique_id.id,
                        'cost': cost,
                        'purchase_charge_id': charge.purchase_charge_id.id,
                        'stock_move_id': stock_move_id.id,
                    })
            else:
                """On crée les charges"""
                for po_cost_line_id in stock_move_id.purchase_line_id.po_cost_line_ids:
                    cost = stock_move_id.product_uom_qty * po_cost_line_id.value / po_cost_line_id.product_uom_qty
                    charge_id = stock_move_id.charges_ids.create({
                        'rubrique_id': po_cost_line_id.rubrique_id.id,
                        'cost': cost,
                        'purchase_charge_id': po_cost_line_id.id,
                        'stock_move_id': stock_move_id.id,
                    })
        # else:
        #     raise UserError(_("""An 'incoming' operation must be linked to a purchase line!!! """))

    @api.model
    def prepare_purchase_charges_account_move_line(self, quantity, stock_move_id):
        stock_move_id.ensure_one()

        res = []
        if stock_move_id._context.get('forced_ref'):
            ref = stock_move_id._context['forced_ref']
        else:
            ref = stock_move_id.picking_id.name

        for charge in stock_move_id.charges_ids:
            # line = charge.puchase_charge_id._get_account_move_line(quantity, ref)
            value = self.env.user.company_id.currency_id.round(abs(self.cost))

            vals = {
                'name': charge.rubrique_id.name,
                'ref': ref + ' / ' + charge.rubrique_id.name,
                # 'partner_id': self.partner_id.id if self.partner_id else None,
                'product_id': charge.product_id.id,
                'quantity': quantity,
                'product_uom_id': charge.product_id.uom_id.id,
                'account_id': charge.rubrique_id.property_account_expense_id.id,
                'debit': 0 if not stock_move_id.origin_returned_move_id else value,
                'credit': value if not stock_move_id.origin_returned_move_id else 0,
                'charge_id': charge.id
            }
            res += [(0, 0, vals)]
        return res


    def _get_charge_account(self):
        accounts_data = self.rubrique_id.product_tmpl_id.get_product_accounts()

        expense = accounts_data['expense'].id
        income = accounts_data['income'].id

        if not expense or not income:
            raise UserError(_("""Vérifier que les comptes de provisions et de dépenses sont bien paramétrés au niveau de la charge"""))

        return expense, income


    def prepare_account_move_line_from_charge(self):
        """•	Comment déterminer le compte :
            * Est-ce que la charge est inclus dans le cout du stock de destination.
            * Oui, alors compte de provision.
            * Non alors compte de provision et compte de dépense.
            * Comment détermine t’on le signe de la balance :
            * Ecriture de provision toujours au crédit sauf si il s’agit d’un retour
        """
        self.ensure_one()
        if self.account_move_line_ids:
            raise UserError(_("""Charge 's account entries already exist!!!"""))

        journal_id, acc_src, acc_dest, acc_valuation = self.stock_move_id._get_accounting_data_for_valuation()
        expense, income = self._get_charge_account()
        move_id = self.stock_move_id.account_move_ids
        move_id.ensure_one()
        cancelled_charge = False
        if self.stock_move_id.origin_returned_move_id:
            cancelled_charge = True

        value = - self.cost if cancelled_charge else self.cost
        res = {}
        ref = self.stock_move_id.reference
        provision_aml = {
            'name': self.rubrique_id.name,
            'ref': ref + ' / ' + self.rubrique_id.name,
            # 'partner_id': self.partner_id.id if self.partner_id else None,
            'product_id': self.product_id.id,
            'quantity': self.product_qty,
            'product_uom_id': self.product_id.uom_id.id,
            'account_id': income,
            'debit': abs(value) if value < 0 else 0,
            'credit': abs(value) if value > 0 else 0,
            'charge_id': self.id,
            'move_id': move_id.id,
        }
        res['provision']= provision_aml

        trigger_cost_valuation = self.stock_move_id.picking_type_id.trigger_cost_valuation
        if not trigger_cost_valuation:
            expense_line = provision_aml.copy()
            expense_line['account_id'] = expense
            expense_line['debit'] = abs(value) if value > 0 else 0
            expense_line['credit'] = abs(value) if value < 0 else 0
            res['expense'] = expense_line
        return res

    @api.multi
    def generate_move_charge_accounting_entry(self):
        stock_move_ids = self.mapped('stock_move_id')
        stock_move_ids.update_account_entry_move()
        # for charge in self:
        #     if charge.state == 'draft' and charge.stock_move_id.account_move_ids:
        #         charge.update_account_entry_move
                # if not charge.account_move_line_ids:
                #     aml_ids = charge.account_move_line_ids
                #     move_id = charge.stock_move_id.account_move_ids
                #     move_id.ensure_one()
                #
                #     journal_id, acc_src, acc_dest, acc_valuation = charge.stock_move_id._get_accounting_data_for_valuation()
                #     expense, income = charge._get_charge_account()
                #
                #     if not aml_ids:
                #         res = charge.prepare_account_move_line_from_charge()
                #         for k, v in res.items():
                #             v['move_id'] = move_id.id
                #             self.env['account.move.line'].create(v)


    @api.multi
    def get_move_charge_accounting_entry_new(self):
        self.ensure_one()
        aml_ids =  self.account_move_line_ids
        if aml_ids:
            move_id = aml_ids.mapped('move_id')
        else:
            move_id = self.stock_move_id.account_move_ids

        move_id.ensure_one()

        journal_id, acc_src, acc_dest, acc_valuation = self.stock_move_id._get_accounting_data_for_valuation()
        expense, income = self._get_charge_account()

        # if not aml_ids and self.state == 'draft':
        #
        #     res = self.prepare_account_move_line_from_charge()
        #     for k, v in res.items():
        #         v['move_id'] = move_id.id
        #         self.env['account.move.line'].create(v)

        is_returned = False
        if self.picking_type_id.trigger_cost_valuation and not is_returned:
            aml_ids.ensure_one()
            if self.stock_move_id._is_out():
                debit_line = aml_ids
                credit_line = aml_ids.move_id.line_ids.filtered(lambda x: x.debit == 0
                                                                          and x.credit == abs()
                                                                          and x.account_id.id == acc_dest
                                                                          and not x.charge_id)
        else:
            assert len(aml_ids) == 2
            debit_line = aml_ids.filtered(lambda x: x.debit >= 0
                                                    and x.credit == 0
                                                    and x.account_id.id == expense)
            debit_line.ensure_one()
            credit_line = aml_ids - debit_line
            credit_line.ensure_one()

    @api.multi
    def get_move_charge_accounting_entry(self):
        self.ensure_one()
        aml_ids = self.account_move_line_ids
        if aml_ids:
            move_id = aml_ids.mapped('move_id')
        else:
            move_id = self.stock_move_id.account_move_ids

        move_id.ensure_one()

        journal_id, acc_src, acc_dest, acc_valuation = self.stock_move_id._get_accounting_data_for_valuation()
        expense, income = self._get_charge_account()

        if self.stock_move_id._is_out():

            if self.picking_type_id.code in ['internal', 'incoming']:
                aml_ids.ensure_one()
                credit_line = aml_ids
                print("opération: %s" % self.stock_move_id.reference)
                debit_line = aml_ids.move_id.line_ids.filtered(lambda x: x.credit == 0
                                                                          and x.stock_move_id.id == self.stock_move_id.id
                                                                          and x.account_id.id == acc_dest
                                                                          and not x.charge_id)
                if len(credit_line) != 1:
                    print('Stock_move_id = %s , pc_id = %s' % (self.stock_move_id.id, debit_line.move_id.id))
                    credit_line.ensure_one()


            elif self.picking_type_id.code in ['outgoing']:
                debit_line = aml_ids.filtered(lambda x: x.debit >= 0
                                                        and x.credit == 0
                                                        and x.account_id.id == expense)
                debit_line.ensure_one()
                credit_line = aml_ids.filtered(lambda x: x.debit == 0 and x.credit >= 0
                                                         and debit_line.id != x.id
                                                         and x.account_id.id == income)
                credit_line.ensure_one()
            else:
                raise UserError("""The type of operation is not recognized !!!""")

        elif self.stock_move_id._is_in():
            if self.picking_type_id.code in ['internal', 'incoming']:
                aml_ids.ensure_one()
                credit_line = aml_ids
                assert credit_line.debit == 0 and credit_line.credit >= 0 and credit_line.account_id.id == income
                debit_line = aml_ids.move_id.line_ids.filtered(lambda x: x.debit >= 0
                                                                    and x.credit == 0
                                                                    and x.account_id.id == acc_valuation
                                                                    and not x.charge_id)
                debit_line.ensure_one()
            # elif self.picking_type_id.code in ['incoming']:
            #     aml_ids.ensure_one()
            #     credit_line = aml_ids
            #     debit_line = aml_ids.filtered(lambda x: x.debit == 0
            #                                             and x.credit == debit_line.move_id.amount
            #                                             and x.account_id == acc_valuation
            #                                             and x.stock_move_id == self.stock_move_id)
            #     debit_line.ensure_one
            #     assert credit_line.debit == 0 and credit_line.credit >= 0 and credit_line.account_id.id == income
            elif self.picking_type_id.code in ['outgoing']:
                debit_line = aml_ids.filtered(lambda x: x.debit >= 0
                                                        and x.credit == 0
                                                        and x.account_id.id == income)
                debit_line.ensure_one()
                credit_line = aml_ids.filtered(lambda x: x.debit == 0 and x.credit >= 0 and debit_line.id != x.id
                                                         and x.account_id.id == expense)
                credit_line.ensure_one()
            else:
                raise UserError("""The type of operation is not identifiable !!!""")

        else:
            raise UserError("""The type of operation is not identifiable !!!""")

        return debit_line, credit_line

    @api.multi
    def get_move_charge_accounting_entry_old(self):
        self.ensure_one()
        aml_ids = self.account_move_line_ids
        if aml_ids:
            move_id = aml_ids.mapped('move_id')
        else:
            move_id = self.stock_move_id.account_move_ids

        move_id.ensure_one()

        journal_id, acc_src, acc_dest, acc_valuation = self.stock_move_id._get_accounting_data_for_valuation()
        expense, income = self._get_charge_account()

        if self.stock_move_id._is_out():

            if self.picking_type_id.code in ['internal', 'incoming']:
                aml_ids.ensure_one()
                debit_line = aml_ids
                print("opération: %s" % self.stock_move_id.reference)
                credit_line = aml_ids.move_id.line_ids.filtered(lambda x: x.debit == 0
                                                                          and x.stock_move_id.id == self.stock_move_id.id
                                                                          and x.account_id.id == acc_dest
                                                                          and not x.charge_id)
                if len(credit_line) != 1:
                    print('Stock_move_id = %s , pc_id = %s' % (self.stock_move_id.id, debit_line.move_id.id))
                    credit_line.ensure_one()


            elif self.picking_type_id.code in ['outgoing']:
                debit_line = aml_ids.filtered(lambda x: x.debit >= 0
                                                        and x.credit == 0
                                                        and x.account_id.id == expense)
                debit_line.ensure_one()
                credit_line = aml_ids.filtered(lambda x: x.debit == 0 and x.credit >= 0
                                                         and debit_line.id != x.id
                                                         and x.account_id.id == income)
                credit_line.ensure_one()
            else:
                raise UserError("""The type of operation is not recognized !!!""")

        elif self.stock_move_id._is_in():
            if self.picking_type_id.code in ['internal', 'incoming']:
                aml_ids.ensure_one()
                credit_line = aml_ids
                assert credit_line.debit == 0 and credit_line.credit >= 0 and credit_line.account_id.id == income
                debit = aml_ids.move_id.line_ids.filtered(lambda x: x.debit >= debit_line.move_id.amount
                                                                    and x.credit == 0
                                                                    and x.account_id.id == acc_valuation
                                                                    and not x.charge_id)
                debit.ensure_one()
            # elif self.picking_type_id.code in ['incoming']:
            #     aml_ids.ensure_one()
            #     credit_line = aml_ids
            #     debit_line = aml_ids.filtered(lambda x: x.debit == 0
            #                                             and x.credit == debit_line.move_id.amount
            #                                             and x.account_id == acc_valuation
            #                                             and x.stock_move_id == self.stock_move_id)
            #     debit_line.ensure_one
            #     assert credit_line.debit == 0 and credit_line.credit >= 0 and credit_line.account_id.id == income
            elif self.picking_type_id.code in ['outgoing']:
                debit_line = aml_ids.filtered(lambda x: x.debit >= 0
                                                        and x.credit == 0
                                                        and x.account_id.id == income)
                debit_line.ensure_one()
                credit_line = aml_ids.filtered(lambda x: x.debit == 0 and x.credit >= 0 and debit_line.id != x.id
                                                         and x.account_id.id == expense)
                credit_line.ensure_one()
            else:
                raise UserError("""The type of operation is not identifiable !!!""")

        else:
            raise UserError("""The type of operation is not identifiable !!!""")

        return debit_line, credit_line