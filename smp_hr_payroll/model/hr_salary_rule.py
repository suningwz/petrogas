# -*- coding: utf-8 -*-

from odoo import api, fields, models
from datetime import datetime


class HrSalaryRuleCategory(models.Model):
    _inherit = 'hr.salary.rule.category'

    sequence = fields.Integer(string="Sequence", help='Use to help in sequencing salary rule')
    salary_rule_ids = fields.One2many('hr.salary.rule', 'category_id', string='Salary Rule')



class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    is_regularization_struct = fields.Boolean('Is a regularization structure', default=False)

