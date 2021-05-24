# -*- coding= utf-8 -*-

from odoo import fields, models, _, api
from odoo.exceptions import UserError


class CouponPrintingOrder(models.Model):
    _name = 'coupon.printing.order'
    _description = 'Coupon Printing Order'

    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True,
                                 default=lambda self: self.env.user.company_id)
    name = fields.Char('Name', required=True, default='/', readonly=True, copy=False)
    sale_order_id = fields.Many2one('sale.order', readonly=True, copy=False)
    printing_line_ids = fields.One2many('coupon.printing.order.line', 'printing_order_id')
    partner_id = fields.Many2one('res.partner', 'Customer', related='sale_order_id.partner_id', readonly=True)
    printer_id = fields.Many2one('printing.printer')
    printing_date = fields.Date('Print Date', default=fields.date.today())
    confirmation_date = fields.Date('Confirmation Date', default=fields.date.today(),copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Ready to print'),
        ('printing', 'Printing'),
        ('done', 'Done'),
    ], default='draft')

    # open ---> print_printing_order ---->done

    @api.multi
    def open(self):
        self.ensure_one()
        res = self.create_coupons()
        self.state = 'open'
        self.name = self.env.ref('bons_valeurs.seq_coupon_printing_order').next_by_id()
        return res

    @api.multi
    def print_printing_order(self):
        self.ensure_one()
        coupon_ids = self.printing_line_ids.mapped('stack_ids.coupon_ids')
        coupon_ids.write({'state': 'printing'})
        self.write({'state': 'printing'})
        return coupon_ids._print_coupon()

    def done(self):
        self.ensure_one()

        # Si c'est une vente on crée un bon de livrison
        if self.sale_order_id:
            self.delivery_id = [(0, 0, {
                'name': self.env.ref('bons_valeurs.seq_coupon_delivery_order').next_by_id(),
                'state': 'open',
                'confirmation_date': self.confirmation_date,
                'company_id': self.company_id.id,
                'partner_id': self.partner_id.id,
                'sale_id': self.sale_order_id.id,
                'stack_ids': [(6, 0, [r.id for r in self.printing_line_ids.mapped('stack_ids')])],
            })]
            self.printing_line_ids.mapped('stack_ids.coupon_ids').write({'state': 'attenteliv'})

        else:
            # Sinon on modifie le statut des tickets
            self.printing_line_ids.mapped('stack_ids.cupon_ids').write({'state': 'done'})

        self.state = 'done'

    @api.multi
    def print_printing_order(self):
        self.ensure_one()
        coupon_ids = self.printing_line_ids.mapped('stack_ids.coupon_ids')
        coupon_ids.write({'state': 'printing'})
        self.write({'state': 'printing'})
        return coupon_ids._print_coupon()

    @api.multi
    def create_coupons(self):
        self.ensure_one()
        stack_ids = self.env['coupon.stack']
        for line in self.printing_line_ids:
            stack_ids |= line._create_stack()

    def _create_coupon_delivery(self):
        self.ensure_one()
        if self.sale_id and self.state == 'printed':
            state = 'open'
            val = {
                'state': state,
                'confirmation_date': self.confirmation_date,
                'partner_id': self.sale_order_id.partner_id.id,
                'sale_id': self.sale_order_id.id,
                'stack_ids': [(0, 0, self.stack_ids.ids)],
                'location_id': [self.sale_order_id.location_id],
            }
            return self.env['coupon.delivery.order'].create(val)


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
        for i in range(1, len(range(0, self.quantity, self.coupon_per_stack))+1):
            # Il se peut que le dernier carnet contienne moins de ticket
            coupon_per_stack = self.coupon_per_stack if (i * self.coupon_per_stack) <= self.quantity else (self.quantity - (i-1) * self.coupon_per_stack)
            stack_ids += [{
                'company_id': self.company_id.id,
                'sequence': ir_sequence.next_by_code('sheet.stack'),
                'product_qty': coupon_per_stack,
                'coupon_ids': self._prepare_coupon_to_create(coupon_per_stack),
                'printing_order_line_id': self.id,
                'sale_line_id': self.sale_order_line_id and self.sale_order_line_id.id or False,
            }]

        return self.env['coupon.stack'].create(stack_ids)

    @api.multi
    def _prepare_coupon_to_create(self, coupon_by_stack=0):
        self.ensure_one()
        coupon_key_obj = self.env['coupon.configuration']
        config = coupon_key_obj.search([('company_id', '=', self.company_id.id)], limit=1)
        assert config
        key = config.key

        # receipt_name = self.env['ir.sequence'].next_receipt(self.env.ref('seq_receipt_sequence'))
        # receipt_name = self.env.ref('seq_receipt_sequence').next_by_id()
        res = []
        ir_sequence = self.env['ir.sequence']

        for i in range(int(coupon_by_stack)):
            barcode_receipt = config.RandomEAN13(key)
            res += [(0, 0, {
                'active': True,
                'company_id': self.company_id.id,
                'sequence': ir_sequence.next_by_code('receipt.sequence'),
                'barcode': barcode_receipt,
                'barcode_trunked': barcode_receipt[:9],
                'product_id': self.product_id.id,
                'value': self.value,
                'state': 'to_print',
                'partner_id': self.printing_order_id.partner_id and self.printing_order_id.partner_id.id or False,
            })]
        return res

    # @api.multi
    # def _print_order_line_coupon(self):
    #     coupon_ids = self.mapped('stack_ids.coupon_ids')
    #     coupon_ids.write({'state': 'printing'})
    #     self.write({'state': 'printed'})
    #     return coupon_ids._print_coupon()

