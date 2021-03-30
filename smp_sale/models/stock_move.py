# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError



class StockMove(models.Model):
    _inherit = "stock.move"

    invoice_line_id = fields.Many2one(
        comodel_name='account.invoice.line',
        string='Invoice Line',
        copy=False,
        readonly=True,
    )

    @api.multi
    def _get_new_picking_values(self):
        """ Prepares a new picking for this move as it could not be assigned to
        another picking. This method is designed to be inherited. """
        res = super(StockMove, self)._get_new_picking_values()

        if self.sale_line_id:
            if self.sale_line_id.order_id.location_id:
                res['location_id'] = self.sale_line_id.order_id.location_id.id
        return res

    @api.multi
    @api.depends('state', 'picking_id', 'product_id')
    def _compute_is_quantity_done_editable(self):
        super(StockMove, self)._compute_is_quantity_done_editable()
        for move in self:
            if move.picking_id.picking_type_id.code == 'outgoing':
                if move.product_id.product_tmpl_id.invoice_policy == 'delivery':
                    move.is_quantity_done_editable = True
                elif move.picking_id.regime_id and move.product_id.apply_price_structure:
                    # sale_price_id = self.env['product.sale.price'].get_specific_records(move.date, move.product_id,
                    #                                               move.location_id if move._is_out() else move.location_dest_id,
                    #                                               move.picking_id.regime_id)
                    # if sale_price_id and sale_price_id.quantity_to_confirm:
                    #     move.is_quantity_done_editable = True
                    if move.sale_line_id.qty_to_confirm:
                        move.is_quantity_done_editable = True
                # if move.sale_line_id.quantity_to_confirm or (move.picking_id.picking_type_id.code == 'outgoing' and move.product_id.product_tmpl_id.invoice_policy == 'delivery'):

    @api.multi
    def _search_picking_for_assignation(self):
        self.ensure_one()
        # if self.product_id.unique_picking and self._is_out() and  'customer' in [self.location_id.usage,self.location_dest_id.usage]:
        if self.product_id.unique_picking:
            print('Génération un BL par article')
            return None

        picking = self.env['stock.picking'].search([
                ('group_id', '=', self.group_id.id),
                ('location_id', '=', self.location_id.id),
                ('location_dest_id', '=', self.location_dest_id.id),
                ('picking_type_id', '=', self.picking_type_id.id),
                ('printed', '=', False),
                ('state', 'in', ['draft', 'confirmed', 'waiting', 'partially_available', 'assigned'])], limit=1)
        return picking