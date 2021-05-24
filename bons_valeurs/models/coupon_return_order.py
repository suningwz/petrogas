# -*- coding= utf-8 -*-

from odoo import fields, models, _, api
from odoo.exceptions import UserError


class CouponReturnOrder(models.Model):
    _name = 'coupon.return.order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Coupon Receipt Order'
    _order = "confirmation_date desc, name desc, id desc"

    def _compute_amount(self):
        if self.coupon_ids:
            self.value = sum(self.coupon_ids.mapped('value'))

    state = fields.Selection([('draft', 'Draft'), ('open', 'Open'),  ('done', 'Done')], default='draft')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.user.company_id)
    partner_id = fields.Many2one('res.partner', 'Customer', required=False)
    name = fields.Char('Name', required=True, default='/', readonly=True)
    confirmation_date = fields.Date('Confirmation Date', default=fields.Date.today())
    coupon_ids = fields.One2many('coupon.value', 'return_id')
    anomalie_coupon_ids = fields.Many2many('coupon.value', string='Rejected Coupon')
    coupon_return_count_id = fields.One2many('coupon.return.count', 'return_id')
    invoice_id = fields.Many2one('account.invoice', 'Credit Note', readonly=True)
    value = fields.Float('Total Amount', required=True, default=0, readonly=True)
    notes = fields.Text()

    @api.multi
    def open(self):
        self.ensure_one()
        self.name = self.env['ir.sequence'].next_by_code('bons_valeurs.seq_coupon_receipt_return')

    @api.multi
    def confirm(self):
        self.ensure_one()
        # for r in self:
        #     r.coupon_ids.write({'state': 'done'})
        # On crée une note de crédit
        if not self.coupon_ids:
            raise UserError(_("""Before a confirmation. Please ensure to register valid coupons."""))

        invoice_val = self.prepare_invoice()
        invoice_id = self.env['account.invoice'].create(invoice_val)

        # On actualise les statuts des coupons et du bon de retour
        self.coupon_ids.write({'state': 'done'})
        self.state = 'done'
        return invoice_id

    def cancel(self):
        # invoice_id = self.invoice_id
        invoice_id = True
        if invoice_id :
            raise UserError(_("""You can not cancel a coupon return order which has credit note."""))

    def prepare_invoice(self):
        invoice_vals = {}
        journal_id = self.env['coupon.configuration'].get_config(self.company_id).return_journal_id
        invoice_vals.update({
            'name': (self.client_order_ref or '')[:2000],
            'origin': self.name,
            'type': 'in_invoice',
            'account_id': self.partner_id.property_account_receivable_id.id,
            'journal_id': journal_id.id,
            'currency_id': self.company_id.currency_id.id,
            'comment': self.note,
            'payment_term_id': self.payment_term_id.id,
            'company_id': self.company_id.id,
            'user_id': self.env.user_id,
            'lines': [(0, 0, r) for r in self.prepare_invoice_line()]
        })
        return invoice_vals

    def prepare_invoice_line(self):
        res = []
        domain = []
        field_list = ['quantity:count(coupon_ids)']
        group_by = ['value_unit']
        lines = self.coupon_ids.read_group(domain, field_list, group_by)
        for line in lines:
            res += [{
                'product_id': False,
                'account_id': False,
                'price_unit': line['value_unit'],
                'quantity': line['field_list']['quantity'],
            }]
        return res

    def set_count(self):
        self.ensure_one()
        res = self.read_group([('id','=', self.id)], ['value_unit', 'number_of_coupon:count(value_unit)'], ['value_unit'])
        for r in res:
            val = [(0, 0, {
                'value_unit': r['value_unit'],
                'number_of_coupon': r['number_of_coupon'],
            })]


class CouponReturnCount(models.Model):
    _name = 'coupon.return.count'
    _description = 'Coupon Return resume'

    value_unit = fields.Float('Value Unit')
    number_of_coupon = fields.Integer('Number Of Coupon ')
    return_id = fields.Many2one('coupon.return', required=True)




# class CouponReturnOrderLine(models.Model):
#     _name = 'coupon.return.order.line'
#     _description = 'Coupon Receipt Order Line'
#
#     return_id = fields.Many2one('coupon.value')
#     char = fields.Char('codebare', required=True)
#     coupon_id = fields.Many2one('coupon.value')
#     is_ok = fields.Boolean('Controlled', default=False)
