from odoo import fields, models, api


class CouponReturnOrderWizard(models.TransientModel):
    _name = 'coupon.return.order.wizard'
    _description = 'Scanned Coupon Wizard'

    return_id = fields.Many2one('coupon.return.order', 'Coupon Return Order', readonly=True, required=True)
    line_ids = fields.One2many('coupon.return.order.line.wizard', 'return_id',string='Scanned Coupon', readonly=True)

    def confirm(self):
        coupon_ids = self.return_id.coupon_ids.search([('barecode', 'in', self.line_ids.mapped('scanned_code'))])


class CouponReturnOrderLineWizard(models.TransientModel):
    _name = 'coupon.return.order.line.wizard'
    _description = 'Scanned Coupon Wizard Lines'

    scanned_code = fields.Char('Scanned Code')
    coupon_id = fields.Many2one('coupon.value', 'Coupons')
    value = fields.Float('Value', related='coupon_id.value')
    return_id = fields.Many2one('coupon.return.order.wizard', 'Coupon Return Order', required=True)

