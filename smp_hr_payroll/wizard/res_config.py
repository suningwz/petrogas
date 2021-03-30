# -*- coding: utf-8 -*-

from odoo import models, fields, api,_
import logging
_logger = logging.getLogger(__name__)
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError, UserError
from odoo.tools.float_utils import float_round

class ResConfigSettings(models.TransientModel):
    _inherit = ['res.config.settings']

    salary_journal = fields.Many2one('account.journal', string="Salary Account Journal", company_dependent=True,)
    # advance_salary_journal = fields.Many2one('account.journal', string="Salary Account Journal", company_dependent=True,)
    # loan_journal = fields.Many2one('account.journal', string="Salary Account Journal", company_dependent=True,)
    employee_payable_account = fields.Many2one('account.account', string="Employee Payable Account", company_dependent=True,)
    loan_account = fields.Many2one('account.account', string="Loan Account",company_dependent=True,)
    salary_advance_account = fields.Many2one('account.account', string="Salary Advance Account",company_dependent=True,)
    loan_sal_adv_account_move_separation = fields.Boolean(string="Separate loan and salary advance's constation from the payment", default=False, company_dependent=True,)

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        res.update(
            salary_journal=int(self.env['ir.config_parameter'].sudo().get_param('smp_hr_payroll.salary_journal')),
            employee_payable_account=int(self.env['ir.config_parameter'].sudo().get_param('smp_hr_payroll.employee_payable_account')),
            loan_account=int(self.env['ir.config_parameter'].sudo().get_param('smp_hr_payroll.loan_account')),
            salary_advance_account=int(self.env['ir.config_parameter'].sudo().get_param('smp_hr_payroll.salary_advance_account')),
            loan_sal_adv_account_move_separation=self.env['ir.config_parameter'].sudo().get_param('smp_hr_payroll.loan_sal_adv_account_move_separation'),
        )
        return res

    @api.multi
    def set_values(self):
        super(ResConfigSettings, self).set_values()
        param = self.env['ir.config_parameter'].sudo()

        salary_journal = self.salary_journal and self.salary_journal.id or False
        employee_payable_account = self.employee_payable_account and self.employee_payable_account.id or False
        loan_account = self.loan_account and self.loan_account.id or False
        salary_advance_account = self.salary_advance_account and self.salary_advance_account.id or False
        loan_sal_adv_account_move_separation = self.loan_sal_adv_account_move_separation or False

        param.set_param('smp_hr_payroll.salary_journal', salary_journal)
        param.set_param('smp_hr_payroll.employee_payable_account', employee_payable_account)
        param.set_param('smp_hr_payroll.loan_account', loan_account)
        param.set_param('smp_hr_payroll.salary_advance_account', salary_advance_account)
        param.set_param('smp_hr_payroll.loan_sal_adv_account_move_separation', loan_sal_adv_account_move_separation)

