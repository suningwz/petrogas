# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_is_zero
from datetime import timedelta, date
import math

READONLY_STATES = {
    'draft': [('readonly', False)],
    'open': [('readonly', True)],
    'closed': [('readonly', True)],
    'cancel': [('readonly', True)],
}


class CredocConfiguration(models.Model):
    _name = 'credoc.configuration'
    _description = "Configuration de la gestion de Letter Credit"

    commission_account = fields.Many2one('account.account', 'Compte de commission')
    deposit_account = fields.Many2one('account.account', 'Compte de déposit')


class CredocCredoc(models.Model):
    _name = 'credoc.credoc'
    _description = "gestion documentaire"


    # @api.depends('invoice_ids')
    # def _get_payment_ids(self):
    #     # self.ensure_one()
    #     for r in self:
    #         if r.mapped('invoice_ids.invoice_id.payment_ids'):
    #             r.payment_ids = r.mapped('invoice_ids.invoice_id.payment_ids')

    @api.depends('invoice_ids','invoice_ids.invoice_id.payment_ids' )
    def _get_payment_ids(self):
        self.ensure_one()
        # for r in self:
        # invoice_ids = self.mapped('invoice_ids.invoice_id.payment_ids')
        invoice_ids2 = self.mapped('invoice_ids.invoice_id.payment_group_ids.payment_ids')
        # invoice_ids2 += invoice_ids
        # if self.mapped('invoice_ids.invoice_id.payment_ids.'):
        if invoice_ids2:
                self.payment_ids = invoice_ids2
                self.paid_amount = sum(invoice_ids2.mapped('amount'))


    # @api.multi
    # @api.depends('payment_ids')
    # def _get_paid_amount(self):
    #     self.ensure_one()
    #     if not self.payment_ids:
    #         self.paid_amount = sum([r.amount for r in self.payment_ids])
    #     else:
    #         self.paid_amount = 0.0


    name = fields.Char('Sequence', readonly=True, default="/", copy=False)
    currency_id = fields.Many2one('res.currency', string='Devise', readonly=True)
    opening_currency_rate = fields.Float(' Commission Currency rate', digits=(12, 6), default=1.0)
    opening_currency_rate_visible = fields.Boolean('Commission currency rate visible')
    amount_credoc = fields.Monetary('Credit Letter Amount', currency_field='currency_id', states=READONLY_STATES)
    number_credoc = fields.Char("Credit Letter Number", states=READONLY_STATES, required=True)
    code_domiciliation = fields.Char("Bank domicile code", states=READONLY_STATES, required=True)
    bank_id = fields.Many2one('account.journal', 'Bank', domain=[('type', '=', 'bank')], states=READONLY_STATES, required=True)
    partner_id = fields.Many2one('res.partner', 'Supplier', states=READONLY_STATES, domain=[('supplier', '=', True)],
                                 required=True)
    date_start = fields.Date("Openning Date", states=READONLY_STATES, default=fields.Date.today())
    payment_term = fields.Many2one('account.payment.term', 'Payment term', states=READONLY_STATES,
                                       required=True)
    date_due = fields.Date("Due Date", compute='_compute_date_due', readonly=True)
    deposit_percentage = fields.Percent('Déposit in %', states=READONLY_STATES, required=True)
    amount_deposit = fields.Monetary('Deposit Amount', compute='_get_deposit_amount', currency_field='currency_id', readonly=True)

    company_currency_id = fields.Many2one('res.currency', string='Company Currency', readonly=True, )
    commission = fields.Monetary("Commission", currency_field='company_currency_id', states=READONLY_STATES, required=True)
    commission_move_id = fields.Many2one('account.move', "Commission Account Move")

    state = fields.Selection([('draft', 'Draft'), ('open', 'En Cours'), ('closed', 'Fermé'), ('cancel', 'Annulé')],
                              string="Status", default='draft')
    deposit_ids = fields.One2many('credoc.deposit', 'credoc_id', 'Deposit')

    order_ids = fields.One2many('purchase.order.line', 'credoc_id', 'Commandes')
    ordered_amount = fields.Monetary('Orders Amount', currency_field='currency_id', compute='_get_ordered_amount')

    stock_move_ids = fields.One2many('stock.move', 'credoc_id', 'Product Received')

    # TODO: domaine pour invoice lineids
    invoice_ids = fields.One2many('account.invoice.line', 'credoc_id', 'Product Invoiced', domain=[('state', 'not in', ['draft', 'cancel'])])
    invoiced_amount = fields.Monetary('Invoiced Amount', currency_field='currency_id', compute='_get_invoiced_amount')

    # payment_ids = fields.Many2many('account.payment', string='Payments', related='invoice_ids.invoice_id.payment_ids')
    payment_ids = fields.Many2many('account.payment', string='Payments', compute='_get_payment_ids')
    paid_amount = fields.Monetary('Paid Amount', currency_field='currency_id', compute='_get_payment_ids')

    retrocession_ids = fields.One2many('credoc.retrocession', 'credoc_id', string='Retrocession')


    def set_local_amount_currency(self):
        for r in self:
            for p in r.deposit_ids:
                p.local_amount = p.move_id.amount
            for p in r.payment_ids:
                p.local_amount = p.move_id.amount
            for p in r.retrocession_ids:
                p.local_amount = p.move_id.amount


    def create_return_deposit(self):
        RetrocessionWizard = self.env['credoc.retrocession.wizard']

        # 'amount_paid': sum([p.amount for p in self.payment_ids]),
        # 'total_deposit': sum([p.amount_deposit for p in self.deposit_ids]),
        # 'total_retrocession': sum([p.amount_paid for p in self.retrocession_ids]),
        # 'total_credoc': sum([p.amount_credoc for p in self.deposit_ids]),
        # 'percent_of_deposit': self.company_currency_id.round(100 * self.amount_paid / self.total_credoc),
        # 'amount_to_pay': self.total_deposit * self.amount_paid / self.total_credoc,
        # 'amount_to_pay_company_currency': self.currency_rate * self.amount_to_pay,

        wiz = RetrocessionWizard.create({
            'payment_ids': [(4, p.id) for p in self.payment_ids.filtered(lambda r: r not in self.retrocession_ids.mapped('payment_ids'))],
            'credoc_id': self.id,
            'currency_rate': self.opening_currency_rate,
        })
        view = self.env.ref('credoc.credoc_retrocession_wizard_form')
        action = RetrocessionWizard.get_formview_action()
        action['res_id'] = wiz.id
        action['view_id'] = view.id
        action['target'] = 'new'
        return action

    @api.onchange("currency_id")
    def _get_currency_rate_visible(self):
        if self.currency_id:
            self.opening_currency_rate_visible = False
            if self.currency_id != self.env.user.company_id.currency_id:
                self.opening_currency_rate_visible = True

    @api.multi
    @api.depends('date_start', 'payment_term')
    def _compute_date_due(self):
        # self.ensure_one()
        for record in self:
            delta = record.payment_term.line_ids.days
            date_start = record.date_start
            date_due = date_start + timedelta(days=delta)
            record.date_due = date_due

    @api.depends('order_ids')
    def _get_ordered_amount(self):
        self.ensure_one()
        self.ordered_amount = sum([order.price_total for order in self.order_ids])
        if self.ordered_amount > self.amount_credoc:
            UserError("Dépassement de la limite de crédit. Pensez à réajuster le montant de la ligne de crédit")

    @api.depends('invoice_ids')
    def _get_invoiced_amount(self):
        self.ensure_one()
        self.invoiced_amount = sum([invoice.price_total for invoice in self.invoice_ids])
        if self.invoiced_amount > self.amount_credoc:
            exceptions.UserError("Dépassement de la limité de crédit, Pensez à réajuster le montant de la ligne de crédit")

    @api.multi
    @api.onchange('bank_id')
    def _get_currency(self):
        self.ensure_one()
        self.currency_id = self.bank_id.currency_id or self.env.user.company_id.currency_id
        self.company_currency_id = self.env.user.company_id.currency_id

    @api.multi
    @api.depends('deposit_percentage', 'amount_credoc')
    def _get_deposit_amount(self):
        self.ensure_one()
        if not self.deposit_ids:
            self.amount_deposit = self.deposit_percentage * self.amount_credoc / 100
        else:
            self.amount_deposit = sum([r.amount_deposit for r in self.deposit_ids])
            self.amount_credoc = sum([r.amount_credoc for r in self.deposit_ids])

    @api.multi
    def open_credoc(self):
        self.ensure_one()
        if self.name == '/':
            self.name = self.env['ir.sequence'].next_by_code('credoc.credoc')
        # TODO: Création du déposit
        deposit_id = self.set_deposit()
        for deposit in self.deposit_ids:

            if not deposit.move_id and deposit_id != 'draft':
                deposit.set_deposit_move()


        # TODO: Création du déposit
        self.commission_move_id = self._set_commissions_move()

        self.state = 'open'

    def close_credoc(self):
        self.ensure_one()
        # Vérification si deposit == retrocession
        if not sum([r.amount_deposit for r in self.deposit_ids]) == sum([r.amount_paid for r in self.retrocession_ids]):
            raise UserError(_("""Deposit total amount must be aqual to the retrocessions total amount"""))
        # Vérification si facture payé
        if not all([state == 'paid' for state in self.invoice_ids.mapped("state")]):
            raise UserError(_("Error"), _("""All invoices must be in paid state"""))
        self.state = 'closed'
        print('Fermerture de credoc')

    def cancel_credoc(self):
        self.ensure_one()
         # Annuler retrocession
         # Annuler deposit
         # Vérifier si pas de facture ni de BL
        # self.state = 'draft'
        print('Annulation de credoc')

    def _set_commissions_move(self):
        self.ensure_one()
        am_pool = self.env['account.move']
        aml_pool = self.env['account.move.line']

        #PC
        val_pc = {
            'company_id': self.env.user.company_id.id,
            'journal_id': self.bank_id.id,
            'date': self.date_start,
            'ref': self.name + ' - ' + "Commision d'ouverture"
        }

        am_id = am_pool.create(val_pc)
        credoc_conf = self._get_configuration()
        aml_debit = {
            'name': self.name + ' - ' + "Commision d'ouverture",
            'account_id': credoc_conf.commission_account.id,
            'move_id': am_id.id,
            'debit': self.commission,
            'credit': 0,
        }
        aml_credit = {
            'name': self.name + " - "+ "Commision d'ouverture",
            'account_id': self.bank_id.default_credit_account_id.id,
            'move_id': am_id.id,
            'debit': 0,
            'credit': self.commission,
        }

        aml_debit.update(val_pc)
        aml_credit.update(val_pc)
        aml_pool.create([aml_debit, aml_credit])

        am_id.post()
        return am_id

    def _get_configuration(self):
        credoc_account = self.env['credoc.configuration'].search([
            ('id', '=', self.env.ref('credoc.credoc_main_configuration').id)])
        if not credoc_account:
            raise exceptions.except_orm("Attention", """ Aucune configuration n'a été trouvé concernant les comptes de gestion
            des crédits documentaire""")
        if not credoc_account.deposit_account:
            raise exceptions.except_orm("Attention", """ Aucun compte de déposit n'a été trouvé concernant la gestion
            des crédits documentaire""")
        if not credoc_account.commission_account:
            raise exceptions.except_orm("Attention", """ Aucun compte de commission n'a été trouvé concernant la gestion
            des crédits documentaire""")
        return  credoc_account

    @api.model
    def get_partner_credoc(self, partner_id):
        credoc_ids = [i.id for i in self.search([('partner_id', '=', partner_id.id), ('state', '=', 'open')])]
        return credoc_ids

    @api.multi
    def set_deposit(self, date_start=None, new_amount_credoc=None):
        if not self.deposit_ids:
            new_amount_credoc = self.amount_credoc
            current_amount_credoc = 0
        else:
            current_amount_credoc = sum([d.amount_credoc for d in self.deposit_ids])
            assert new_amount_credoc != 0

        diff_amount_credoc = new_amount_credoc - current_amount_credoc
        if diff_amount_credoc == 0:
            return False

        vals = {
            'deposit_date': date_start or self.date_start,
            'credoc_id': self.id,
            'currency_id': self.currency_id.id,
            'amount_credoc': diff_amount_credoc,
            'amount_deposit': diff_amount_credoc * self.deposit_percentage / 100,
            'state': 'draft'
        }
        deposit_id = self.env['credoc.deposit'].create(vals)
        self.amount_credoc = sum([r.amount_credoc for r in self.deposit_ids])

        return deposit_id


