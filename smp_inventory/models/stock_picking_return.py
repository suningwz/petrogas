# -*- coding: utf-8 -*-
# Part of Odoo. See ICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round


class ReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'
    # _description = 'Return Picking'
    #
    # picking_id = fields.Many2one('stock.picking')
    # product_return_moves = fields.One2many('stock.return.picking.line', 'wizard_id', 'Moves')
    # move_dest_exists = fields.Boolean('Chained Move Exists', readonly=True)
    # original_location_id = fields.Many2one('stock.location')
    # parent_location_id = fields.Many2one('stock.location')
    # location_id = fields.Many2one(
    #     'stock.location', 'Return Location',
    #     domain="['|', ('id', '=', original_location_id), ('return_location', '=', True)]")

    @api.model
    def default_get(self, fields):
        if len(self.env.context.get('active_ids', list())) > 1:
            raise UserError(_("You may only return one picking at a time."))
        res = super(ReturnPicking, self).default_get(fields)

        move_dest_exists = False
        product_return_moves = []
        picking = self.env['stock.picking'].browse(self.env.context.get('active_id'))
        if picking:
            res.update({'picking_id': picking.id})
            if picking.state != 'done':
                raise UserError(_("You may only return Done pickings."))
            for move in picking.move_lines:
                if move.scrapped:
                    continue
                if move.move_dest_ids:
                    move_dest_exists = True
                quantity = move.product_uom_qty - sum(move.move_dest_ids.filtered(lambda m: m.state in ['partially_available', 'assigned', 'done']).\
                                                  mapped('move_line_ids').mapped('product_uom_qty'))
                # quantity = move.product_qty - sum(move.move_dest_ids.filtered(lambda m: m.state in ['partially_available', 'assigned', 'done']).\
                #                                   mapped('move_line_ids').mapped('product_qty'))

                quantity = float_round(quantity, precision_rounding=move.product_uom.rounding)
                product_return_moves.append((0, 0, {'product_id': move.product_id.id, 'quantity': quantity, 'move_id': move.id, 'uom_id': move.product_uom.id}))
                # product_return_moves.append((0, 0, {'product_id': move.product_id.id, 'quantity': quantity, 'move_id': move.id, 'uom_id': move.product_id.uom_id.id}))

            if not product_return_moves:
                raise UserError(_("No products to return (only lines in Done state and not fully returned yet can be returned)."))
            if 'product_return_moves' in fields:
                res.update({'product_return_moves': product_return_moves})
            if 'move_dest_exists' in fields:
                res.update({'move_dest_exists': move_dest_exists})
            if 'parent_location_id' in fields and picking.location_id.usage == 'internal':
                res.update({'parent_location_id': picking.picking_type_id.warehouse_id and picking.picking_type_id.warehouse_id.view_location_id.id or picking.location_id.location_id.id})
            if 'original_location_id' in fields:
                res.update({'original_location_id': picking.location_id.id})
            if 'location_id' in fields:
                location_id = picking.location_id.id
                if picking.picking_type_id.return_picking_type_id.default_location_dest_id.return_location:
                    location_id = picking.picking_type_id.return_picking_type_id.default_location_dest_id.id
                res['location_id'] = location_id
        return res

    @api.model
    def _prepare_move_default_values(self, return_line, new_picking):

        vals = {
            'product_id': return_line.product_id.id,
            'product_uom_qty': return_line.quantity,
            'product_uom': return_line.uom_id.id,
            # 'product_uom': return_line.product_id.uom_id.id,
            'picking_id': new_picking.id,
            'state': 'draft',
            'date_expected': fields.Datetime.now(),
            'location_id': return_line.move_id.location_dest_id.id,
            'location_dest_id': self.location_id.id or return_line.move_id.location_id.id,
            'picking_type_id': new_picking.picking_type_id.id,
            'warehouse_id': self.picking_id.picking_type_id.warehouse_id.id,
            'origin_returned_move_id': return_line.move_id.id,
            'procure_method': 'make_to_stock',
        }
        if return_line.move_id.inter_uom_factor:
            vals['inter_uom_factor'] = return_line.move_id.inter_uom_factor
        return vals

    # @api.model
    def create_returns(self):
        res = super(ReturnPicking, self).create_returns()
        stock_move_ids =  self.env['stock.picking'].browse([res['res_id']]).mapped('move_lines')

        """Create invoice return"""
        invoice_line_id = stock_move_ids.mapped('invoice_line_id')



        # for stock_move in stock_move_ids:
        #     if stock_move.origin_returned_move_id and stock_move.origin_returned_move_id.mapped('charges_ids'):
        #         for charge in stock_move.origin_returned_move_id.mapped('charges_ids'):
        #             stock_move.charges_ids.create({
        #                 'rubrique_id': charge.rubrique_id.id,
        #                 'cost': -charge.cost,
        #                 'purchase_charge_id': charge.purchase_charge_id.id,
        #                 'stock_move_id': stock_move.id,
        #             })
        #         stock_move.landed_cos_value += -charge.cost
        return res

class StockReturnPickingLine(models.TransientModel):
    _inherit = "stock.return.picking.line"

    to_refund = fields.Boolean(string="To Refund (update SO/PO)", help='Trigger a decrease of the delivered/received quantity in the associated Sale Order/Purchase Order', default=True)
