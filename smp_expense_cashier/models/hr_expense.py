# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import email_split, float_is_zero

from odoo.addons import decimal_precision as dp


class HrExpense(models.Model):

    _inherit = "hr.expense"

    payment_mode = fields.Selection([
        ("own_account", "Employee (to reimburse)"),
        ("company_account", "Company")
    ], default='company_account',
        states={'done': [('readonly', True)], 'approved': [('readonly', True)], 'reported': [('readonly', True)]},
        string="Paid By")
    bank_statement_line_id = fields.Many2one('account.bank.statement.line', string='Cashier', ondelete='cascade')


    @api.onchange('product_id')
    def _onchange_product_id(self):
        res = super(HrExpense,self)._onchange_product_id()
        if self.product_id:
            self.name = self.product_id.display_name or ''
        if self.sheet_id:
            self.employee_id = self.sheet_id.employee_id

    def prepare_bank_statement_line(self):
        bank_statement = self.get_bank_statement()
        # self.sheet_id.bank_statement_id = bank_statement
        partner_id = self.employee_id.address_id if self.payment_mode else self.employee_id.address_id
        res = {
            'date': self.date,
            'name': self.name,
            'ref': self.sheet_id.name,
            'amount': -1 * self.total_amount,
            'statement_id': bank_statement.id,
            'expense_id': self.id,
            'partner_id': self.employee_id.address_id.id,
        }
        return res

    @api.multi
    def action_move_create_old(self):
        '''
        main function that is called when trying to create the accounting entries related to an expense
        '''
        move_group_by_sheet = self._get_account_move_by_sheet()

        move_line_values_by_expense = self._get_account_move_line_values()

        for expense in self:
            company_currency = expense.company_id.currency_id
            different_currency = expense.currency_id != company_currency

            # get the account move of the related sheet
            move = move_group_by_sheet[expense.sheet_id.id]

            # get move line values
            move_line_values = move_line_values_by_expense.get(expense.id)
            move_line_dst = move_line_values[-1]
            total_amount = move_line_dst['debit'] or -move_line_dst['credit']
            total_amount_currency = move_line_dst['amount_currency']

            # create one more move line, a counterline for the total on payable account
            if expense.payment_mode == 'company_account':
                if not expense.sheet_id.bank_journal_id.default_credit_account_id:
                    raise UserError(_("No credit account found for the %s journal, please configure one.") % (expense.sheet_id.bank_journal_id.name))
                journal = expense.sheet_id.bank_journal_id
                # create payment
                payment_methods = journal.outbound_payment_method_ids if total_amount < 0 else journal.inbound_payment_method_ids
                journal_currency = journal.currency_id or journal.company_id.currency_id
                payment = self.env['account.payment'].with_context(create_from_expense=True).create({
                    'payment_method_id': payment_methods and payment_methods[0].id or False,
                    'payment_type': 'outbound' if total_amount < 0 else 'inbound',
                    'partner_id': expense.employee_id.address_home_id.commercial_partner_id.id,
                    'partner_type': 'supplier',
                    'journal_id': journal.id,
                    'payment_date': expense.date,
                    'state': 'reconciled',
                    'currency_id': expense.currency_id.id if different_currency else journal_currency.id,
                    'amount': abs(total_amount_currency) if different_currency else abs(total_amount),
                    'name': expense.name,
                })
                move_line_dst['payment_id'] = payment.id

            # link move lines to move, and move to expense sheet
            move.with_context(dont_create_taxes=True).write({
                'line_ids': [(0, 0, line) for line in move_line_values]
            })
            expense.sheet_id.write({'account_move_id': move.id})

            if expense.payment_mode == 'company_account':
                expense.sheet_id.paid_expense_sheets()

        # post the moves
        for move in move_group_by_sheet.values():
            move.post()
            # on fitre les écritures de journaux qu'il faut reconcilier
            for line in move.line_ids.filtered(lambda x: x.expense_id
                                                         and (x.account_id == journal.default_credit_account_id
                                                              or x.account_id == journal.default_debit_account_id)):
                if line.expense_id.payment_mode == 'company_account':
                    # On créee la ligne de relevé bancaire
                    bank_statement_line_id = line.expense_id.prepare_bank_statement_line()
                    line.expense_id.bank_statement_line_id = self.env['account.bank.statement.line'].create([bank_statement_line_id])
                    # On reconcilie la ligne avec la ligne comptable
                    line.expense_id.bank_statement_line_id.journal_entry_ids = [(4, line.id)]
        return move_group_by_sheet

    def action_move_create(self):
        '''
        main function that is called when trying to create the accounting entries related to an expense
        '''
        move_group_by_sheet = self._get_account_move_by_sheet()

        move_line_values_by_expense = self._get_account_move_line_values()

        """ Création d'un paiement contenant  toute les lignes par sheet"""
        for sheet_id in self.mapped('sheet_id'):
            total_amount = - sheet_id.total_amount
            if sheet_id.expense_line_ids.filtered(lambda x: x.payment_mode == 'company_account'):
                company_id = sheet_id.journal_id.company_id.id
                vals = {
                        'company_id': company_id,
                        'partner_type': 'supplier',
                        'partner_id': sheet_id.employee_id.address_id.id,
                        'payment_date': sheet_id.accounting_date or fields.Date.context_today(self),
                        # 'communication': vals.get('communication'),
                    }
                payment_group = self.env['account.payment.group'].create(vals)

            for expense in sheet_id.expense_line_ids:
                company_currency = expense.company_id.currency_id
                different_currency = expense.currency_id != company_currency

                # get the account move of the related sheet
                move = move_group_by_sheet[expense.sheet_id.id]

                # get move line values
                move_line_values = move_line_values_by_expense.get(expense.id)
                move_line_dst = move_line_values[-1]
                total_amount = move_line_dst['debit'] or -move_line_dst['credit']
                total_amount_currency = move_line_dst['amount_currency']

                # create one more move line, a counterline for the total on payable account
                if expense.payment_mode == 'company_account':
                    if not expense.sheet_id.bank_journal_id.default_credit_account_id:
                        raise UserError(_("No credit account found for the %s journal, please configure one.") % (expense.sheet_id.bank_journal_id.name))
                    journal = expense.sheet_id.bank_journal_id
                    # create payment
                    payment_methods = journal.outbound_payment_method_ids if total_amount < 0 else journal.inbound_payment_method_ids
                    journal_currency = journal.currency_id or journal.company_id.currency_id
                    payment = self.env['account.payment'].with_context(create_from_expense=True, payment_group_id=payment_group).create({
                        'payment_method_id': payment_methods and payment_methods[0].id or False,
                        'payment_type': 'outbound' if total_amount < 0 else 'inbound',
                        'partner_id': expense.employee_id.address_home_id.commercial_partner_id.id,
                        'partner_type': 'supplier',
                        'journal_id': journal.id,
                        'payment_date': expense.date,
                        'state': 'reconciled',
                        'currency_id': expense.currency_id.id if different_currency else journal_currency.id,
                        'amount': abs(total_amount_currency) if different_currency else abs(total_amount),
                        'name': expense.name,
                    })
                    move_line_dst['payment_id'] = payment.id

                # link move lines to move, and move to expense sheet
                move.with_context(dont_create_taxes=True).write({
                    'line_ids': [(0, 0, line) for line in move_line_values]
                })
                expense.sheet_id.write({'account_move_id': move.id})

                if expense.payment_mode == 'company_account':
                    expense.sheet_id.paid_expense_sheets()


        # post the moves
        for move in move_group_by_sheet.values():
            move.post()
            # on fitre les écritures de journaux qu'il faut reconcilier
            for line in move.line_ids.filtered(lambda x: x.expense_id and journal.is_bank_statement
                                                         and (x.account_id == journal.default_credit_account_id
                                                              or x.account_id == journal.default_debit_account_id)):
                if line.expense_id.payment_mode == 'company_account':
                    """on met à jour bank statemt line """

                    # On créee la ligne de relevé bancaire
                    # bank_statement_line_id = line.statement_line_id.id
                    # bank_statement_line_id.ref = line.expense_id.name
                    bank_statement_line_id = line.expense_id.prepare_bank_statement_line()
                    line.expense_id.bank_statement_line_id = self.env['account.bank.statement.line'].create([bank_statement_line_id])
                    # On reconcilie la ligne avec la ligne comptable
                    line.expense_id.bank_statement_line_id.journal_entry_ids = [(4, line.id)]
        return move_group_by_sheet

    def get_bank_statement(self):
        self.ensure_one()
        BankStatement = self.env['account.bank.statement']
        account_date = self.sheet_id.accounting_date or self.date
        journal_id = self.sheet_id.bank_journal_id.id
        # statement_id = BankStatement.search([('journal_id', '=', journal_id)])
        statement_id = BankStatement.search([('journal_id', '=', journal_id), ('state', '=', 'open'),  ('date', '<=', account_date)])

        if not statement_id:
            raise UserError("""Veuillez créer un relevé de caisse ouverte à la journée du %s!!! """ % self.date)
        statement_id.ensure_one()
        return statement_id