class CredocDeposit(models.Model):
    _name = 'credoc.deposit'
    _description = "Gestion des déposits"

    deposit_date = fields.Date('Date', required=True)
    credoc_id = fields.Many2one('credoc.credoc', 'Letter Credit', required=True)
    move_id = fields.Many2one('account.move', 'Account Move')
    currency_id = fields.Many2one('res.currency', 'Currency', readonly=True)
    amount_credoc = fields.Monetary('Montant Crédit', currency_field='currency_id', required=True)
    amount_deposit = fields.Monetary('Montant Deposit', currency_field='currency_id', required=True)

    company_currency_id = fields.Many2one('res.currency', string='Company Currency', related='credoc_id.company_currency_id', readonly=True, default=lambda self: self.env.user.company_id.currency_id)

    company_currency_id = fields.Many2one('res.currency', string='Company Currency', related='credoc_id.company_currency_id', readonly=True, default=lambda self: self.env.user.company_id.currency_id)
    amount_company_currency = fields.Monetary(string='Amount on Company Currency', related='move_id.amount', currency_field='company_currency_id')

    state = fields.Selection([('draft', 'Non Comptabilisé'), ('open', 'A retourné'), ('done', 'Retourné')], string='statut',
                             default='draft', required=True)

    @api.multi
    @api.onchange('bank_id')
    def _get_currency(self):
        self.ensure_one()
        self.currency_id = self.credoc_id.currency_id

    @api.multi
    def confirm(self):
        # move_id = self.create_account_move()
        # aml_ids = self.create_account_move()
        # for line in aml_ids:
        #     line['journal_id'] = move_id.journal_id.id
        #     line['date'] = self.deposit_date
        #     line['ref'] = move_id.name
        #     line['move_id'] = move_id.id
        # aml_ids = self.env['account.move.line'].create(aml_ids)
        deposit_id = self.credoc_id.set_deposit(self.deposit_date, self.amount_credoc)
        return True

    def set_deposit_move(self):
        self.ensure_one()
        am_pool = self.env['account.move']
        aml_pool = self.env['account.move.line']
        credoc_id = self.credoc_id
        operation = 'Déposit'
        #PC
        val_pc = {
            'company_id': credoc_id.env.user.company_id.id,
            'journal_id': credoc_id.bank_id.id,
            'date': self.deposit_date,
            'ref': credoc_id.name + ' - ' + operation,
            'currency_id': credoc_id.currency_id.id
        }

        am_id = am_pool.create(val_pc)
        credoc_conf = credoc_id._get_configuration()

        force_currency_rate = self.credoc_id.opening_currency_rate
        if self.env.context.get('force_currency_rate', False):
            force_currency_rate = self.env.context.get('force_currency_rate')

        res = aml_pool._compute_amount_fields(self.amount_deposit, credoc_id.currency_id.with_context(
            force_currency_rate=force_currency_rate), credoc_id.company_currency_id)
        # price_unit = , credoc_id.currency_id.with_context(force_currency_rate=self.credoc_id.opening_currency_rate)._convert(self.amount_deposit, self.company_id, self.date_order or fields.Date.today(), round=False)
        aml_debit = {
            'name': credoc_id.name + ' - ' + operation,
            'account_id': credoc_conf.deposit_account.id,
            'move_id': am_id.id,
            'amount_currency': self.amount_deposit,
            'debit': res[0],
            'credit': res[1],
        }
        aml_credit = {
            'name': credoc_id.name + " - " + operation,
            'account_id': credoc_id.bank_id.default_credit_account_id.id,
            'amount_currency': -1*self.amount_deposit,
            'move_id': am_id.id,
            'debit': res[1],
            'credit': res[0],
        }
        aml_debit.update(val_pc)
        aml_credit.update(val_pc)
        aml_pool.create([aml_debit, aml_credit])

        self.move_id = am_id.id
        self.state = 'open'
        am_id.post()
        return am_id

    @api.multi
    def set_account_moves_line(self):
        self.ensure_one()
        credoc_account = self.env['credoc.configuration'].get_credoc_account()
        bank_move_line = {
            'account_id': self.amount_deposit > 0 and self.credoc_id.bank_id.default_debit_account_id.id or
                          self.credoc_id.bank_id.default_credit_account_id.id,
            'name': self.credoc_id.name - "Déposit",
            'debit': self.amount_deposit < 0 and abs(self.amount_deposit) or 0.0,
            'credit': self.amount_deposit > 0 and self.amount_deposit or 0.0,
        }
        deposit_move_line = {
            'account_id': credoc_account.commission_account.id,
            'name': self.credoc_id.name - "Déposit",
            'debit': self.amount_deposit > 0 and self.amount_deposit or 0.0,
            'credit': self.amount_deposit < 0 and abs(self.amount_deposit) or 0.0,
        }
        return [deposit_move_line, bank_move_line]

    def create_account_move(self):
        self.ensure_one()
        vals={
            'name': self.credoc_id.name + ":Deposit",
            'journal_id': self.credoc_id.bank_id.id,
            'date': self.deposit_date,
            'state': 'draft',
            'company_id': self.env.user.company_id.Id,
        }
        return self.env['account.move'].create([vals])

    def return_deposit(self):
        print('Return deposit')

    # def get_local_currency_amount(self):


