# -*- coding: utf-8 -*-

from odoo import fields, models, api, _


class AccountInvoice(models.Model):
    _inherit = "account.invoice"

    currency_rate = fields.Float('Currency rate' ,digits=(12, 6), default=1.0)
    currency_rate_visible = fields.Boolean('Currency rate visible')

    @api.onchange("currency_id")
    def _get_currency_rate_visible(self):
        if self.currency_id:
            self.currency_rate_visible = False
            if self.currency_id != self.env.user.company_id.currency_id:
                self.currency_rate_visible = True

    @api.onchange("currency_id")
    def _get_currency_rate(self):
        if self.currency_id:
            if self.currency_id != self.env.user.company_id.currency_id:
                from_currency = self.currency_id
                to_currency = self.env.user.company_id.currency_id
                company = self.env.user.company_id
                date = self.date_invoice
                # currency_rate = self.env['res.currency']._get_conversion_rate(from_currency, to_currency, company, date)
                currency_rate = from_currency.rate
                self.currency_rate = currency_rate
            else:
                self.currency_rate = 1

    @api.multi
    def compute_invoice_totals(self, company_currency, invoice_move_lines):
        total = 0
        total_currency = 0
        for line in invoice_move_lines:
            if self.currency_id != company_currency:
                currency = self.currency_id
                date = self._get_currency_rate_date() or fields.Date.context_today(self)
                if not (line.get('currency_id') and line.get('amount_currency')):
                    line['currency_id'] = currency.id
                    line['amount_currency'] = currency.round(line['price'])
                    line['price'] = currency.with_context(force_currency_rate=self.currency_rate)._convert(line['price'], company_currency, self.company_id, date)
            else:
                line['currency_id'] = False
                line['amount_currency'] = False
                line['price'] = self.currency_id.round(line['price'])
            if self.type in ('out_invoice', 'in_refund'):
                total += line['price']
                total_currency += line['amount_currency'] or line['price']
                line['price'] = - line['price']
            else:
                total -= line['price']
                total_currency -= line['amount_currency'] or line['price']
        return total, total_currency, invoice_move_lines

    @api.multi
    def action_invoice_open(self):
        # OVERRIDE
        # Auto-reconcile the invoice with payments coming from transactions.
        # It's useful when you have a "paid" sale order (using a payment transaction) and you invoice it later.
        res = super(AccountInvoice, self).action_invoice_open()

        """On verifie si operation de stock """
        for line in self.mapped('invoice_line_ids').filtered(lambda x: x.product_id.type in ['product','consu'] and x.purchase_line_id):
            price_unit_uom = line.price_unit
            if self.currency_id != self.company_id.currency_id:
                currency_rate = self.currency_rate
                price_unit_uom = self.currency_id.with_context(force_currency_rate=currency_rate)._convert(line.price_unit, self.company_id.currency_id, self.company_id, line.invoice_id.date_invoice, round=True)
            for move in line.purchase_line_id.move_ids.filtered(lambda x: x.state == 'done'):
                 """On modifie cout de l'opération de stocks"""
                 value = price_unit_uom * move.product_uom_qty
                 move.write({
                     'value': value,
                     'price_unit' : value / move.product_qty,
                     'invoice_line_id':line.id,
                 })
                 move.update_account_entry_move()
                 # move.update_stock_move_value()

    def _prepare_invoice_line_from_po_line(self, line):
        data = super(AccountInvoice,self)._prepare_invoice_line_from_po_line(line)
        if line.product_id.purchase_method == 'receive':
            stock_move_ids = line.move_ids.filtered(lambda x: not x.invoice_line_id)
            if stock_move_ids:
                assert sum(stock_move_ids.mapped('quantity_done')) == line.qty_received - line.qty_invoiced
                data['move_line_ids'] = [(4, x.id) for x in stock_move_ids]
        return data


