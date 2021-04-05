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
        vals = {}
        domain = super(SaleOrderLine, self).product_id_change()
        transport_cost_id = self.env['transport.picking'].get_transport_cost_from_sale_order_line(self)
        if transport_cost_id:
            price_unit = transport_cost_id.value
            if self.order_id.currency_id != self.order_id.pricelist_id.currency_id:
                price_unit= price_unit * self.currency_rate
            # self.update({'price_unit': price_unit})
            vals['price_unit'] = price_unit
            self.update(vals)
            # self.price_unit = price_unit
        return domain

class TransportPicking(models.Model):
    _inherit = 'transport.picking'

    def get_transport_cost_from_sale_order_line(self, so_line_id):
        so_line_id.ensure_one()
        order_id = so_line_id.order_id
        transport_cost_id = False
        transport_type = order_id.transport_type and order_id.transport_type or False
        partner_id = order_id.partner_id and order_id.partner_id or False
        location_id = order_id.location_id and order_id.location_id or False
        city_src = location_id.city_id and location_id.city_id or False
        city_dest = (partner_id and partner_id.city_id) and partner_id.city_id or False

        if city_src and city_dest and so_line_id.product_id.id == so_line_id.order_id.transport_type.charge.id:

            transport_cost_id = self.search([('city_src', '=', city_src.id), ('city_dest', '=', city_dest.id)], limit=1)

        return transport_cost_id
