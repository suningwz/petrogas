# -*- coding: utf-8 -*-

from odoo import models, fields, api,_
from datetime import datetime,date
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError, UserError, except_orm
from odoo.tools.float_utils import float_round, float_is_zero
import time
import calendar as cal

class HrLoanType(models.Model):
    _name = 'hr.loan.type'
    _description = "Loan Types"

    name = fields.Char(string='Name')
    installment = fields.Integer(string="No Of Installments", default=1)
    is_salary_advance = fields.Boolean(string="Is salary advance type")


class HrLoan(models.Model):
    _name = 'hr.loan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Loan loan"

    @api.model
    def default_get(self, field_list):
        result = super(HrLoan, self).default_get(field_list)
        if result.get('user_id'):
            ts_user_id = result['user_id']
        else:
            ts_user_id = self.env.context.get('user_id', self.env.user.id)
            result['employee_id'] = self.env['hr.employee'].search([('user_id', '=', ts_user_id)], limit=1).id
        return result

    @api.one
    def _compute_loan_amount(self):
        total_paid = 0.0
        for loan in self:
            for line in loan.loan_lines:
                if line.paid:
                    total_paid += line.amount
            balance_amount = loan.loan_amount - total_paid
            self.total_amount = loan.loan_amount
            self.balance_amount = balance_amount
            self.total_paid_amount = total_paid

    @api.one
    @api.depends('account_move_line_ids.amount_residual')
    def _compute_residual(self):
        residual = 0.0
        residual_company_signed = 0.0
        # sign = self.type in ['in_refund', 'out_refund'] and -1 or 1
        if self.journal.type not in ['bank', 'cash'] and self.loan_sal_adv_account_move_separation and self.account_move_line_ids:
            for line in self.account_move_line_ids.filtered(lambda l: l.account_id.id == self.credit.id):
                residual_company_signed += line.amount_residual
                if line.currency_id == self.currency_id:
                    residual += line.amount_residual_currency if line.currency_id else line.amount_residual
                else:
                    from_currency = line.currency_id or line.company_id.currency_id
                    residual += from_currency._convert(line.amount_residual, self.currency_id, line.company_id, line.date or fields.Date.today())
            # self.residual_company_signed = abs(residual_company_signed) * sign
            # self.residual_signed = abs(residual) * sign
            self.residual = abs(residual)
            digits_rounding_precision = self.currency_id.rounding
            # if float_is_zero(self.residual, precision_rounding=digits_rounding_precision):
            if float_is_zero(residual_company_signed, precision_rounding=digits_rounding_precision):
                self.reconciled = True
                self.write({'state': 'paid'})
            else:
                self.reconciled = False
                self.write({'state': 'confirmed'})
        else:
            self.reconciled = False



    name = fields.Char(string="Loan Name", default="/", readonly=True)
    employee_id = fields.Many2one('hr.employee', string="Employee", required=True)
    date = fields.Date(string="Date", default=fields.Date.today())
    department_id = fields.Many2one('hr.department', related="employee_id.department_id", readonly=True,
                                    string="Department")
    loan_type = fields.Many2one('hr.loan.type', string='Loan Type')
    installment = fields.Integer(string="No Of Installments", default=1, store=True)
    loan_lines = fields.One2many('hr.loan.line', 'loan_id', string="Loan Line", index=True)

    # """ Journal de provisionnement """
    payment_date = fields.Date(string="Payment Start Date", required=True, default=fields.Date.today())
    debit = fields.Many2one('account.account', string='Debit Account')
    credit = fields.Many2one('account.account', string='Credit Account')
    journal = fields.Many2one('account.journal', string='Journal')
    account_move_line_ids = fields.Many2many('account.move.line', string='Account Moves Lines', track_visibility='always')

    loan_sal_adv_account_move_separation = fields.Boolean('Account Move Separation')

    # """ Autres Info """
    company_id = fields.Many2one('res.company', 'Company', readonly=True,
                                 default=lambda self: self.env.user.company_id,
                                 states={'draft': [('readonly', False)]})
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                  default=lambda self: self.env.user.company_id.currency_id)
    job_position = fields.Many2one('hr.job', related="employee_id.job_id", readonly=True, string="Job Position")
    loan_amount = fields.Float(string="Loan Amount", required=True)
    total_amount = fields.Float(string="Total Amount", readonly=True, compute='_compute_loan_amount')
    balance_amount = fields.Float(string="Balance Amount", compute='_compute_loan_amount')
    total_paid_amount = fields.Float(string="Total Paid Amount", compute='_compute_loan_amount')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid', 'Paid'),
        ('refund', 'Refund'),
        ('cancel', 'Canceled'),
    ], string="State", default='draft', track_visibility='onchange', copy=False, )
    reconciled = fields.Boolean(string='Paid/Reconciled', store=True, readonly=True, compute='_compute_residual',
        help="It indicates that the invoice has been paid and the journal entry of the invoice has been reconciled with one or several journal entries of payment.")
    residual = fields.Monetary(string='Amount Due',
        compute='_compute_residual', store=True, help="Remaining amount due.")


    @api.onchange('loan_type')
    def get_loan_installment(self):
        if self.loan_type:
            self.installment = self.loan_type.installment
        else:
            self.installment = 1

    @api.onchange('date')
    def get_payment_date(self):
        if self.date:
            self.payment_date = self.date

    @api.onchange('journal', 'loan_type')
    def get_account(self):
        if self.journal and self.loan_type:
            ReSet = self.env['res.config.settings']
            salary_advance_account_id = ReSet.sudo().get_values()['loan_account']
            employee_payable_account = ReSet.sudo().get_values()['employee_payable_account']
            loan_sal_adv_account_move_separation = ReSet.sudo().get_values()['loan_sal_adv_account_move_separation']
            self.loan_sal_adv_account_move_separation = loan_sal_adv_account_move_separation
            payment_type = 'outbound' if self.loan_amount < 0 else 'inbound'

            if not loan_sal_adv_account_move_separation:
                if not self.journal.type in ['cash', 'bank']:
                    raise UserError(_("The advance salary confirmation setting is configured to generate directly the payment. So you need to chose a bank or cash journal."))

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
                    raise UserError(_("The loan or advance salary confirmation setting is configured to not generate directly the payment. So you can't chose a bank or cash journal."))

                if not employee_payable_account:
                    raise UserError(_("Please configure the employee asset provision account int the configuration menu."))
                counter_part_account = employee_payable_account

            self.debit = counter_part_account if payment_type == 'outbound' else salary_advance_account_id
            self.credit = salary_advance_account_id if payment_type == 'outbound' else counter_part_account

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.update({
            'name': '',
            'loan_sal_adv_account_move_separation': self.env['res.config.settings'].get_values()['loan_sal_adv_account_move_separation'],
            'date': fields.date.today(),
            'account_move_line_ids': False,
            'loan_lines': False,
        })
        return super(HrLoan, self).copy(default)

    @api.model
    def create(self, vals):
        vals['name'] = self.env['ir.sequence'].get('hr.loan.seq') or ''
        vals['loan_sal_adv_account_move_separation'] = self.env['res.config.settings'].sudo().get_values()['loan_sal_adv_account_move_separation']
        res_id = super(HrLoan, self).create(vals)
        return res_id

    @api.multi
    def action_confirm(self):
        for loan in self:

            loan_count = loan.search_count(
                [('employee_id', '=', loan.employee_id.id), ('state', '=', 'confirmed')
                    , ('balance_amount', '!=', 0), ('loan_type', '=', loan.loan_type.id)])

            if loan_count:
                raise ValidationError(_("The employee has already a pending installment for the same type of loan."))
            loan.name = self.env['ir.sequence'].get('salary.advance.seq') if not self.name else self.name

            loan.compute_installment()
            loan.compute_entry_move()
            if not self.loan_sal_adv_account_move_separation and self.journal.type in ['bank', 'cash']:
                self.write({'state': 'paid'})
            else:
                self.write({'state': 'confirmed'})

    @api.multi
    def action_cancel(self):
        self.write({'state': 'cancel'})

    @api.multi
    def compute_entry_move(self):

        move_obj = self.env['account.move']
     
        for loan in self:
            timenow = time.strftime('%Y-%m-%d')
            line_ids = []

            doc_name = loan.loan_type.name + ' - ' + loan.employee_id.name

            if not loan.debit or not loan.credit or not loan.journal:
                raise except_orm('Warning', "You must enter Debit & Credit account and journal to approve ")
            if not loan.loan_amount and loan.loan_amount > 0:
                raise except_orm('Warning', 'You must Enter the loan amount')

            amount = loan.loan_amount
            loan_name = loan.employee_id.name
            reference = loan.name
            journal_id = loan.journal.id
            journal = loan.journal
            move = {
                'narration': doc_name,
                'ref': reference,
                'journal_id': journal_id,
                'date': timenow,
                'state': 'draft',
            }
            debit_account_id = loan.debit.id
            credit_account_id = loan.credit.id

            if debit_account_id:
                debit_line = (0, 0, {
                    'name': loan_name + ' / ' + doc_name,
                    'account_id': debit_account_id,
                    'journal_id': journal_id,
                    'partner_id': loan.employee_id.address_id.id,
                    'date': timenow,
                    'debit': amount > 0.0 and amount or 0.0,
                    'credit': amount < 0.0 and -amount or 0.0,
                    'currency_id': self.currency_id.id,
                })
                line_ids.append(debit_line)
                # debit_sum += debit_line[2]['debit'] - debit_line[2]['credit']

            if credit_account_id:
                credit_line = (0, 0, {
                    'name': loan_name + ' / ' + doc_name,
                    'account_id': credit_account_id,
                    'journal_id': journal_id,
                    'partner_id': loan.employee_id.address_id.id,
                    'date': timenow,
                    'debit': amount < 0.0 and -amount or 0.0,
                    'credit': amount > 0.0 and amount or 0.0,
                    'currency_id': self.currency_id.id,
                })
                line_ids.append(credit_line)
                # credit_sum += credit_line[2]['credit'] - credit_line[2]['debit']

            if not self.loan_sal_adv_account_move_separation:
                payment_methods = journal.outbound_payment_method_ids if loan.loan_amount < 0 else journal.inbound_payment_method_ids
                payment = self.env['account.payment'].with_context(create_from_expense=True).create({
                    'payment_method_id': payment_methods and payment_methods[0].id or False,
                    'payment_type': 'outbound' if loan.loan_amount < 0 else 'inbound',
                    'partner_id': loan.employee_id.address_id.id,
                    'partner_type': 'supplier',
                    'journal_id': journal_id,
                    'payment_date': loan.date,
                    'state': 'reconciled',
                    'currency_id': loan.currency_id.id,
                    'amount': abs(amount),
                    'name': loan_name + ' / ' + doc_name,
                })

                for line in line_ids:
                    line[2]['payment_id'] = payment.id

            move.update({'line_ids': line_ids})
            move = move_obj.create(move)
            move.post()
            loan.account_move_line_ids = [(4, line.id) for line in move.line_ids]

            if not self.loan_sal_adv_account_move_separation and journal.is_bank_statement:
                # """ Création ligne de banque"""
                bank_statement = self.env['account.bank.statement'].get_bank_statement(journal, timenow)

                line = move.line_ids.filtered(lambda x: x.account_id == journal.default_credit_account_id
                                                        or x.account_id == journal.default_debit_account_id)
                line.ensure_one()
                bank_statement_line_id = {
                    'date': timenow,
                    'name': loan_name + ' / ' + doc_name,
                    'ref': loan_name + ' / ' + doc_name,
                    'amount': -1 * loan.advance,
                    'statement_id': bank_statement.id,
                    'partner_id': loan.employee_id.address_id.id,
                }
                bank_statement_line_id = self.env['account.bank.statement.line'].create([bank_statement_line_id])
                bank_statement_line_id.journal_entry_ids = [(4, line.id)]

    @api.multi
    def unlink(self):
        for loan in self:
            if loan.state not in ('draft', 'cancel'):
                raise UserError(
                    'You cannot delete a loan which is not in draft or cancelled state')
        return super(HrLoan, self).unlink()

    @api.multi
    def compute_installment(self):
        """This automatically create the installment the employee need to pay to
        company based on payment start date and the no of installments.
            """
        for loan in self:
            loan.loan_lines.unlink()
            amount = float_round(loan.loan_amount / loan.installment, precision_rounding=self.currency_id.rounding)
            total_amount = 0

            # date_start = datetime.strptime(str(loan.payment_date), '%Y-%m-%d')
            date_start = datetime.strptime(str(loan.payment_date), '%Y-%m-%d')
            last_month_day = cal.monthrange(date_start.year, date_start.month)[1]
            date_start = date(date_start.year, date_start.month, last_month_day)


            for i in range(1, loan.installment):
                # date_start = date_start. + relativedelta(months=1)
                date_start = date_start + relativedelta(months=1)
                last_month_day = cal.monthrange(date_start.year, date_start.month)[1]
                date_start = date(date_start.year, date_start.month, last_month_day)
                self.env['hr.loan.line'].create({
                    'date': date_start,
                    'amount': amount,
                    'employee_id': loan.employee_id.id,
                    'loan_id': loan.id})
                total_amount += amount
            date_start = date_start + relativedelta(months=1)
            last_month_day = cal.monthrange(date_start.year, date_start.month)[1]
            date_start = date(date_start.year, date_start.month, last_month_day)
            self.env['hr.loan.line'].create({
                'date': date_start,
                'amount': loan.loan_amount - total_amount,
                'employee_id': loan.employee_id.id,
                'loan_id': loan.id})
        return True

    @api.multi
    def action_get_account_moves(self):
        self.ensure_one()
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

    @api.multi
    def do_print(self):
        # for record in self:
        report_id = self.env.ref('smp_hr_payroll.hr_loan_report_template')
        return report_id.report_action(self)

class HrLoanLine(models.Model):
    _name = "hr.loan.line"
    _description = "Loan Lines"

    date = fields.Date(string="Payment Date", required=True)
    employee_id = fields.Many2one('hr.employee', string="Employee")
    amount = fields.Float(string="Amount", required=True)
    paid = fields.Boolean(string="Paid")
    loan_id = fields.Many2one('hr.loan', string="Loan Ref.")
    payslip_id = fields.Many2one('hr.payslip', string="Payslip Ref.")
    account_move_line_id = fields.Many2one('account.move.line', string="Ligne Comptable")


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    @api.one
    def _compute_employee_loans(self):
        """This compute the loan amount and total loans count of an employee.
            """
        self.loan_count = self.env['hr.loan'].search_count([('employee_id', '=', self.id)])

    loan_count = fields.Integer(string="Loan Count", compute='_compute_employee_loans')


