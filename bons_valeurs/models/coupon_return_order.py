# -*- coding= utf-8 -*-

from odoo import fields, models, _, api
from odoo.exceptions import UserError


class CouponReturnOrder(models.Model):
    _name = 'coupon.return.order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Coupon Return Order'
    _order = "confirmation_date desc, name desc, id desc"
    _rec_name = 'name'

    @api.depends('scan_coupon_ids.coupon_id')
    def _compute_amount(self):
        coupon_ids = self.scan_coupon_ids.mapped('coupon_id')
        # res = self.coupon_ids.read_group(domain=[('id', 'in', coupon_ids.ids)], fields=['value', 'count:count(id)'],
        #                                 groupby=['value'])
        # vals = []
        #
        # for line in res:
        #     vals += [{
        #         'value_unit': line['value'],
        #         'quantity': line['count'],
        #         'return_id': self.id,
        #     }]
        # self.coupon_return_count_ids.unlink()
        # self.update({'coupon_return_count_ids': [(0, 0, r) for r in vals]})
        self.value = coupon_ids and sum(coupon_ids.mapped('value')) or 0.0

    # @api.onchange('scan_coupon_ids')
    # def save_coupon(self):
    #     for r in self.scan_coupon_ids:
    #         r.return_id = self.id

    state = fields.Selection([('draft', 'Draft'), ('open', 'Open'),  ('done', 'Done')], default='draft')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.user.company_id, readonly=True)
    partner_id = fields.Many2one('res.partner', 'Customer', required=False, readonly=True,
                                 states={'draft': [('readonly', False)]})
    name = fields.Char('Name', required=True, default='/', readonly=True)
    confirmation_date = fields.Date('Confirmation Date', default=fields.Date.today())
    coupon_ids = fields.One2many('coupon.value', 'return_id', readonly=True)
    scan_coupon_ids = fields.One2many('coupon.return.order.line', 'return_id', string='Scanned Code', readonly=True, states={'open': [('readonly', False)]})
    anomalie_coupon_ids = fields.Many2many('coupon.value', string='Rejected Coupon', readonly=True)
    coupon_return_count_ids = fields.One2many('coupon.return.count', 'return_id', readonly=True)
    invoice_id = fields.Many2one('account.invoice', 'Credit Note', readonly=True)
    value = fields.Float('Total Amount', default=0.0, readonly=True)
    notes = fields.Text('Note', readonly=True, states={'open':[('readonly', False)]})

    # @api.onchange('scan_coupon_ids.coupon_id')
    def compute_total_value(self):
        self.ensure_one()
        coupon_ids = self.scan_coupon_ids.mapped('coupon_id')
        res = self.coupon_ids.read_group(domain=[('id', 'in', coupon_ids.ids)],
                                         fields=['product_id', 'value', 'count:count(id)'],
                                         groupby=['product_id', 'value'])
        vals = []
        for line in res:
            vals += [{
                'product_id': line['product_id'][0],
                'value_unit': line['value'],
                'quantity': line['count'],
            }]
        self.coupon_return_count_ids.unlink()
        self.update({'coupon_return_count_ids': [(0, 0, r) for r in vals]})
        self.value = coupon_ids and sum(coupon_ids.mapped('value')) or 0.0

    @api.multi
    def open(self):
        self.ensure_one()
        if self.name == "/":
            self.update({
                'name': self.env['ir.sequence'].next_by_code('coupon.return.order'),
                'state': 'open'
                        })

    @api.multi
    def confirm(self):
        self.ensure_one()

        # On crée une note de crédit
        if not self.scan_coupon_ids.filtered(lambda r: r.coupon_id):
            raise UserError(_("""Before a confirmation. Please ensure to register valid coupons."""))
        # poie = [(0, 0, r) for r in coupon_ids.ids]

        self.compute_total_value()
        invoice_val = self.prepare_invoice()
        invoice_id = self.env['account.invoice'].sudo().create(invoice_val)
        invoice_id.action_invoice_open()
        self.invoice_id = invoice_id

        # On actualise les statuts des coupons et du bon de retour
        self.scan_coupon_ids.filtered(lambda r: r.coupon_id).mapped('coupon_id')._set_coupons_to_returned_state()
        self.state = 'done'
        return invoice_id

    def cancel(self):
        # invoice_id = self.invoice_id
        invoice_id = True
        if invoice_id :
            raise UserError(_("""You can not cancel a coupon return order which has credit note."""))

    def prepare_invoice(self):
        invoice_vals = {}
        journal_id = self.env['coupon.configuration'].search([('company_id', '=', self.company_id.id)], limit=1).return_journal_id
        invoice_vals.update({
            'origin': self.name,
            'type': 'out_refund',
            'account_id': self.partner_id.property_account_receivable_id.id,
            'journal_id': journal_id.id,
            'currency_id': self.company_id.currency_id.id,
            'comment': self.notes,
            'payment_term_id': self.partner_id.property_payment_term_id and self.partner_id.property_payment_term_id.id or False,
            'company_id': self.company_id.id,
            'user_id': self.env.user.id,
            'vendor_id': self.env.user.id,
            'partner_id': self.partner_id.id,
            'invoice_line_ids': [(0, 0, r) for r in self.prepare_invoice_line()]
        })
        return invoice_vals

    def prepare_invoice_line(self):
        coupon_ids = self.scan_coupon_ids.mapped('coupon_id')
        lines = self.coupon_ids.read_group(domain=[('id', 'in', coupon_ids.ids)],
                                         fields=['product_id', 'value', 'count:count(id)'],
                                         groupby=['product_id', 'value'])
        res = []
        for line in lines:
            product_id = self.env['product.product'].search([('id', '=', line['product_id'][0])], limit=1)
            account = product_id.product_tmpl_id._get_product_accounts()['expense']
            res += [{
                'product_id': product_id.id,
                'name': product_id.name,
                'account_id': account.id,
                'price_unit': line['value'],
                'quantity': line['count'],
            }]
        return res

    def set_count(self):
        self.ensure_one()
        res = self.read_group([('id','=', self.id)], ['value_unit', 'quantity:count(value_unit)'], ['value_unit'])
        val = []
        for r in res:
            val += [(0, 0, {
                'value_unit': r['value_unit'],
                'quantity': r['quantity'],
            })]
        return val

    @api.multi
    def write(self, vals):
        self.ensure_one()
        # self.compute_total_value()
        return super(CouponReturnOrder, self).write(vals)


