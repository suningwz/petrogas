# -*- coding: utf-8 -*-
import time
from datetime import datetime
from odoo import fields, models, api, _
from odoo.exceptions import except_orm, UserError
from odoo import exceptions
from odoo.tools import float_compare, float_round, float_is_zero

class SalaryAdvancePayment(models.Model):
    _name = "salary.advance"
    _inherit = ['mail.thread', 'mail.activity.mixin']


    @api.one
    @api.depends('account_move_line_ids.amount_residual')
    def _compute_residual(self):
        residual = 0.0
        residual_company_signed = 0.0
        # sign = self.type in ['in_refund', 'out_refund'] and -1 or 1
        if self.journal.type not in ['bank', 'cash'] and self.loan_sal_adv_account_move_separation and self.account_move_line_ids :
            for line in self.account_move_line_ids.filtered(lambda l: l.account_id.id == self.credit.id):
                residual_company_signed += line.amount_residual
                if line.currency_id == self.currency_id:
                    residual += line.amount_residual_currency if line.currency_id else line.amount_residual
                else:
                    from_currency = line.currency_id or line.company_id.currency_id
                    residual += from_currency._convert(line.amount_residual, self.currency_id, line.company_id, line.date or fields.Date.today())
            self.residual = abs(residual)
            digits_rounding_precision = self.currency_id.rounding
            # if float_is_zero(self.residual, precision_rounding=digits_rounding_precision):
            if float_is_zero(residual_company_signed, precision_rounding=digits_rounding_precision):
                self.reconciled = True
                self.write({'state': 'paid'})
            else:
                self.reconciled = False
                self.write({'state': 'confirmed'})

        if self.state == 'paid':
            residual_company_signed = 0.0
            residual = 0.0
            for line in self.account_move_line_ids.filtered(lambda l: l.account_id.id == self.debit.id):
                residual_company_signed += line.amount_residual

                if line.currency_id == self.currency_id:
                    residual += line.amount_residual_currency if line.currency_id else line.amount_residual
                else:
                    from_currency = line.currency_id or line.company_id.currency_id
                    residual += from_currency._convert(line.amount_residual, self.currency_id, line.company_id,
                                                       line.date or fields.Date.today())
                self.residual = abs(residual)
                digits_rounding_precision = self.currency_id.rounding
                # if float_is_zero(self.residual, precision_rounding=digits_rounding_precision):
                if float_is_zero(residual_company_signed, precision_rounding=digits_rounding_precision):
                    self.write({'state': 'refund'})


    name = fields.Char(string='Name', readonly=True, default=lambda self: 'Adv/')
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    job_position = fields.Many2one('hr.job', related="employee_id.job_id", readonly=True, string="Job Position")
    date = fields.Date(string='Date', required=True, default=lambda self: fields.Date.today())
    reason = fields.Text(string='Reason')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                  default=lambda self: self.env.user.company_id.currency_id)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.user.company_id)
    advance = fields.Float(string='Advance', required=True)
    exceed_condition = fields.Boolean(string='Exceed than maximum',
                                      help="The Advance is greater than the maximum percentage in salary structure")
    department = fields.Many2one('hr.department', string='Department')
    state = fields.Selection([('draft', 'Draft'),
                              ('confirmed', 'Confirmed'),
                              ('paid', 'Paid'),
                              ('refund', 'Refunded'),
                              ('cancel', 'Cancelled')], string='Status', default='draft', track_visibility='onchange')
    payment_method = fields.Many2one('account.journal', string='Payment Method')
    # payment_method_ids = fields.Many2many('account.move.line', string='Payment entries')
    payslip_id = fields.Many2one('hr.payslip', string='Payslip')
    employee_contract_id = fields.Many2one('hr.contract', string='Contract')
    debit = fields.Many2one('account.account', string='Debit Account')
    credit = fields.Many2one('account.account', string='Credit Account')
    journal = fields.Many2one('account.journal', string='Journal')
    account_move_line_ids = fields.Many2many('account.move.line', track_visibility='always')
    loan_sal_adv_account_move_separation = fields.Boolean('Account Move Separation')
    reconciled = fields.Boolean(string='Paid/Reconciled', store=True, readonly=True, compute='_compute_residual',
        help="It indicates that the due amount has been paid and the journal entry of the of the advance salary has been reconciled with one or several journal entries of payment.")
    # payslip_reconciled = fields.Boolean(string='Payslip/Reconciled', store=True, readonly=True, compute='_compute_residual')
    residual = fields.Monetary(string='Amount Due',
        compute='_compute_residual', store=True, help="Remaining amount due.")
    # residual_signed = fields.Monetary(string='Amount Due in Invoice Currency', currency_field='currency_id',
    #     compute='_compute_residual', store=True, help="Remaining amount due in the currency of the invoice.")
    # residual_company_signed = fields.Monetary(string='Amount Due in Company Currency', currency_field='company_currency_id',
    #     compute='_compute_residual', store=True, help="Remaining amount due in the currency of the company.")
    # payment_ids = fields.Many2many('account.payment', string="Payments", copy=False, readonly=True)
    # payment_move_line_ids = fields.Many2many('account.move.line', string='Payment Move Lines', compute='_compute_payments', store=True)




    # state = fields.Selection([('draft', 'Draft'),
    #                           ('submit', 'Submitted'),
    #                           ('waiting_approval', 'Waiting Approval'),
    #                           ('approve', 'Approved'),
    #                           ('cancel', 'Cancelled'),
    #                           ('reject', 'Rejected')], string='Status', default='draft', track_visibility='onchange')


    @api.onchange('employee_id')
    def onchange_employee_id(self):
        department_id = self.employee_id.department_id.id
        domain = [('employee_id', '=', self.employee_id.id)]

        # contract_ids = self.get_contract(self.employee_id, self.date, self.date)

        return {'value': {'department': department_id}, 'domain': {
            'employee_contract_id': domain,
        }}

    @api.onchange('company_id')
    def onchange_company_id(self):
        company = self.company_id
        domain = [('company_id.id', '=', company.id)]
        result = {
            'domain': {
                'journal': domain,
            },

        }
        return result

    @api.onchange('journal')
    def get_account(self):
        if self.journal:
            ReSet = self.sudo().env['res.config.settings']
            salary_advance_account_id = ReSet.sudo().get_values()['loan_account']
            employee_payable_account = ReSet.sudo().get_values()['employee_payable_account']
            loan_sal_adv_account_move_separation = ReSet.sudo().get_values()['loan_sal_adv_account_move_separation']
            self.loan_sal_adv_account_move_separation = loan_sal_adv_account_move_separation
            payment_type = 'outbound' if self.advance < 0 else 'inbound'

            if not loan_sal_adv_account_move_separation:
                if not self.journal.type in ['cash', 'bank']:
                    raise UserError(_(
                        "The advance salary confirmation setting is configured to generate directly the payment. So you need to chose a bank or cash journal."))

                if payment_type == 'outbound':
                    if not self.journal.default_debit_account_id:
                        raise UserError(_("No debit account found for the %s journal, please configure one.") % (
                            self.journal.name))
                else:
                    if not self.journal.default_credit_account_id:
                        raise UserError(_("No credit account found for the %s journal, please configure one.") % (
                            self.journal.name))
                counter_part_account = self.journal.default_credit_account_id.id if payment_type == 'outbound' else self.journal.default_debit_account_id.id

            else:
                if self.journal.type in ['cash', 'bank']:
                    raise UserError(_(
                        "The loan or advance salary confirmation setting is configured to not generate directly the payment. So you can't chose a bank or cash journal."))

                if not employee_payable_account:
                    raise UserError(
                        _("Please configure the employee asset provision account int the configuration menu."))
                counter_part_account = employee_payable_account

            self.debit = counter_part_account if payment_type == 'outbound' else salary_advance_account_id
            self.credit = salary_advance_account_id if payment_type == 'outbound' else counter_part_account
            # self.write({'debit':debit, 'credit':credit})


    @api.model
    def create(self, vals):
        vals['name'] = self.env['ir.sequence'].get('salary.advance.seq') or ''
        vals['loan_sal_adv_account_move_separation'] = self.env['res.config.settings'].sudo().get_values()['loan_sal_adv_account_move_separation'] or False
        if vals['loan_sal_adv_account_move_separation']:
            vals['salary_journal'] = self.env['res.config.settings'].sudo().get_values()['salary_journal']
        res_id = super(SalaryAdvancePayment, self).create(vals)
        return res_id

    # @api.model
    # def copy(self, vals):
    #     vals['name'] = ''
    #     vals['loan_sal_adv_account_move_separation'] = self.env['res.config.settings'].get_values()['loan_sal_adv_account_move_separation']
    #     res_id = super(SalaryAdvancePayment, self).copy(vals)
    #     return res_id

    @api.multi
    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.update({
            'name': '',
            'loan_sal_adv_account_move_separation': self.env['res.config.settings'].get_values()['loan_sal_adv_account_move_separation'],
            'date': fields.date.today(),
            'account_move_line_ids': False,
        })
        return super(SalaryAdvancePayment, self).copy(default)

    @api.multi
    def confirm(self):
        self.ensure_one()
        self.name = self.env['ir.sequence'].get('salary.advance.seq') if not self.name else self.name

        salary_advance_search = self.search([('employee_id', '=', self.employee_id.id), ('id', '!=', self.id), ('state', '=', 'approve')])

        current_month = datetime.strptime(str(self.date), '%Y-%m-%d').date().month

        for each_advance in salary_advance_search:
            existing_month = datetime.strptime(str(each_advance.date), '%Y-%m-%d').date().month
            if current_month == existing_month:
                raise except_orm('Error!', 'Advance can be requested once in a month')
        if not self.debit or not self.credit or not self.journal:
            raise except_orm('Warning', "You must enter Debit & Credit account and journal to approve ")
        if not self.advance and self.advance > 0:
            raise except_orm('Warning', 'You must Enter the Salary Advance amount')

        self.sudo().compute_entry_move()
        if not self.loan_sal_adv_account_move_separation and self.journal.type in ['bank', 'cash']:
            self.write({'state': 'paid'})
        else:
            self.write({'state': 'confirmed'})
        self.state ='confirmed'

    @api.one
    def reopen(self):
        assert not self.account_move_line_ids
        self.state = 'draft'

    @api.one
    def cancel(self):
        if self.payslip_id:
            raise UserError(_("""You must cancel the payslip before cancelling the advance"""))
        if self.payment_method:
            raise UserError(_("""You must cancel the payment before cancelling the advance"""))
        self.state = 'cancel'



    @api.multi
    def compute_entry_move(self):
        """This Approve the employee salary advance request from accounting department."""

        move_obj = self.env['account.move']
        timenow = time.strftime('%Y-%m-%d')
        line_ids = []
        debit_sum = 0.0
        credit_sum = 0.0
        for request in self:
            amount = request.advance
            request_name = request.employee_id.name
            reference = request.name
            journal_id = request.journal.id
            journal = request.journal
            move = {
                'narration': _('Salary Advance Of ') + request_name,
                'ref': reference,
                'journal_id': journal_id,
                'date': timenow,
                'state': 'draft',
            }
            debit_account_id = request.debit.id
            credit_account_id = request.credit.id

            if debit_account_id:
                debit_line = (0, 0, {
                    'name': request_name,
                    'account_id': debit_account_id,
                    'journal_id': journal_id,
                    'partner_id': request.employee_id.address_id.id,
                    'date': timenow,
                    'debit': amount > 0.0 and amount or 0.0,
                    'credit': amount < 0.0 and -amount or 0.0,
                    'currency_id': self.currency_id.id,
                })
                line_ids.append(debit_line)
                # debit_sum += debit_line[2]['debit'] - debit_line[2]['credit']

            if credit_account_id:
                credit_line = (0, 0, {
                    'name': request_name,
                    'account_id': credit_account_id,
                    'journal_id': journal_id,
                    'partner_id': request.employee_id.address_id.id,
                    'date': timenow,
                    'debit': amount < 0.0 and -amount or 0.0,
                    'credit': amount > 0.0 and amount or 0.0,
                    'currency_id': self.currency_id.id,
                })
                line_ids.append(credit_line)
                # credit_sum += credit_line[2]['credit'] - credit_line[2]['debit']

            if not self.loan_sal_adv_account_move_separation:
                payment_methods = journal.outbound_payment_method_ids if request.advance < 0 else journal.inbound_payment_method_ids
                payment = self.env['account.payment'].with_context(create_from_expense=True).create({
                    'payment_method_id': payment_methods and payment_methods[0].id or False,
                    'payment_type': 'outbound' if request.advance  < 0 else 'inbound',
                    'partner_id': request.employee_id.address_id.id,
                    'partner_type': 'supplier',
                    'journal_id': journal_id,
                    'payment_date': request.date,
                    'state': 'reconciled',
                    'currency_id': request.currency_id.id,
                    'amount': abs(amount),
                    'name': request.name,
                })

                for line in line_ids:
                    line[2]['payment_id'] = payment.id

            move.update({'line_ids': line_ids})
            move = move_obj.create(move)
            move.post()
            request.account_move_line_ids = [(4, line.id) for line in move.line_ids]

            if not self.loan_sal_adv_account_move_separation and journal.is_bank_statement:
                """ Création ligne de banque"""
                bank_statement = self.env['account.bank.statement'].get_bank_statement(journal, timenow)

                line = move.line_ids.filtered(lambda x: x.account_id == journal.default_credit_account_id
                                                        or x.account_id == journal.default_debit_account_id)
                line.ensure_one()
                bank_statement_line_id = {
                        'date': timenow,
                        'name': request.name + ': Salary advance for ' + request.employee_id.name,
                        'ref': request.name + ': Salary advance for ' + request.employee_id.name,
                        'amount': -1 * request.advance,
                        'statement_id': bank_statement.id,
                        'partner_id': request.employee_id.address_id.id,
                    }
                bank_statement_line_id = self.env['account.bank.statement.line'].create([bank_statement_line_id])
                bank_statement_line_id.journal_entry_ids = [(4, line.id)]

            if not self.loan_sal_adv_account_move_separation:
                self.state = 'paid'
            else:
                self.state = 'confirmed'

            return True


    @api.multi
    def action_get_account_moves(self):
        action = {
            'name': _('Account Move Line'),
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'account.move.line',
            'view_id': False,
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', [x.id for x in self.account_move_line_ids])],
        }
        return action


    class AccountBankStatement(models.Model):
        _inherit = 'account.bank.statement'

        @api.model
        def get_bank_statement(self, journal_id=None, date=fields.date.today()):
            journal_id.ensure_one()
            BankStatement = self.env['account.bank.statement']
            account_date = date
            journal_id = journal_id.id
            statement_id = BankStatement.search([('journal_id', '=', journal_id), ('state', '=', 'open'),  ('date', '<=', account_date)])

            if not statement_id:
                raise UserError("""Ensure that cash register is open at the date %s  and for the journal %s! !! """ % (account_date, journal_id.name ))
            statement_id.ensure_one()
            return statement_id