class CredocRetrocession(models.Model):
    _name = 'credoc.retrocession'
    _description = "Documentary letter Deposit Refund - Retrocession"
    _order = 'date desc'

    @api.depends('move_id')
    def compute_state(self):
        for r in self:
            if r.move_id:
                r.state = 'done'
            else:
                r.state = 'draft'

    date = fields.Date('Date', required=True)
    credoc_id = fields.Many2one('credoc.credoc', 'Documentary Credit', required=True)
    move_id = fields.Many2one('account.move', 'Account Move', on_delete='cascade')
    currency_id = fields.Many2one('res.currency', 'Devise', related='credoc_id.currency_id', readonly=True)

    amount_paid = fields.Monetary('Amount Paid', currency_field='currency_id', required=True)
    deposit_id = fields.Many2one('credoc.deposit', 'Retrocession')
    #
    # invoice_ids = fields.Many2many('account.invoice', 'Invoice', domain=lambda self: [('order_id', '=', self.credoc_id.id)])
    # payment_ids = fields.Many2many('account.payment', string='Payments',  domain=lambda self: [('id', 'in', self.mapped('invoice_ids.payment_ids').ids)])
    payment_ids = fields.Many2many('account.payment', string='Payments')

    company_currency_id = fields.Many2one('res.currency', string='Company Currency', related='credoc_id.company_currency_id', readonly=True, default=lambda self: self.env.user.company_id.currency_id)

    amount_company_currency = fields.Monetary('Amount on Company Currency', currency_field='company_currency_id', default=0.0)

    state = fields.Selection( related='move_id.state', string='statut', default='draft', required=True)
    #
    #
    # @api.onchange('invoice_id')
    # def get_invoice_amount(self):
    #
    #     amount_du = self.residual
    #     float_is_zero(amount_du, self.currency_id.rounding)
    #
    #     amount_paid = sum(self.mapped('payment_ids.amount'))
    #     float_is_zero(amount_paid, self.currency_id.rounding)
    #
    #     pass

    #

    @api.multi
    def confirm(self):
        for r in self.filtered(lambda x: x.state != 'done'):
            move_id = r.create_move()
            move_id.post()
            r.move_id = move_id.id
        return True

    @api.multi
    def create_move(self):
        self.ensure_one()
        am_pool = self.env['account.move']
        aml_pool = self.env['account.move.line']

        force_currency_rate = self.credoc_id.opening_currency_rate
        if self.env.context.get('force_currency_rate', False):
            force_currency_rate = self.env.context.get('force_currency_rate')

        name = self.credoc_id.name + ' - ' + _('Retrocession for payments : ') + ' / '.join(self.payment_ids.mapped('payment_group_id.name'))

        val_pc = {
            'company_id': self.env.user.company_id.id,
            'journal_id': self.credoc_id.bank_id.id,
            'date': self.date,
            'ref': name,
            'currency_id': self.currency_id.id
        }

        credoc_conf = self.credoc_id._get_configuration()

        amount_company_currency = self.amount_company_currency
        bank_move_line = (0, 0,{
            'name': name,
            'account_id': amount_company_currency >= 0 and self.credoc_id.bank_id.default_debit_account_id.id
                          or self.credoc_id.bank_id.default_credit_account_id.id,
            'currency_id': self.currency_id.id,
            'amount_currency': self.amount_paid,
            'debit': amount_company_currency >= 0 and amount_company_currency or 0.0,
            'credit': amount_company_currency <= 0 and abs(amount_company_currency) or 0.0,
        })
        deposit_move_line = (0, 0,{
            'name': name,
            'account_id': credoc_conf.deposit_account.id ,
            'currency_id': self.currency_id.id,
            'amount_currency': -1 * self.amount_paid,
            'debit': amount_company_currency <= 0 and abs(amount_company_currency) or 0.0,
            'credit': amount_company_currency >= 0 and amount_company_currency or 0.0,
        })

        val_pc['line_ids'] = [deposit_move_line, bank_move_line]
        am_id = am_pool.create(val_pc)
        print(am_id)
        return am_id

    @api.multi
    def unlink(self):
        for r in self:
            if r.credoc_id.state != 'open':
                raise exceptions.UserError(_("""To cancel a retrocession, the documentary credit letter must be in 'open' state. """))
            if r.move_id:
                if self.move_id.state == 'posted':
                    self.move_id.button_cancel()
                    self.move_id.unlink()
            self.payment_ids = [(5, )]
        res = super(CredocRetrocession, self).unlink()
        return res


