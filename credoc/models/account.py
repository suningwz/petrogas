# -*- coding: utf-8 -*-

import time
from datetime import date
from collections import OrderedDict
from odoo import api, fields, models, _
from odoo.osv import expression
from odoo.exceptions import RedirectWarning, UserError, ValidationError
from odoo.tools.misc import formatLang, format_date
from odoo.tools import float_is_zero, float_compare
from odoo.tools.safe_eval import safe_eval
from lxml import etree
import decimal_precision as dp



class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.onchange('amount_currency', 'currency_id', 'account_id')
    def _onchange_amount_currency(self):
        '''Recompute the debit/credit based on amount_currency/currency_id and date.
        However, date is a related field on account.move. Then, this onchange will not be triggered
        by the form view by changing the date on the account.move.
        To fix this problem, see _onchange_date method on account.move.
        '''
        for line in self:
            company_currency_id = line.account_id.company_id.currency_id
            amount = line.amount_currency
            if line.currency_id and company_currency_id and line.currency_id != company_currency_id:
                amount = line.currency_id._convert(amount, company_currency_id, line.company_id, line.date or fields.Date.today())
                line.debit = amount > 0 and amount or 0.0
                line.credit = amount < 0 and -amount or 0.0