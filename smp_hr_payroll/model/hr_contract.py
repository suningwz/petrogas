# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions
from odoo import tools, _


class Allowance(models.Model):
    _name = 'hr.allowance'
    _rec_name = 'name'
    _description = 'Allowance'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Allowance Name", required=True)
    salary_rule_id = fields.Many2one('hr.salary.rule', string="Salary Rule", required=True)
    active = fields.Boolean(string="Active", default=True)
    taxable = fields.Boolean(string="Taxable", default=False)


class ContractAllowanceLine(models.Model):
    _name = 'hr.contract.allowance.line'
    _rec_name = 'allowance_id'
    _description = 'Contract Allowance Line'

    allowance_id = fields.Many2one(comodel_name="hr.allowance", string="Allowance", required=True)
    salary_rule_id = fields.Many2one('hr.salary.rule', string="Salary Rule", related='allowance_id.salary_rule_id')
    contract_id = fields.Many2one(comodel_name="hr.contract", string="Contract",required=True)
    amount = fields.Float(string="Amount", required=True)


class Contract(models.Model):
    _name = "hr.contract"
    _inherit = 'hr.contract'

    @api.multi
    @api.constrains('state')
    def _check_state(self):
        for record in self:
            if record.state == 'open':
                contract_ids = self.env['hr.contract'].search(
                    [('employee_id', '=', record.employee_id.id), ('state', '=', 'open')])
                if len(contract_ids) > 1:
                    raise exceptions.ValidationError(_('Employee Must Have Only One Running Contract'))

    allowances_ids = fields.One2many(comodel_name="hr.contract.allowance.line", inverse_name="contract_id")
    legal_leave__qty = fields.Float("Legal Leave Quantity", default=0.0)
    legal_leaves_type = fields.Many2one('hr.leave.type', 'Legal Leaves')

    @api.multi
    def get_all_allowances(self, code=None):
        if not code:
            return sum(self.allowances_ids.mapped('amount'))
        else:
            return sum(self.allowances_ids.filtered(lambda x: x.salary_rule_id.code == code).mapped('amount'))

    @api.multi
    def get_no_taxable_allowances(self):
        return sum(self.allowances_ids.filtered(lambda x: x.allowance_id.taxable is False).mapped('amount'))


    # @api.multi
    # def get_all_allowances(self):
    #     return sum(self.allowances_ids.mapped('amount'))