class CredocAdjustment(models.TransientModel):
    _name = 'credoc.adjustment'
    _description = "Interface d'ajustement de crédit"

    date_start = fields.Date(string='Date', required=True, help="""Accounting date""")
    credoc_id = fields.Many2one('credoc.credoc', 'Letter Credit', required=True, readonly=True)

    currency_id = fields.Many2one('res.currency', 'Devise', related='credoc_id.currency_id', readonly=True)
    currency_rate = fields.Float('Currency rate', digits=(12, 6), default=1.0)
    opening_currency_rate_visible = fields.Boolean('Currency rate visible')

    company_currency_id = fields.Many2one('res.currency', string='Company Currency', related='credoc_id.company_currency_id', readonly=True, default=lambda self: self.env.user.company_id.currency_id)

    # local_amount = fields.Monetary('Local currency amount', related='move_id.amount', currency_field='company_currency_id', required=True)
    amount_credoc = fields.Monetary(string='Nouvelle Valeur du crédit', currency_field='currency_id', required=True,
                                    help="""Saisir la nouvelle valeur de la ligne de crédit""")


    @api.multi
    @api.onchange('credoc_id')
    def get_currency(self):
        for record in self:
            record.currency_id = record.credoc_id.currency_id

    @api.multi
    def confirm(self):
        deposit_id = self.credoc_id.with_context(force_currency_rate=self.currency_rate).set_deposit(self.date_start, self.amount_credoc)
        deposit_id.with_context(force_currency_rate=self.currency_rate).set_deposit_move()

    @api.model
    def get_credoc_account(self):
        self.ensure_one()
        """ Création de pièce comptable"""
        credoc_account = self.search([('id', '=', self.env.ref('credoc.credoc_main_configuration').id)])
        if not credoc_account:
            raise exceptions.except_orm("Attention", """ Aucune configuration n'a été trouvé concernant les comptes de gestion
            des crédits documentaire""")
        if not credoc_account.deposit_account:
            raise exceptions.except_orm("Attention", """ Aucun compte de déposit n'a été trouvé concernant la gestion
            des crédits documentaire""")
        if not credoc_account.commission_account:
            raise exceptions.except_orm("Attention", """ Aucun compte de commission n'a été trouvé concernant la gestion
            des crédits documentaire""")
        return credoc_account


