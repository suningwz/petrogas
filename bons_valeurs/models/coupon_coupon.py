# -*- coding= utf-8 -*-

from odoo import models, fields, api, _
import random, hmac, hashlib
from odoo.tools.float_utils import float_compare, float_round, float_is_zero
from odoo.exceptions import UserError
COUPON_STATES = [
    ('to_print', 'To Print'),
    ('printing', 'Print Ongoing'),
    ('done', 'Printed'),
    ('to_deliver', 'Delivery Waiting'),
    ('circulation', 'En circulation'),
    ('return', 'Returned'),
    ('canceled', 'Canncelled'),
]


class StockLocation(models.Model):
    _inherit = 'stock.location'

    is_coupon_production = fields.Boolean('Is a Coupon Production Location', default=False)
    is_coupon_sale = fields.Boolean('Is a Coupon Sale Location', default=False)


class CouponConfiguration(models.Model):
    _name = 'coupon.configuration'
    _description = 'Coupon Configuration'

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.user.company_id)
    validity_date = fields.Integer('Number of days before coupon expiration')
    product_ids = fields.Many2many('product.product', domain=[('type', '=', 'service')])
    sale_journal_id = fields.Many2one('account.journal', 'Debit Note', domain=[('type', '=', 'sale')])
    return_journal_id = fields.Many2one('account.journal', 'Credit Note', domain=[('type', '=', 'purchase')])
    key = fields.Char('Key', size=4)

    _sql_constraints = [('company_uniq', 'unique(company_id)', 'The configuration for a company must be unique !'),]

    def RandomEAN13(self, s):
        # generate a 32 bytes hexadecimal random number
        Available = "abcdef0123456789"
        Length = 32
        rnd = random.SystemRandom()
        r = ""
        s = str(s)

        # TODO: A supprimer
        s = 'star'
        s_byte = bytes(s, 'utf-8')

        for i in range(Length):
            r += rnd.choice(Available)

        # hash s and r together
        hm = "0x" + hmac.new(s_byte, r.encode('utf-8'), hashlib.sha256).hexdigest()

        # get the first 13 digits of this number and call ean13 over it
        value = str(int(hm, 0))[-13:]

        # now build the ean13
        ean13 = self.env['barcode.nomenclature'].sanitize_ean(value)

        return ean13

    def get_product_ids(self, company_id):
        res = self.search([('company_id', '=', company_id)])
        if not res:
            raise UserError(_("""No configuration was found."""))
        res.ensure_one()
        return res

    def get_coupon_config(self, company_id):
        config =  self.search([('company_id', '=', company_id.id)], limit=1)
        if not config:
            raise UserError("No coupon configuration has been found.")
        return config

    def get_coupon_products(self, company_id):
        return self.get_coupon_config(company_id).product_ids


class CouponValue(models.Model):
    _name = 'coupon.value'
    _description = 'Coupon'
    _order = 'sequence'

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.user.company_id)
    sequence = fields.Char('Sequence', required=True)
    barcode = fields.Char('Code Bare', size=13, readonly=True)
    barcode_trunked = fields.Char('Code Bare', size=9, readonly=True)
    value = fields.Float('Coupon Value', readonly=True)
    state = fields.Selection(COUPON_STATES, 'Statut', readonly=True)
    active = fields.Boolean('Active', Default=True, readonly=True)
    stack_id = fields.Many2one('coupon.stack', 'Stack')
    partner_id = fields.Many2one('res.partner', 'Customer', required=False)
    product_id = fields.Many2one('product.product', 'Product', required=True)
    printing_order_id = fields.Many2one('coupon.printing.order', related='stack_id.printing_order_id', required=True)
    # sale_id = fields.Many2one('sale.order', related='stack_id.sale_id')
    return_id = fields.Many2one('coupon.return.order', string="Coupon Return Receipt")

    date = fields.Date('Date')
    expiration_date = fields.Date('Expiration Date')

    _sql_constraints = [('barcode_uniq', 'unique(barcode)', 'The codebare must be unique !')]

    def _print_coupon(self):
        print_by = 4
        # remained_to_print = self
        # to_print = remained_to_print[:print_by]
        # remained_to_print -= to_print
        report_id = self.env.ref('bons_valeurs.coupon_report')
        return report_id.report_action(self)

    def _get_saled_coupon(self):
        pass

    def _get_returned_coupon(self):
        pass

    def _get_in_circulation_coupon(self):
        pass

    def _get_expired_coupon_in_circulation(self):
        pass


class CouponStack(models.Model):
    _name = 'coupon.stack'
    _description = 'Coupon Stack'
    _order = 'sequence'

    sequence = fields.Char('Sequence', required=True, readonly=True, default='/')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.user.company_id)
    coupon_ids = fields.One2many('coupon.value', 'stack_id')
    product_qty = fields.Integer('Quantity')
    printing_order_line_id = fields.Many2one('coupon.printing.order.line')
    printing_order_id = fields.Many2one('coupon.printing.order', related='printing_order_line_id.printing_order_id')
    sale_line_id = fields.Many2one('sale.order.line', related='printing_order_line_id.sale_order_line_id')
    sale_id = fields.Many2one('sale.order')
    delivery_id = fields.Many2one('coupon.delivery.order')
    value_unit = fields.Float('Coupon Value Unit', required=True)
    location_id = fields.Many2one('stock.location', readonly=True, required=True)

    def get_stock(self):
        return self.read_group(domain=[('delivery_id', '=', False), ('state', '=', False)],
                               fields=['value_unit', 'product_qty', 'count:sum(product_qty)'],
                               groupby=['value_unit'], lazy=False)

    @api.model
    def _get_stack_to_reserve(self, value_unit, coupon_per_stack, number_of_stack):
        domain = [('delivery_id', '=', False), ('sale_id', '=', False),
                  ('value_unit', '=', value_unit), ('product_qty', '=', coupon_per_stack)]
        return self.search(domain, order="id asc", limit=number_of_stack)


    # @api.model
    # def reserve_stock_type_or_stack(self,value=False, value_unit=False, quantity=False, coupon_per_stack=False):
    #     domain = [('delivery_id', '=', False), ('value_unit', '=', value), ('value_unit', '=', value)]
    #     if product_qty:
    #         domain += [('product_qty', '=', product_qty)]
    #     return self.search(domain, order="id asc", limit=quantity)


class CouponTransfertReceipt(models.Model):
    _name = 'coupon.transfert.receipt'
    _description = 'Coupon Transfert Order'

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.user.company_id)



