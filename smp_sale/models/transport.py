# -*- coding: utf-8 -*-
from datetime import date, timedelta
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


class TransportPickingType(models.Model):
    _inherit = 'transport.picking.type'

    @api.multi
    def get_account_for_sale_order(self, line_order):
        self.ensure_one()
        line_order.ensure_one()
        if line_order.product_id == self.charge:
            return self.charge.property_account_expense_id.id
        return self.charge.property_account_income_id.id


class TransportPicking(models.Model):
    _inherit = 'transport.picking'

    def get_transport_cost_from_sale_order_line(self, transport_type, location, partner):
        city_src = location.city_id and location.city_id or False
        city_dest = partner and partner.city_id or False

        if not city_src and not city_dest:
            raise UserError(_("City Source and City Destination must be set to evaluate the cost transfert."))

        transport_cost_id = self.search([('city_src', '=', city_src.id), ('city_dest', '=', city_dest.id)], limit=1)

        return transport_cost_id


class TransportPickingType(models.Model):
    _inherit = 'transport.picking.type'