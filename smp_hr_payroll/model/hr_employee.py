# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    code = fields.Char(string="code")

    @api.onchange('job_id')
    def _onchange_job_id(self):
        res = super(HrEmployee, self)._onchange_job_id()
        if self.job_id.department_id:
            self.department_id = self.job_id.department_id
    @api.model
    def create(self, vals):
        res_id = super(HrEmployee, self).create(vals)
        res_id.link_employee_to_res_partner()
        return res_id


    @api.multi
    def link_employee_to_res_partner(self):
        for employee in self:
            if employee.user_id and employee.user_id.partner_id:
                employee.address_id = employee.user_id.partner_id
            # elif (employee.user_id and not employee.user_id.partner_id) or not employee.user_id:
            else:
                vals = {
                    'name': employee.name,
                    'code': employee.code,
                    'employee': True,
                    'customer': False,
                    'supplier': False,
                    'company_type': 'person',
                }
                partner_id = employee.address_id.create([vals])
                employee.address_id = partner_id

            employee.address_home_id = employee.address_id
            employee.address_id.employee = True

    @api.multi
    def get_current_year_payslip(self):
        struct_id = self.env['hr.payroll.structure'].search([('is_regularization_struct', '=', False)])
        if not struct_id:
            raise UserError(_("""Ensure an not regularization payroll structure exist !!!"""))
        slip_ids = self.slip_ids and self.slip_ids.filtered(lambda x: x.struct_id in struct_id and x.state == 'done') or False
        if slip_ids:
            return slip_ids.sorted(lambda r: r.date_from)[-11:]
        return slip_ids

    @api.multi
    def get_average_year_payslip(self):
        slip_ids = self.get_current_year_payslip()
        if slip_ids:
            return sum(slip_ids.rule_ids.filtered(lambda x: x.code == 'NET').mapped('amount'))
        return False


# if employee.get_current_year_payslip():
#                     result = employee.get_average_year_payslip() / len(employee.get_current_year_payslip())
# else:
#     result = contract.wage