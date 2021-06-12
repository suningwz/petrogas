# -*- coding= utf-8 -*-

from odoo import fields, models, _, api
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta


class CouponPrintingOrder(models.Model):
    _name = 'coupon.printing.order'
    _description = 'Coupon Printing Order'
    _order = 'name'

    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True,
                                 default=lambda self: self.env.user.company_id)
    name = fields.Char('Name', required=True, default='/', readonly=True, copy=False)
    sale_order_id = fields.Many2one('sale.order', readonly=True, copy=False)
    printing_line_ids = fields.One2many('coupon.printing.order.line', 'printing_order_id',
                                        readonly=True, states={'draft': [('readonly', False)]})
    partner_id = fields.Many2one('res.partner', 'Customer', related='sale_order_id.partner_id',
                                        readonly=True, states={'draft': [('readonly', False)]})
    printer_id = fields.Many2one('printing.printer',
                                        readonly=True, states={'open': [('readonly', False)]})
    delivery_id = fields.Many2one('coupon.delivery.order', 'Coupon Delivery Order',
                                        readonly=True, states={'draft': [('readonly', False)]})
    printing_date = fields.Date('Print Date', default=fields.date.today(),
                                        readonly=True, states={'draft': [('readonly', False)]})
    confirmation_date = fields.Date('Confirmation Date', default=fields.date.today(),copy=False,
                                        readonly=True, states={'draft': [('readonly', False)]})
    location_id = fields.Many2one('stock.location', 'Coupon Location',
                                        readonly=True, states={'draft': [('readonly', False)]})
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Ready to print'),
        ('printing', 'Printing'),
        ('done', 'Done'),
    ], default='draft')

    # open ---> print_printing_order ---->done

    @api.multi
    def create(self, vals_list):
        name = self.env.ref('bons_valeurs.seq_coupon_printing_order').next_by_id()
        vals_list['name'] = name
        return super(CouponPrintingOrder, self).create(vals_list)

    @api.multi
    def open(self):
        self.ensure_one()
        res = self._create_coupons()
        self.state = 'open'
        return res

    @api.multi
    def print_printing_order(self):
        self.ensure_one()
        coupon_ids = self.printing_line_ids.mapped('stack_ids.coupon_ids')
        coupon_ids.write({'state': 'printing'})
        self.write({'state': 'printing'})
        return coupon_ids._print_coupon()

    @api.multi
    def done(self):
        self.ensure_one()

        # Si c'est une vente on crée un bon de livrison
        if self.sale_order_id:
            # delivery_id = self._create_delivery_order_from_print_order()
            self.delivery_id = self._create_coupon_delivery()
            if not self.delivery_id and not self.delivery_id.stack_ids:
                raise UserError(_("""No stack in the coupon delivery order."""))
            self.delivery_id.stack_ids.mapped('coupon_ids')._set_coupons_to_deliver_state()

        else:
            # Sinon on modifie le statut des tickets
            self.printing_line_ids.mapped('stack_ids.coupon_ids')._set_coupons_to_done_state()

        self.state = 'done'

    # @api.multi
    # def print_printing_order(self):
    #     self.ensure_one()
    #     coupon_ids = self.printing_line_ids.mapped('stack_ids.coupon_ids')
    #     # coupon_ids.write({'state': 'printing'})
    #     # self.write({'state': 'printing'})
    #     return coupon_ids._print_coupon()

    @api.multi
    def _create_coupons(self):
        self.ensure_one()
        stack_ids = self.env['coupon.stack']
        for line in self.printing_line_ids:
            stack_ids |= line._create_stack()

    @api.multi
    def _create_coupon_delivery(self):
        self.ensure_one()
        if self.sale_order_id:
            stack_ids = self.printing_line_ids.mapped('stack_ids').ids
            val = {
                'state': 'open',
                'confirmation_date': self.confirmation_date.strftime('%Y-%m-%d'),
                'name': self.env.ref('bons_valeurs.seq_coupon_delivery_order').next_by_id(),
                'company_id': self.company_id.id,
                'partner_id': self.sale_order_id.partner_id.id,
                'sale_id': self.sale_order_id.id,
                'stack_ids': [(6, 0, stack_ids)],
                'location_id': self.location_id and self.location_id.id or False,
            }
            return self.env['coupon.delivery.order'].create([val])


class CouponPrintingOrderLine(models.Model):
    _name = 'coupon.printing.order.line'
    _description = 'Coupon Printing Order Line'

    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.user.company_id)
    sale_order_line_id = fields.Many2one('sale.order.line', copy=False)
    printing_order_id = fields.Many2one('coupon.printing.order')
    product_id = fields.Many2one('product.product', 'Product', required=True)
    quantity = fields.Integer('Quantity')
    value = fields.Float('Coupon Value')
    coupon_per_stack = fields.Integer('Coupon Per Stack', default=10)
    stack_ids = fields.One2many('coupon.stack', 'printing_order_line_id', copy=False)

    @api.multi
    def _create_stack(self):
        self.ensure_one()
        ir_sequence = self.env['ir.sequence']
        stack_ids = []
        for i in range(1, len(range(0, self.quantity, self.coupon_per_stack)) + 1):
            # Il se peut que le dernier carnet contienne moins de tickets
            coupon_per_stack = self.coupon_per_stack if (i * self.coupon_per_stack) <= self.quantity else (self.quantity - (i-1) * self.coupon_per_stack)
            stack_ids += [{
                'company_id': self.company_id.id,
                'sequence': ir_sequence.next_by_code('coupon.stack'),
                'product_qty': coupon_per_stack,
                'value_unit': self.value,
                'coupon_ids': self._prepare_coupon_to_create(coupon_per_stack),
                'printing_order_line_id': self.id,
                'sale_line_id': self.sale_order_line_id and self.sale_order_line_id.id or False,
                'location_id': self.printing_order_id.location_id.id,
                'sale_id': self.printing_order_id.sale_order_id and self.printing_order_id.sale_order_id.id or False,
            }]

        return self.env['coupon.stack'].create(stack_ids)

    @api.multi
    def _prepare_coupon_to_create(self, coupon_by_stack=0):
        self.ensure_one()
        coupon_key_obj = self.env['coupon.configuration']
        config = coupon_key_obj.search([('company_id', '=', self.company_id.id)], limit=1)
        assert config
        key = config.key

        res = []

        validity_period = relativedelta(months=6)
        printing_date = self.printing_order_id.confirmation_date
        # expiration_date = fields.Date.add(printing_date, validity_period)
        expiration_date = printing_date + validity_period
        for i in range(int(coupon_by_stack)):
            barcode_receipt = config.RandomEAN13(key)
            res += [(0, 0, {
                'active': True,
                'company_id': self.company_id.id,
                'sequence': self.env.ref('bons_valeurs.seq_receipt_sequence').next_by_id(),
                'barcode': barcode_receipt,
                'barcode_trunked': barcode_receipt[:9],
                'product_id': self.product_id.id,
                'value': self.value,
                'state': 'to_print',
                'partner_id': self.printing_order_id.partner_id and self.printing_order_id.partner_id.id or False,
                'printing_order_id': self.printing_order_id.id,
                'expiration_date': fields.Date.to_string(expiration_date)
            })]
        return res

    # @api.multi
    # def _print_order_line_coupon(self):
    #     coupon_ids = self.mapped('stack_ids.coupon_ids')
    #     coupon_ids.write({'state': 'printing'})
    #     self.write({'state': 'printed'})
    #     return coupon_ids._print_coupon()



