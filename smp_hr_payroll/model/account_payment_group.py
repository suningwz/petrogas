# -*- coding: utf-8 -*-

from odoo import models, api, fields, _
from odoo.exceptions import ValidationError, UserError


class AccountPaymentGroup(models.Model):
    _inherit = "account.payment.group"


    employee = fields.Boolean(string='Is an employee', related='partner_id.employee')