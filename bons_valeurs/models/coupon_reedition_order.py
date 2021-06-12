 # -*- coding= utf-8 -*-

from odoo import fields, models, _, api
from odoo.exceptions import UserError


class CouponReeditionOrder(models.Model):
    _name = 'coupon.reedition.order'
    _description = 'Coupon Reedition Order'
    _order = 'name'

    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True,
                                 default=lambda self: self.env.user.company_id)
    name = fields.Char('Name', required=True, default='/', readonly=True, copy=False)
    line_ids = fields.One2many('coupon.reedition.order.line', 'printing_order_id',
                                        readonly=True, states={'draft': [('readonly', False)]})
    partner_id = fields.Many2one('res.partner', 'Customer', related='sale_order_id.partner_id',
                                 readonly=True, states={'draft': [('readonly', False)]})
    printing_date = fields.Date('Print Date', default=fields.date.today(),
                                readonly=True, states={'draft': [('readonly', False)]})
    confirmation_date = fields.Date('Confirmation Date', default=fields.date.today(), copy=False,
                                    readonly=True, states={'draft': [('readonly', False)]})
    location_id = fields.Many2one('stock.location', 'Coupon Location',
                                  readonly=True, states={'draft': [('readonly', False)]})
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Ready to print'),
        ('printing', 'Printing'),
        ('done', 'Done')], default='draft')

    def done(self):
        coupon_ids = self.env['coupon.value']
        for line in self.line_ids:
            assert line.coupon_start_id <= line.coupon_end_id
            coupon_ids += self.coupon_ids.search([('id', '>=', line.coupon_start_id),
                                                  ('id', '<=', line.coupon_end_id)])


class CouponReeditionOrderLine(models.Model):
    _name = 'coupon.reedition.order.line'
    _description = 'Coupon Reedition Order Line'

    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.user.company_id)
    printing_order_id = fields.Many2one('coupon.reedition.order')
    coupon_start_id = fields.Integer('Coupon Start Id', required=True)
    coupon_end_id = fields.Integer('Coupon End Id', required=True)
    quantity = fields.Integer('Quantity', readonly=True)



