# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from datetime import timedelta, date

# READONLY_STATES = {
#     'draft': [('readonly', False)],
#     'open': [('readonly', True)],
#     'closed': [('readonly', True)],
#     'cancel': [('readonly', True)],
# }


class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    credoc_id = fields.Many2one('credoc.credoc', 'Letter Credit')

    @api.multi
    def set_hide_credo(self):
        self.ensure_one()
        hide_credoc = True
        credoc_ids = False
        if self.type not in ('in_refund', 'in_invoice') and  self.partner_id:
            credoc_ids = self.env['credoc.credoc'].get_partner_credoc(self.partner_id)
            if credoc_ids:
                hide_credoc = False
        self = self.with_context(hide_credoc=hide_credoc)
        return {'domain': {'credoc_id': [('id', 'in', credoc_ids), ('state', '=', 'open')]}, 'context': self._context}

    @api.constrains
    def _check_currency_credoc(self):
        if self.credoc_id and self.credoc_id.currency_id is not self.currency_id:
            raise exceptions.ValidationError(_("Invoice currency must be the same as the documentary credit."))


class AccountInvoiceLine(models.Model):
    _inherit = 'account.invoice.line'

    credoc_id = fields.Many2one('credoc.credoc', 'Letter Credit', related='invoice_id.credoc_id')
    state = fields.Selection(related='invoice_id.state',string='state')