class HrExpenseSheet(models.Model):
    """
        Here are the rights associated with the expense flow

        Action       Group                   Restriction
        =================================================================================
        Submit      Employee                Only his own
                    Officer                 If he is expense manager of the employee, manager of the employee
                                             or the employee is in the department managed by the officer
                    Manager                 Always
        Approve     Officer                 Not his own and he is expense manager of the employee, manager of the employee
                                             or the employee is in the department managed by the officer
                    Manager                 Always
        Post        Anybody                 State = approve and journal_id defined
        Done        Anybody                 State = approve and journal_id defined
        Cancel      Officer                 Not his own and he is expense manager of the employee, manager of the employee
                                             or the employee is in the department managed by the officer
                    Manager                 Always
        =================================================================================
    """
    _inherit = "hr.expense.sheet"

    bank_statement_id = fields.Many2one('account.bank.statement', string='Relevé Bancaire', ondelete='cascade',readonly=True)
    name = fields.Char('Expense Report Summary', required=True, default="/")

    @api.multi
    def action_submit_sheet(self):
        # if self.name == '/':
        for sheet in self:
            name = self.env['ir.sequence'].next_by_code('hr.expense.sheet')
            self.name = name
            res = super(HrExpenseSheet, sheet).action_submit_sheet()

    @api.multi
    def action_sheet_move_create(self):
        res = super(HrExpenseSheet, self).action_sheet_move_create()
        bank_statement_id = self.mapped('expense_line_ids.bank_statement_line_id.statement_id')
        bank_statement_id.ensure_one()
        self.bank_statement_id = bank_statement_id
        return res





