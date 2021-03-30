# -*- coding: utf-8 -*-
import time
import babel
from odoo import models, fields, api, tools, _
from datetime import datetime
from odoo.exceptions import UserError

LOAN_CODE = "LOAN"
ADV_SAL_CODE = "SAR"

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    slip_line_id = fields.Many2one('hr.payslip.line', string='Payslip Line')


class HrPayslipInput(models.Model):
    _inherit = 'hr.payslip.input'

    loan_line_ids = fields.Many2many('hr.loan.line', string="Loan Installment")
    advance_salary_ids = fields.Many2many('salary.advance', string="Salary Advance")


class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'

    loan_line_ids = fields.Many2many('hr.loan.line', string="Loan Installment")
    advance_salary_ids = fields.Many2many('salary.advance', string="Salary Advance")
    account_move_line_ids = fields.One2many('account.move.line', 'slip_line_id', string="Account Move Line")


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'



    @api.onchange('employee_id', 'date_from', 'date_to')
    def onchange_employee(self):
        if (not self.employee_id) or (not self.date_from) or (not self.date_to):
            return

        employee = self.employee_id
        date_from = self.date_from
        date_to = self.date_to
        contract_ids = []

        ttyme = datetime.fromtimestamp(time.mktime(time.strptime(str(date_from), "%Y-%m-%d")))
        locale = self.env.context.get('lang') or 'en_US'
        self.name = _('Salary Slip of %s for %s') % (
        employee.name, tools.ustr(babel.dates.format_date(date=ttyme, format='MMMM-y', locale=locale)))
        self.company_id = employee.company_id

        if not self.env.context.get('contract') or not self.contract_id:
            contract_ids = self.get_contract(employee, date_from, date_to)
            if not contract_ids:
                return
            self.contract_id = self.env['hr.contract'].browse(contract_ids[0])

        if not self.contract_id.struct_id:
            return
        self.struct_id = self.contract_id.struct_id

        # computation of the salary input
        contracts = self.env['hr.contract'].browse(contract_ids)
        worked_days_line_ids = self.get_worked_day_lines(contracts, date_from, date_to)
        worked_days_lines = self.worked_days_line_ids.browse([])
        for r in worked_days_line_ids:
            worked_days_lines += worked_days_lines.new(r)
        self.worked_days_line_ids = worked_days_lines
        if contracts:
            self.input_line_ids.unlink()
            input_line_ids = self.get_inputs(contracts, date_from, date_to)
            input_lines = self.input_line_ids.browse([])
            for r in input_line_ids:
                input_lines += input_lines.new(r)
                # r['payslip_id'] = self.id
                # input_lines += input_lines.create(r)
            self.input_line_ids = input_lines
            # self.get_loan_adv_salary_input(contracts, date_from, date_to)
        return

    def get_inputs(self, contract_ids, date_from, date_to):
        res = super(HrPayslip, self).get_inputs(contract_ids, date_from, date_to)
        contract_obj = self.env['hr.contract']
        emp_id = contract_obj.browse(contract_ids[0].id).employee_id

        """ Gestion des prêts"""
        loan_line_obj = self.env['hr.loan.line'].search([('employee_id', '=', emp_id.id),
                                                         ('paid', '=', False),
                                                         ('date', '<=', date_to)])
        for loan_line in loan_line_obj:
            for result in res:
                if result.get('code') == 'LOAN':
                    result['amount'] = loan_line.amount if not result.get('amount') else result['amount'] + loan_line.amount


        """ Gestion des avances"""
        adv_salary = self.env['salary.advance'].search([('employee_id', '=', emp_id.id),
                                                        ('state', '=', 'paid'),
                                                        ('date', '<=', date_to),
                                                        ])
        for adv_obj in adv_salary:
            amount = adv_obj.advance
            for result in res:
                if result.get('code') == 'SAR':
                    result['amount'] = amount if not result.get('amount') else result['amount'] + amount
        return res

    def get_loan_adv_salary_input(self, contract_ids, date_from, date_to):
        """This Compute the other inputs to employee payslip.
                           """
        # self.input_line_ids.unlink()

        contract_obj = self.env['hr.contract']
        emp_id = contract_obj.browse(contract_ids[0].id).employee_id
        lon_obj = self.env['hr.loan'].search([('employee_id', '=', emp_id.id), ('state', '=', 'approve')])
        for input_line_id in self.input_line_ids:
            # input_line_id = self.input_line_ids.create(result)

            """ Gestion des allocations"""

            """ Gestion des prêts"""
            if input_line_id.code == LOAN_CODE:
                loan_line_obj = self.env['hr.loan.line'].search([('employee_id', '=', emp_id.id),
                                                                ('paid', '=', False),
                                                                ('date', '<=', date_to)])
                input_line_id.amount = 0.0
                for loan_line in loan_line_obj:
                    input_line_id.amount += loan_line.amount
                    input_line_id.loan_line_ids = [(4, loan_line.id)]


            """ Gestion des avances"""
            if input_line_id.code == ADV_SAL_CODE:
                adv_salary = self.env['salary.advance'].search([('employee_id', '=', emp_id.id),
                                                                ('state', '=', 'paid'),
                                                                ('date', '<=', date_to),
                                                                ])
                input_line_id.amount = 0.0
                for adv_obj in adv_salary:
                    input_line_id.amount += adv_obj.advance
                input_line_id.advance_salary_ids = [(4, x.id) for x in adv_salary]
        return True

    @api.multi
    def _get_partner_id(self):
        self.ensure_one()
        return self.employee_id.address_home_id.id

    @api.multi
    def action_payslip_done(self):
        # res = super(HrPayslip, self).action_payslip_done()

        self.get_loan_adv_salary_input(self.contract_id, self.date_from, self.date_to)

        self.compute_sheet()

        for slip in self:
            line_ids = []
            debit_sum = 0.0
            credit_sum = 0.0
            date = slip.date or slip.date_to
            currency = slip.company_id.currency_id

            name = _('Payslip of %s') % (slip.employee_id.name)
            move_dict = {
                'narration': name,
                'ref': slip.number,
                'journal_id': slip.journal_id.id,
                'date': date,
            }
            for line in slip.details_by_salary_rule_category:
                amount = currency.round(slip.credit_note and -line.total or line.total)
                if currency.is_zero(amount):
                    continue
                debit_account_id = line.salary_rule_id.account_debit.id
                credit_account_id = line.salary_rule_id.account_credit.id

                if debit_account_id:
                    debit_line = (0, 0, {
                        'name': line.name,
                        'partner_id': line._get_partner_id(credit_account=False),
                        'account_id': debit_account_id,
                        'journal_id': slip.journal_id.id,
                        'date': date,
                        'debit': amount > 0.0 and amount or 0.0,
                        'credit': amount < 0.0 and -amount or 0.0,
                        'analytic_account_id': line.salary_rule_id.analytic_account_id.id or slip.contract_id.analytic_account_id.id,
                        'tax_line_id': line.salary_rule_id.account_tax_id.id,
                        'slip_line_id': line.id,
                    })
                    line_ids.append(debit_line)
                    debit_sum += debit_line[2]['debit'] - debit_line[2]['credit']

                if credit_account_id:
                    credit_line = (0, 0, {
                        'name': line.name,
                        'partner_id': line._get_partner_id(credit_account=True),
                        'account_id': credit_account_id,
                        'journal_id': slip.journal_id.id,
                        'date': date,
                        'debit': amount < 0.0 and -amount or 0.0,
                        'credit': amount > 0.0 and amount or 0.0,
                        'analytic_account_id': line.salary_rule_id.analytic_account_id.id or slip.contract_id.analytic_account_id.id,
                        'tax_line_id': line.salary_rule_id.account_tax_id.id,
                        'slip_line_id': line.id,
                    })
                    line_ids.append(credit_line)
                    credit_sum += credit_line[2]['credit'] - credit_line[2]['debit']

            if currency.compare_amounts(credit_sum, debit_sum) == -1:
                acc_id = slip.journal_id.default_credit_account_id
                if not acc_id:
                    raise UserError(_('The Expense Journal "%s" has not properly configured the Credit Account!') % (slip.journal_id.name))
                adjust_credit = (0, 0, {
                    'name': acc_id.name,
                    # 'name': _('Adjustment Entry'),
                    'partner_id': slip._get_partner_id(),
                    'account_id': acc_id.id,
                    'journal_id': slip.journal_id.id,
                    'date': date,
                    'debit': 0.0,
                    'credit': currency.round(debit_sum - credit_sum),
                })
                line_ids.append(adjust_credit)

            elif currency.compare_amounts(debit_sum, credit_sum) == -1:
                acc_id = slip.journal_id.default_debit_account_id
                if not acc_id:
                    raise UserError(_('The Expense Journal "%s" has not properly configured the Debit Account!') % (slip.journal_id.name))
                adjust_debit = (0, 0, {
                    'name': acc_id.name,
                    # 'name': _('Adjustment Entry'),
                    'partner_id': slip._get_partner_id(),
                    'account_id': acc_id.id,
                    'journal_id': slip.journal_id.id,
                    'date': date,
                    'debit': currency.round(credit_sum - debit_sum),
                    'credit': 0.0,
                })
                line_ids.append(adjust_debit)
            move_dict['line_ids'] = line_ids
            move = self.env['account.move'].create(move_dict)
            slip.write({'move_id': move.id, 'date': date})
            move.post()

        for slip in self:
            if not slip.struct_id.is_regularization_struct:
                if slip.contract_id.legal_leaves_type and slip.contract_id.legal_leave__qty :
                    legal_leaves_type = slip.contract_id.legal_leaves_type
                    legal_leave_qty = slip.contract_id.legal_leave__qty

                    val = {
                        'name': slip.name + ' - ' + legal_leaves_type.name,
                        'holiday_type': 'employee',
                        'holidays_statut_id': legal_leaves_type.id,
                        'number_of_days': legal_leave_qty,
                        'employee_id': slip.employee_id.id,
                        'accrual': False,
                        'date_to': slip.date_to,
                        # 'interval_unit': self.interval_unit,
                        # 'interval_number': self.interval_number,
                        # 'number_per_interval': self.request_unit,
                        # 'unit_per_interval': legal_leaves_type.unit_per_interval,
                        'state': 'confirm',
                        'payslip_id': slip.id,
                    }
                    leave_id = self.env['hr.leave.allocation'].create(val)
                    leave_id.action_approve()

        self.reconcile_input_line()

        return self.write({'state': 'done'})


    def reconcile_input_line(self):
        for slip in self:
            if not slip.struct_id.is_regularization_struct:
                if slip.contract_id.legal_leaves_type and slip.contract_id.legal_leave__qty :
                    legal_leaves_type = slip.contract_id.legal_leaves_type
                    legal_leave_qty = slip.contract_id.legal_leave__qty

                    val = {
                        'name': slip.name + ' - ' + legal_leaves_type.name,
                        'holiday_type': 'employee',
                        'holidays_statut_id': legal_leaves_type.id,
                        'number_of_days': legal_leave_qty,
                        'employee_id': slip.employee_id.id,
                        'accrual': False,
                        'date_to': slip.date_to,
                        # 'interval_unit': self.interval_unit,
                        # 'interval_number': self.interval_number,
                        # 'number_per_interval': self.request_unit,
                        # 'unit_per_interval': legal_leaves_type.unit_per_interval,
                        'state': 'confirm',
                        'payslip_id': slip.id,
                    }
                    leave_id = self.env['hr.leave.allocation'].create(val)
                    leave_id.action_approve()


            for input_line in slip.input_line_ids:

                if input_line.loan_line_ids:

                    loan_account_id = input_line.loan_line_ids.mapped('loan_id').mapped('debit')
                    loan_account_id.ensure_one()

                    loan_move_ids = input_line.loan_line_ids.mapped('loan_id').mapped('account_move_line_ids').filtered(lambda x: x.account_id == loan_account_id)
                    if not loan_move_ids:
                        loan__name = ', '.join(input_line.loan_line_ids.mapped('loan_id').mapped('name'))
                        raise UserError(_('No entries move found for the salary advance %s with the account code %s') % (loan__name, loan_account_id.code))

                    rule_line = slip.details_by_salary_rule_category.filtered(lambda x: x.code == LOAN_CODE)
                    rule_line.ensure_one()

                    line_move_id = rule_line.account_move_line_ids.filtered(lambda x: x.account_id == loan_account_id)
                    line_move_id.ensure_one()
                    balance = -sum(loan_move_ids.mapped('balance'))
                    assert loan_account_id == rule_line.salary_rule_id.account_debit
                    # assert line_move_id.balance == -sum(loan_move_ids.mapped('balance'))

                    # loan_move_ids += line_move_id
                    input_line.loan_line_ids.write({'paid': True, 'payslip_id': input_line.payslip_id.id})
                    # loan_move_ids.reconcile(writeoff_acc_id=False, writeoff_journal_id=False)l

                if input_line.advance_salary_ids:

                    advance_salary_account_id = input_line.advance_salary_ids.mapped('debit')
                    advance_salary_account_id.ensure_one()

                    advance_salary_move_ids = input_line.advance_salary_ids.mapped('account_move_line_ids').filtered(lambda x: x.account_id == advance_salary_account_id)
                    if not advance_salary_move_ids:
                        adv_salary_name = ', '.join(input_line.advance_salary_ids.mapped('name'))
                        raise UserError(_('No entries move found for the salary advance %s with the account code %s') % (adv_salary_name, advance_salary_account_id.code))

                    rule_line = slip.details_by_salary_rule_category.filtered(lambda x: x.code == ADV_SAL_CODE)
                    rule_line.ensure_one()

                    line_move_id = rule_line.account_move_line_ids.filtered(lambda x: x.account_id == advance_salary_account_id )
                    line_move_id.ensure_one()

                    assert advance_salary_account_id == rule_line.salary_rule_id.account_debit
                    assert line_move_id.balance == -sum(advance_salary_move_ids.mapped('balance'))

                    input_line.advance_salary_ids.write({'payslip_id': slip.id})

                    advance_salary_move_ids += line_move_id
                    advance_salary_move_ids.reconcile(writeoff_acc_id=False, writeoff_journal_id=False)

            return True


    def cancel(self):

        # Annulation Leaves
        self.env['hr.leave.allocation'].search([('payslip_id', 'in', self.ids)]).action_draft()
        self.env['hr.leave.allocation'].search([('payslip_id', 'in', self.ids)]).unlink()

        # Anulation pièce comptable
        self.mapped('move_id').button_cancel()
        self.mapped('move_id').mapped('line_ids').remove_move_reconcile()
        self.mapped('move_id').unlink()
        self.write({'state':'draft'})




# account_move_line_id