class CouponReturnOrderLine(models.Model):
    _name = 'coupon.return.order.line'
    _description = 'Scanned Coupon'

    scanned_code = fields.Char('Scanned Code', required=True)
    coupon_id = fields.Many2one('coupon.value', 'Coupons', readonly=True)
    product_id = fields.Many2one('product.product', 'Product', related='coupon_id.product_id', readonly=True)
    value = fields.Float('Value', related='coupon_id.value', store=True, readonly=True)
    return_id = fields.Many2one('coupon.return.order', 'Coupon Return Order', readonly=True)

    def control_doublon(self, coupon_id):
        coupon_id.ensure_one()
        msg = ''
        if coupon_id in self.return_id.scan_coupon_ids.mapped('coupon_id'):
            # scanned multiple time on the same return order
            msg = _(
                "Coupons with the following trunked codebare '{}' has already been scanned.").format(
                coupon_id.barcode_trunked)
            return False, msg
        return True, msg

    def control_expiration_date(self):
        pass

    def control_state(self, coupon_id):
        msg = ''
        if coupon_id.state != 'circulation':
            # coupon state not in circulation
            msg = _(
                "Coupons with the following trunked codebare '{}' due an invalide state '{}' will not be accepted by the company,! Please contact your supervisor").format(
                coupon_id.barcode_trunked, coupon_id.state)
            return False, msg

        return True, msg

    @api.multi
    def unlink(self):
        for r in self:
            if r.coupon_id:
                r.coupon_id.return_id = None
        res = super(CouponReturnOrderLine, self).unlink()
        self.return_id.compute_total_value()
        return res

        # 4876104483232

    @api.onchange("scanned_code")
    def get_coupon(self):
        msg = False
        if self.scanned_code:
            coupon_id = self.env['coupon.value'].search([('barcode', '=', self.scanned_code)])
            if not coupon_id:
                msg = _("Coupons with the following trunked codebare '{}' does not exist! Please contact your supervisor").format(self.scanned_code)
            else:
                state, msg_state = self.control_state(coupon_id)
                doublon, msg_doublon = self.control_doublon(coupon_id)

                if not all([state, doublon]):
                    raise UserError(msg_state + '\n' + msg_doublon)
                else:
                    return_id = self._context.get('default_return_id', False)
                    if not return_id:
                        raise UserError(_("No coupon return order has been founded."))
                    self.update({'coupon_id': coupon_id.id})
                    # self.coupon_id.return_id = self.return_id
                    # active_id = self._context.get('active_id')
                    # coupon_id.return_id = return_id
                    # Mettre à jour le compteur
                    self.return_id.compute_total_value()


class CouponReturnCount(models.Model):
    _name = 'coupon.return.count'
    _description = 'Coupon Return resume'
    _order = 'id desc'

    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    value_unit = fields.Float('Value Unit', readonly=True)
    quantity = fields.Integer('Quantity', readonly=True)
    return_id = fields.Many2one('coupon.return.order', 'Coupon Return Order', readonly=True)


