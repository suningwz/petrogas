# -*- coding: utf-8 -*-
from datetime import date,timedelta
from odoo import models, fields, api, exceptions, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero, float_compare
from odoo.addons import decimal_precision as dp


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    transport_type = fields.Many2one('transport.picking.type', 'Transport Type')
    transportor = fields.Many2one('res.partner', 'Transportor')
    transportor_is_visible = fields.Boolean(default=False)

    @api.onchange('transport_type')
    def is_transport_visible(self):
        visible = False
        if self.transport_type:
            visible = True
        self.transportor_is_visible = visible


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.onchange('product_id')
    def product_id_change(self):
        domain = super(SaleOrderLine, self).product_id_change()
        transport_cost_id = self.env['transport.picking'].get_transport_cost_from_sale_order_line(self)
        if transport_cost_id:
            price_unit = transport_cost_id.value
            if self.order_id.currency_id != self.order_id.pricelist_id.currency_id:
                price_unit= price_unit * self.currency_rate
            self.update({'price_unit': price_unit})


class TransportPicking(models.Model):
    _inherit = 'transport.picking'

    def get_transport_cost_from_sale_order_line(self, so_line_id):
        so_line_id.ensure_one()

        transport_cost_id = False
        if so_line_id.order_id.transport_type and so_line_id.partner_id.city_id and so_line_id.location_id.city_id and \
                so_line_id.product_id.id == so_line_id.order_id.transport_type.charge.id:

            city_src = so_line_id.origin_move_id.location_id
            city_dest = so_line_id.location_id.city_id

            transport_cost_id = self.search([('city_src', '=', city_src.id), ('city_dest', '=', city_dest.id)], limit=1)

        return transport_cost_id