class CredocRetrocessionWizard(models.TransientModel):
    _name = 'credoc.retrocession.wizard'
    _description = 'Retrocession process wizard'

    @api.multi
    @api.depends('credoc_id', 'payment_ids')
    def _get_amount(self):
        self.ensure_one()
        self.amount_paid = sum([p.amount for p in self.payment_ids])
        self.total_deposit = sum([p.amount_deposit for p in self.credoc_id.deposit_ids])
        self.total_retrocession = sum([p.amount_paid for p in self.credoc_id.retrocession_ids])
        self.total_credoc = sum([p.amount_credoc for p in self.credoc_id.deposit_ids])
        self.percent_of_deposit = self.company_currency_id.round(100 * self.amount_paid / self.total_credoc)
        self.amount_to_pay = self.total_deposit * self.amount_paid / self.total_credoc
        self.amount_to_pay_company_currency = self.currency_rate * self.amount_to_pay

    date = fields.Date("Accounting Date", default=fields.Date.today())
    credoc_id = fields.Many2one('credoc.credoc')
    partner_id = fields.Many2one('res.partner', related='credoc_id.partner_id')
    payment_ids = fields.Many2many('account.payment', string='Payments')
    company_currency_id = fields.Many2one('res.currency', string='Company Currency', related='credoc_id.company_currency_id', readonly=True, default=lambda self: self.env.user.company_id.currency_id)

    currency_id = fields.Many2one('res.currency', 'Devise', related='credoc_id.currency_id', readonly=True)

    amount_paid = fields.Monetary('Amount Paid', currency_field='currency_id', compute=_get_amount, required=True)
    total_credoc = fields.Monetary('Credoc Amount', currency_field='currency_id', compute=_get_amount, required=True)
    total_deposit = fields.Monetary('Total Deposit', currency_field='currency_id', compute=_get_amount, required=True)
    total_retrocession = fields.Monetary('Total Retrocession', currency_field='currency_id', compute=_get_amount, required=True)
    percent_of_deposit = fields.Percent('% of the deposit', compute=_get_amount, readonly=True)

    amount_to_pay = fields.Monetary('Amount to pay', currency_field='currency_id', compute=_get_amount,  required=True)
    currency_rate = fields.Float('Currency rate', digits=(2, 9))
    amount_to_pay_company_currency = fields.Monetary(string='Amount on Company Currency', currency_field='company_currency_id')

    @api.multi
    @api.onchange('amount_to_pay_company_currency')
    def onchange_amount_to_pay_company_currency(self):
        if self.amount_to_pay_company_currency:
            self.currency_rate = self.amount_to_pay_company_currency / self.amount_to_pay
            # currency_rate = self.amount_to_pay_company_currency / self.amount_to_pay
            # self.write({'currency_rate': currency_rate})

    @api.multi
    @api.onchange('currency_rate')
    def onchange_currency_rate(self):
        if self.currency_rate:
            self.amount_to_pay_company_currency = self.currency_rate * self.amount_to_pay
            # amount_to_pay_company_currency = self.currency_rate * self.amount_to_pay
            # self.write({'amount_to_pay_company_currency': amount_to_pay_company_currency})

    def confirm(self):
        val = {
            'date': self.date,
            'credoc_id': self.credoc_id.id,
            'currency_id': self.currency_id.id,
            'amount_paid': self.amount_to_pay,
            'amount_company_currency': self.amount_to_pay_company_currency,
            'payment_ids': [(4, p) for p in self.payment_ids.ids],
            'state': 'draft',
        }
        retrocession_id = self.env['credoc.retrocession'].create([val])
        retrocession_id.confirm()

