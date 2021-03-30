# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import timeit
from datetime import datetime
from dateutil import relativedelta
from itertools import groupby
from operator import itemgetter

from odoo import api, fields, models, tools, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError
from odoo.osv import expression
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools.float_utils import float_compare, float_round, float_is_zero
from collections import defaultdict
import logging
import xlsxwriter as xls
import io, base64
import pandas as pd

_logger = logging.getLogger(__name__)


class PickingType(models.Model):
    _inherit = 'stock.picking.type'

    internal_type = fields.Selection([('reclassement','Reclassement'),('transfert','Transfert'),('inventory','Inventory')],'Type Interne', help="Allows to differentiate the types of internal operations.")
    no_picking = fields.Boolean('To not generate picking', default=False, help="""Makecost_valuation_triggers generation of pickings not mandatory such as for reclassification""")
    # cost_valuation_trigger = fields.Boolean('Trigger Cost reevaluation', default=False, help="""This type of mouvement is considered in the stock cost reevaluation""")
    trigger_cost_valuation = fields.Boolean('Trigger Cost reevaluation', default=False, help="""This type of mouvement is considered in the stock cost reevaluation""")

    @api.multi
    @api.depends('code')
    def onchange_code(self):
        for r in self:
            if r.code != 'internal':
                r.internal_type = None
                r.no_picking = False


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    stock_move_id = fields.Many2one('stock.move', 'Stock moves')
    charge_id = fields.Many2one('stock.move.charges', 'Charges Logistique')


class StockMove(models.Model):
    _inherit = "stock.move"

    internal_picking_line_id = fields.Many2one('internal.picking.line', string='Transfert lines',copy=False)
    reclassement_line_id = fields.Many2one('reclassement.line', string='Reclassement lines',copy=False)
    inter_uom_factor = fields.Float(string="Conversion factor", digits=(10, 4), default=lambda self: self.product_uom.factor)
    ref_uom_id = fields.Many2one('uom.uom', 'Storage Unit', related='product_id.uom_id')
    landed_cost_value = fields.Float('Landed Cost', compute='get_cost_landing', store=True)
    charges_ids = fields.One2many("stock.move.charges", 'stock_move_id')
    volume = fields.Float('Volume', required=True, digits=dp.get_precision('Product UoS'), default=lambda self: self.product_id.volume)
    weight = fields.Float('Weight', required=True, digits=dp.get_precision('Product UoS'), default=lambda self: self.product_id.weight)



    def _is_in(self):
        """ Check if the move should be considered as entering the company so that the cost method
        will be able to apply the correct logic.

        :return: True if the move is entering the company else False
        """
        if self.move_line_ids:
            for move_line in self.move_line_ids.filtered(lambda ml: not ml.owner_id):
                if not move_line.location_id._should_be_valued() and move_line.location_dest_id._should_be_valued():
                    return True
            return False
        else:
            if not self.location_id._should_be_valued() and self.location_dest_id._should_be_valued():
                return True
            return False

    def _is_out(self):
        """ Check if the move should be considered as leaving the company so that the cost method
        will be able to apply the correct logic.

        :return: True if the move is leaving the company else False
        """
        if self.move_line_ids:
            for move_line in self.move_line_ids.filtered(lambda ml: not ml.owner_id):
                if move_line.location_id._should_be_valued() and not move_line.location_dest_id._should_be_valued():
                    return True
            return False
        else:
            if self.location_id._should_be_valued() and not self.location_dest_id._should_be_valued():
                return True
            return False

    @api.depends('move_line_ids.qty_done', 'move_line_ids.product_uom_id', 'move_line_nosuggest_ids.qty_done')
    def _quantity_done_compute(self):
        """ This field represents the sum of the move lines `qty_done`. It allows the user to know
        if there is still work to do.

        We take care of rounding this value at the general decimal precision and not the rounding
        of the move's UOM to make sure this value is really close to the real sum, because this
        field will be used in `_action_done` in order to know if the move will need a backorder or
        an extra move.
        """
        for move in self:
            quantity_done = 0
            for move_line in move._get_move_lines():
                if move_line._is_same_category() and move_line.inter_uom_factor:
                    quantity_done += move_line.product_uom_id.with_context(inter_uom_factor=move_line.inter_uom_factor)._compute_quantity(move_line.qty_done, move.product_uom, round=False)
                else:
                    quantity_done += move_line.product_uom_id._compute_quantity(move_line.qty_done, move.product_uom, round=False)
            move.quantity_done = quantity_done

    @api.one
    @api.depends('state', 'product_id', 'product_qty', 'location_id')
    def _compute_string_qty_information(self):
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        void_moves = self.filtered(lambda move: move.state in ('draft', 'done', 'cancel') or move.location_id.usage != 'internal')
        other_moves = self - void_moves
        for move in void_moves:
            move.string_availability_info = ''  # 'not applicable' or 'n/a' could work too
        for move in other_moves:
            total_available = min(move.product_qty, move.reserved_availability + move.availability)
            if not move._is_same_category()[0] and move.inter_uom_factor:
                total_available = move.product_id.uom_id.with_context(inter_uom_factor=move.inter_uom_factor)._compute_quantity(total_available, move.product_uom, round=False)
            else:
                total_available = move.product_id.uom_id._compute_quantity(total_available, move.product_uom, round=False)
            total_available = float_round(total_available, precision_digits=precision)
            info = str(total_available)
            if self.user_has_groups('uom.group_uom'):
                info += ' ' + move.product_uom.name
            if move.reserved_availability:
                if move.reserved_availability != total_available:
                    # some of the available quantity is assigned and some are available but not reserved
                    reserved_available = move.product_id.uom_id.with_context(inter_uom_factor=move.inter_uom_factor)._compute_quantity(move.reserved_availability, move.product_uom, round=False)
                    reserved_available = float_round(reserved_available, precision_digits=precision)
                    info += _(' (%s reserved)') % str(reserved_available)
                else:
                    # all available quantity is assigned
                    info += _(' (reserved)')
            move.string_availability_info = info

    @api.multi
    @api.depends('charges_ids', 'charges_ids.cost')
    def get_cost_landing(self):
        for r in self:
            r.update_stock_move_value()

    @api.multi
    def update_stock_move_value(self):
        for move in self:
            # _logger.debug('Stock Move %s with id: %s, value update' % (move.name, move.id))
            if move.charges_ids:
                move.landed_cost_value = sum(move.charges_ids.filtered(lambda r: r.account_move_line_ids).mapped('cost'))
            else:
                move.landed_cost_value = 0.0

            if move.move_dest_ids:
                # value = move.value + move.landed_cost_value
                value = move.value
                if move.picking_type_id.trigger_cost_valuation:
                    value += move.landed_cost_value
                price_unit = value / move.product_qty
                for move_dest_id in move.move_dest_ids:
                    # _logger.debug('Stock Move Destination  %s with id: %s, value update' % (move_dest_id.name, move_dest_id.id))
                    dest_value = price_unit * move_dest_id.product_qty
                    move_dest_id.write({'price_unit': price_unit, 'value': dest_value})
                    move_dest_id.update_stock_move_value()
                    move_dest_id.update_account_entry_move()
                    # TODO: Fonction mettant à jour la pièce comptable de stock

            # if move.origin_returned_move_id:
            #     value = move.value + move.landed_cost_value
            #     price_unit = value / move.product_qty
            #     for move_dest_id in move.move_dest_ids:
            #         # _logger.debug('Stock Move Destination  %s with id: %s, value update' % (move_dest_id.name, move_dest_id.id))
            #         # move_dest_id.price_unit = price_unit
            #         dest_value = price_unit * move_dest_id.product_qty
            #         # move_dest_id.value = dest_value
            #         move_dest_id.write({'value': dest_value})
            #         # TODO: Fonction mettant à jour la pièce comptable de stock

    @api.one
    def _is_same_category(self):
        if self.product_id.uom_id == self.product_uom:
            return True
        else:
            return False

    @api.multi
    def name_get(self):
        result = []
        for s in self:
            if s.reference:
                name = s.origin + ' - ' + s.reference
            else:
                name = s.origin
            result.append((s.id, name))
        return result

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        """ search full name and barcode """
        args = args or []
        if operator == 'ilike' and not (name or '').strip():
            domain = []
        else:
            domain = ['|', ('reference', operator, name), ('origin', operator, name)]
        stock_move_ids = self._search(expression.AND([domain, args]), limit=limit, access_rights_uid=name_get_uid)
        return self.browse(stock_move_ids).name_get()


    @api.depends('product_uom')
    def _manual_product_qty(self):
        if self.product_id.uom_id.category_id != self.product_uom.category_id \
                and self.product_uom.category_id == self.product_id.uom_po_id.category_id:
            # self.manual_product_qty = True
            if tools.float_is_zero(self.inter_uom_factor, precision_rounding=self.product_uom.rounding):
                self.inter_uom_factor = self.product_id.inter_uom_factor

    @api.constrains('product_uom')
    def _check_uom(self):
        moves_error = self.filtered(lambda move: move.product_id.uom_id.category_id != move.product_uom.category_id
                                    and move.product_id.uom_po_id.category_id != move.product_uom.category_id
                                    and move.product_id.is_uom_inter_category)
        if moves_error:
            user_warning = _('You cannot perform the move because the unit of measure has a different category as the product unit of measure.')
            for move in moves_error:
                user_warning += _('\n\n%s --> Product UoM is %s (%s) - Move UoM is %s (%s)') % (move.product_id.display_name, move.product_id.uom_id.name, move.product_id.uom_id.category_id.name, move.product_uom.name, move.product_uom.category_id.name)
            user_warning += _('\n\nBlocking: %s') % ' ,'.join(moves_error.mapped('name'))
            raise UserError(user_warning)

    @api.multi
    @api.depends('move_line_ids.product_qty')
    def _compute_reserved_availability(self):
        """ Fill the `availability` field on a stock move, which is the actual reserved quantity
        and is represented by the aggregated `product_qty` on the linked move lines. If the move
        is force assigned, the value will be 0.
        """
        result = {data['move_id'][0]: data['product_qty'] for data in self.env['stock.move.line'].read_group([('move_id', 'in', self.ids)], ['move_id','product_qty'], ['move_id'])}
        for rec in self:
            if rec.product_id.uom_id.category_id != rec.product_uom.category_id and rec.product_uom.category_id == rec.product_id.uom_po_id.category_id:
                product_qty = result.get(rec.id, 0.0)
                # product_po_qty = rec.product_uom._compute_quantity(rec.product_uom_qty, rec.product_id.uom_po_id)
                precision = max(rec.product_id.uom_id.rounding, rec.product_uom.rounding)
                if tools.float_is_zero(rec.inter_uom_factor, precision_rounding=precision):
                    product_po_qty = product_qty / rec.product_id.inter_uom_factor
                else:
                    product_po_qty = product_qty / rec.inter_uom_factor
                rec.reserved_availability = product_po_qty
            else:
                rec.reserved_availability = rec.product_id.uom_id._compute_quantity(result.get(rec.id, 0.0), rec.product_uom, rounding_method='HALF-UP')

    def _action_assign(self):
        """ Reserve stock moves by creating their stock move lines. A stock move is
        considered reserved once the sum of `product_qty` for all its move lines is
        equal to its `product_qty`. If it is less, the stock move is considered
        partially available.
        """
        assigned_moves = self.env['stock.move']
        partially_available_moves = self.env['stock.move']
        # Read the `reserved_availability` field of the moves out of the loop to prevent unwanted
        # cache invalidation when actually reserving the move.
        reserved_availability = {move: move.reserved_availability for move in self}
        roundings = {move: move.product_id.uom_id.rounding for move in self}
        for move in self.filtered(lambda m: m.state in ['confirmed', 'waiting', 'partially_available']):
            rounding = roundings[move]
            missing_reserved_uom_quantity = move.product_uom_qty - reserved_availability[move]
            if move.product_id.uom_id.category_id != move.product_uom.category_id and move.product_uom.category_id == move.product_id.uom_po_id.category_id:
                product_po_qty = move.product_uom._compute_quantity(missing_reserved_uom_quantity, move.product_id.uom_po_id, rounding_method='HALF-UP')
                missing_reserved_quantity = product_po_qty * move.inter_uom_factor
            else:
                missing_reserved_quantity = move.product_uom._compute_quantity(missing_reserved_uom_quantity, move.product_id.uom_id, rounding_method='HALF-UP')
            if move.location_id.should_bypass_reservation()\
                    or move.product_id.type == 'consu':
                # create the move line(s) but do not impact quants
                if move.product_id.tracking == 'serial' and (move.picking_type_id.use_create_lots or move.picking_type_id.use_existing_lots):
                    for i in range(0, int(missing_reserved_quantity)):
                        self.env['stock.move.line'].create(move._prepare_move_line_vals(quantity=1))
                else:
                    to_update = move.move_line_ids.filtered(lambda ml: ml.product_uom_id == move.product_uom and
                                                            ml.location_id == move.location_id and
                                                            ml.location_dest_id == move.location_dest_id and
                                                            ml.picking_id == move.picking_id and
                                                            not ml.lot_id and
                                                            not ml.package_id and
                                                            not ml.owner_id)
                    if to_update:
                        to_update[0].product_uom_qty += missing_reserved_uom_quantity
                    else:
                        self.env['stock.move.line'].create(move._prepare_move_line_vals(quantity=missing_reserved_quantity))
                assigned_moves |= move
            else:
                if not move.move_orig_ids:
                    if move.procure_method == 'make_to_order':
                        continue
                    # If we don't need any quantity, consider the move assigned.
                    need = missing_reserved_quantity
                    if float_is_zero(need, precision_rounding=rounding):
                        assigned_moves |= move
                        continue
                    # Reserve new quants and create move lines accordingly.
                    forced_package_id = move.package_level_id.package_id or None
                    available_quantity = self.env['stock.quant']._get_available_quantity(move.product_id, move.location_id, package_id=forced_package_id)
                    if available_quantity <= 0:
                        continue
                    taken_quantity = move._update_reserved_quantity(need, available_quantity, move.location_id, package_id=forced_package_id, strict=False)
                    if float_is_zero(taken_quantity, precision_rounding=rounding):
                        continue
                    if float_compare(need, taken_quantity, precision_rounding=rounding) == 0:
                        assigned_moves |= move
                    else:
                        partially_available_moves |= move
                else:
                    # Check what our parents brought and what our siblings took in order to
                    # determine what we can distribute.
                    # `qty_done` is in `ml.product_uom_id` and, as we will later increase
                    # the reserved quantity on the quants, convert it here in
                    # `product_id.uom_id` (the UOM of the quants is the UOM of the product).
                    move_lines_in = move.move_orig_ids.filtered(lambda m: m.state == 'done').mapped('move_line_ids')
                    keys_in_groupby = ['location_dest_id', 'lot_id', 'result_package_id', 'owner_id']

                    def _keys_in_sorted(ml):
                        return (ml.location_dest_id.id, ml.lot_id.id, ml.result_package_id.id, ml.owner_id.id)

                    grouped_move_lines_in = {}
                    for k, g in groupby(sorted(move_lines_in, key=_keys_in_sorted), key=itemgetter(*keys_in_groupby)):
                        qty_done = 0
                        for ml in g:
                            if ml.inter_uom_factor:
                                qty_done += ml.product_uom_id.with_context(inter_uom_factor=ml.inter_uom_factor)._compute_quantity(ml.qty_done, ml.product_id.uom_id)
                            else:
                                qty_done += ml.product_uom_id._compute_quantity(ml.qty_done, ml.product_id.uom_id)
                        grouped_move_lines_in[k] = qty_done
                    move_lines_out_done = (move.move_orig_ids.mapped('move_dest_ids') - move)\
                        .filtered(lambda m: m.state in ['done'])\
                        .mapped('move_line_ids')
                    # As we defer the write on the stock.move's state at the end of the loop, there
                    # could be moves to consider in what our siblings already took.
                    moves_out_siblings = move.move_orig_ids.mapped('move_dest_ids') - move
                    moves_out_siblings_to_consider = moves_out_siblings & (assigned_moves + partially_available_moves)
                    reserved_moves_out_siblings = moves_out_siblings.filtered(lambda m: m.state in ['partially_available', 'assigned'])
                    move_lines_out_reserved = (reserved_moves_out_siblings | moves_out_siblings_to_consider).mapped('move_line_ids')
                    keys_out_groupby = ['location_id', 'lot_id', 'package_id', 'owner_id']

                    def _keys_out_sorted(ml):
                        return (ml.location_id.id, ml.lot_id.id, ml.package_id.id, ml.owner_id.id)

                    grouped_move_lines_out = {}
                    for k, g in groupby(sorted(move_lines_out_done, key=_keys_out_sorted), key=itemgetter(*keys_out_groupby)):
                        qty_done = 0
                        for ml in g:
                            qty_done += ml.product_uom_id._compute_quantity(ml.qty_done, ml.product_id.uom_id)
                        grouped_move_lines_out[k] = qty_done
                    for k, g in groupby(sorted(move_lines_out_reserved, key=_keys_out_sorted), key=itemgetter(*keys_out_groupby)):
                        grouped_move_lines_out[k] = sum(self.env['stock.move.line'].concat(*list(g)).mapped('product_qty'))
                    available_move_lines = {key: grouped_move_lines_in[key] - grouped_move_lines_out.get(key, 0) for key in grouped_move_lines_in.keys()}
                    # pop key if the quantity available amount to 0
                    available_move_lines = dict((k, v) for k, v in available_move_lines.items() if v)

                    if not available_move_lines:
                        continue
                    for move_line in move.move_line_ids.filtered(lambda m: m.product_qty):
                        if available_move_lines.get((move_line.location_id, move_line.lot_id, move_line.result_package_id, move_line.owner_id)):
                            available_move_lines[(move_line.location_id, move_line.lot_id, move_line.result_package_id, move_line.owner_id)] -= move_line.product_qty
                    for (location_id, lot_id, package_id, owner_id), quantity in available_move_lines.items():
                        need = move.product_qty - sum(move.move_line_ids.mapped('product_qty'))
                        # `quantity` is what is brought by chained done move lines. We double check
                        # here this quantity is available on the quants themselves. If not, this
                        # could be the result of an inventory adjustment that removed totally of
                        # partially `quantity`. When this happens, we chose to reserve the maximum
                        # still available. This situation could not happen on MTS move, because in
                        # this case `quantity` is directly the quantity on the quants themselves.
                        available_quantity = self.env['stock.quant']._get_available_quantity(
                            move.product_id, location_id, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=True)
                        if float_is_zero(available_quantity, precision_rounding=rounding):
                            continue
                        taken_quantity = move.with_context(inter_uom_factor=move.inter_uom_factor)._update_reserved_quantity(need, min(quantity, available_quantity), location_id, lot_id, package_id, owner_id)
                        if float_is_zero(taken_quantity, precision_rounding=rounding):
                            continue
                        if float_is_zero(need - taken_quantity, precision_rounding=rounding):
                            assigned_moves |= move
                            break
                        partially_available_moves |= move
        partially_available_moves.write({'state': 'partially_available'})
        assigned_moves.write({'state': 'assigned'})
        self.mapped('picking_id')._check_entire_pack()

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        self.ensure_one()
        # apply putaway
        location_dest_id = self.location_dest_id.get_putaway_strategy(self.product_id).id or self.location_dest_id.id
        vals = {
            'move_id': self.id,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_uom.id,
            'location_id': self.location_id.id,
            'location_dest_id': location_dest_id,
            'picking_id': self.picking_id.id,
        }
        if quantity:
            if self.product_id.uom_id.category_id != self.product_uom.category_id \
                    and self.product_uom.category_id == self.product_id.uom_po_id.category_id:
                # from product_id.uom_id to product_uom_id
                product_po_qty = quantity / self.inter_uom_factor
                uom_quantity = self.product_id.uom_po_id._compute_quantity(product_po_qty, self.product_uom, rounding_method='HALF-UP')
                uom_quantity_back_to_product_uom = product_po_qty * self.inter_uom_factor
            else:
                uom_quantity = self.product_id.uom_id._compute_quantity(quantity, self.product_uom, rounding_method='HALF-UP')
                uom_quantity_back_to_product_uom = self.product_uom._compute_quantity(uom_quantity, self.product_id.uom_id, rounding_method='HALF-UP')
            rounding = self.env['decimal.precision'].precision_get('Product Unit of Measure')
            if float_compare(quantity, uom_quantity_back_to_product_uom, precision_digits=rounding) == 0:
                vals = dict(vals, product_uom_qty=uom_quantity)
            else:
                vals = dict(vals, product_uom_qty=quantity, product_uom_id=self.product_id.uom_id.id)
        if reserved_quant:
            vals = dict(
                vals,
                location_id=reserved_quant.location_id.id,
                lot_id=reserved_quant.lot_id.id or False,
                package_id=reserved_quant.package_id.id or False,
                owner_id =reserved_quant.owner_id.id or False,
            )
        return vals

    @api.multi
    @api.depends('state', 'picking_id', 'product_id')
    def _compute_is_quantity_done_editable(self):
        res = super(StockMove, self)._compute_is_quantity_done_editable()
        for move in self:
            if not move.product_id:
                move.is_quantity_done_editable = False
            elif not move.picking_id.immediate_transfer and move.picking_id.state == 'draft':
                move.is_quantity_done_editable = False
            elif move.picking_id.is_locked and move.state in ('done', 'cancel'):
                move.is_quantity_done_editable = False
            elif move.show_details_visible:
                if move.picking_id.picking_type_id.code == 'incoming' \
                        and move.product_id.product_tmpl_id.purchase_method == 'receive':
                    move.is_quantity_done_editable = True
                elif move.picking_id.picking_type_id.code == 'outgoing' \
                        and move.product_id.product_tmpl_id.purchase_method == 'delivery':
                    move.is_quantity_done_editable = True
                elif move.picking_id.picking_type_id.code == 'internal':
                    move.is_quantity_done_editable = True
                else:
                    move.is_quantity_done_editable = False
            elif move.show_operations:
                move.is_quantity_done_editable = False

            else:
                move.is_quantity_done_editable = True

    @api.multi
    def product_price_update_before_done(self, forced_qty=None):
        self.product_price_update_before_done_per_location(forced_qty)

    @api.multi
    def product_price_update_before_done_per_location(self, forced_qty=None):
        StockQuant = self.env['stock.quant']
        tmpl_dict = defaultdict(lambda: 0.0)
        std_price_update = {}

        for move in self.filtered(lambda move: move._is_in() and not move.origin_returned_move_id and move.product_id.cost_method == 'average'):
            # TODO: On détermine la location pour les transfert
            # TODO: On détermine la location pour les achats

            if move.location_id._should_be_valued():
                location_id = move.location_id
            elif move.location_dest_id._should_be_valued():
                location_id = move.location_dest_id
            else:
                raise UserError(""" Please check the type of operation for a correct valuation.""")

            # TODO: On récupère le stock_quant
            quant_id = StockQuant._gather(move.product_id, location_id)
            product_tot_qty_available_all_loc = move.product_id.qty_available + tmpl_dict[move.product_id.id]
            product_tot_qty_available = quant_id.quantity
            rounding = move.product_id.uom_id.rounding
            
            if move.product_id.uom_id.category_id != move.product_uom.category_id \
                    and move.product_uom.category_id == move.product_id.uom_po_id.category_id:
                product_po_qty = move.product_uom._compute_quantity(move.quantity_done, move.product_id.uom_po_id)
                qty_done = product_po_qty * move.inter_uom_factor
            else:
                qty_done = move.product_uom._compute_quantity(move.quantity_done, move.product_id.uom_id)

            # cost_landing = move.get_cost_landing()
            cost_landing = move.landed_cost_value

            # TODO: Si stock existant = 0 on récupére le cout du stock_move.
            if float_is_zero(product_tot_qty_available, precision_rounding=rounding):
                new_std_price = move._get_price_unit() + cost_landing
                qty = qty_done

            # TODO: Si stock existant != 0 mais pas de cout il s'agit d'une initilisation donc on lance la valorisation.
            # elif float_is_zero(product_tot_qty_available + move.product_qty, precision_rounding=rounding) or \
            #         float_is_zero(product_tot_qty_available + qty_done, precision_rounding=rounding):
            # elif not float_is_zero(product_tot_qty_available, precision_rounding=rounding) and  not float_is_zero(quant_id.cost, 1):
            #     new_std_price = move._get_price_unit()
            else:
                # Get the standard price
                # TODO: Si stock existant != 0 mais pas de cout il s'agit d'une initilisation donc on lance la valorisation.

                # TODO: Si ancien cout existant nn récupére le cout existant dans stock_quant.
                # amount_unit = std_price_update.get((move.company_id.id, move.product_id.id)) or move.product_id.standard_price
                amount_unit = quant_id.cost
                qty = forced_qty or qty_done
                actual_value = amount_unit * product_tot_qty_available
                operation_value_unit = move._get_price_unit()
                operation_value = operation_value_unit * qty_done
                operation_value_in = operation_value + cost_landing * qty_done
                # operation_value_in_unit = operation_value_in / qty_done


                new_value = actual_value + operation_value_in
                new_quantity = product_tot_qty_available  + qty_done
                new_std_price = new_value / new_quantity

            if not quant_id:
                quant_id = StockQuant.sudo().create({
                        'product_id': move.product_id.id,
                        'location_id': location_id.id,
                        'quantity': 0,
                        'in_date': move.date_expected,
                    })
            quant_id.cost = new_std_price

            # raise UserWarning("""Atention dfsfdf""")

            tmpl_dict[move.product_id.id] += qty_done
            new_std_price_all_location = ((move.product_id.standard_price * product_tot_qty_available_all_loc) +
                                          ((move._get_price_unit() + cost_landing) * qty)) / (product_tot_qty_available_all_loc + qty)
            move.product_id.with_context(force_company=move.company_id.id).sudo().write({'standard_price': new_std_price_all_location})
            std_price_update[move.company_id.id, move.product_id.id] = new_std_price

        return True

    @api.multi
    def _get_price_unit(self):
        """ Returns the unit price for the move"""
        self.ensure_one()
        if self.origin_returned_move_id:
            self.origin_returned_move_id.ensure_one()
            price_unit = self.origin_returned_move_id.price_unit
            # price_unit = -1*self.origin_returned_move_id.price_unit
            return  price_unit
        elif self.move_orig_ids and not self.origin_returned_move_id:
            self.move_orig_ids.ensure_one()
            price_unit = (self.move_orig_ids.value + self.move_orig_ids.landed_cost_value) / self.move_orig_ids.product_qty
            return price_unit
        # elif self.internal_picking_line_id and (self._is_in() or self._is_scrapped()):
        #     """On retrouve le cout d'origine à travers la ligne internal_picking_line_id d'origine"""
        #     self.move_orig_ids.ensure_one()
        #     price_unit = (self.move_orig_ids.value + self.move_orig_ids.landed_cost_value) / self.move_orig_ids.product_qty
        #     # price_unit = self.internal_picking_line_id.cmp_out_amount + self.internal_picking_line_id.charge_out_amount
        #
        #     # TODO: Vérifier conversion des unités
        #     if self.internal_picking_line_id.product_uom.id != self.product_id.uom_id.id:
        #         price_unit *= self.internal_picking_line_id.product_uom.factor / self.product_id.uom_id.factor
        #     return price_unit
        elif self.purchase_line_id and self.product_id.id == self.purchase_line_id.product_id.id:
            line = self.purchase_line_id
            order = line.order_id
            price_unit = line.price_unit
            if line.taxes_id:
                price_unit = line.taxes_id.with_context(round=False).compute_all(price_unit, currency=line.order_id.currency_id, quantity=1.0)['total_excluded']
            if line.product_uom.id != line.product_id.uom_id.id:
                if line.product_id.uom_id.category_id != line.product_uom.category_id and \
                        line.product_id.uom_po_id.category_id == line.product_uom.category_id:
                    price_unit *= (line.product_uom.factor / line.product_id.uom_po_id.factor) / self.inter_uom_factor
                else:
                    price_unit *= line.product_uom.factor / line.product_id.uom_id.factor
            if order.currency_id != order.company_id.currency_id:
                # The date must be today, and not the date of the move since the move move is still
                # in assigned state. However, the move date is the scheduled date until move is
                # done, then date of actual move processing. See:
                # https://github.com/odoo/odoo/blob/2f789b6863407e63f90b3a2d4cc3be09815f7002/addons/stock/models/stock_move.py#L36
                # if order.env.context.get('force_currency_rate')
                price_unit = order.currency_id.with_context(force_currency_rate=order.currency_rate)._convert(
                    price_unit, order.company_id.currency_id, order.company_id, fields.Date.context_today(self), round=False)
            return price_unit
        elif self.inventory_id:
            self.price_unit
        price_unit = super(StockMove, self)._get_price_unit()
        return price_unit

    @api.multi
    def _get_accounting_data_for_valuation(self):
        """ Return the accounts and journal to use to post Journal Entries for
        the real-time valuation of the quant. """
        self.ensure_one()
        journal_id, acc_src, acc_dest, acc_valuation = super(StockMove, self)._get_accounting_data_for_valuation()
        accounts_data = self.product_id.product_tmpl_id.get_product_accounts()

        if self.location_id.valuation_out_account_id:
            acc_src = self.location_id.valuation_out_account_id.id
        elif self.location_id.usage == 'transit':
            acc_src = accounts_data['stock_transit'].id
        elif self.location_id.usage == 'inventory' and self.location_id.scrap_location:
            acc_src = accounts_data['stock_loss'].id
        else:
            acc_src = accounts_data['stock_input'].id

        if self.location_dest_id.valuation_in_account_id:
            acc_dest = self.location_dest_id.valuation_in_account_id.id
        elif self.location_dest_id.usage == 'transit':
            acc_dest = accounts_data['stock_transit'].id
        elif self.location_dest_id.usage == 'inventory' and self.location_dest_id.scrap_location:
            acc_dest = accounts_data['stock_loss'].id
        elif self.location_dest_id.usage == 'reclassement':
            move_dest_id = self.move_dest_ids
            move_dest_id.ensure_one()
            accounts_dest_data = move_dest_id.product_id.product_tmpl_id.get_product_accounts()
            if accounts_dest_data.get('stock_valuation', False):
                acc_dest = accounts_dest_data['stock_valuation'].id
            else:
                raise("""Aucun de valorisation de stock, trouvé pour le mouvement d'entré de reclassement""")
        else:
            acc_dest = accounts_data['stock_output'].id

        acc_valuation = accounts_data.get('stock_valuation', False)
        if acc_valuation:
            acc_valuation = acc_valuation.id
        if not accounts_data.get('stock_journal', False):
            raise UserError(_(
                'You don\'t have any stock journal defined on your product category, check if you have installed a chart of accounts.'))
        if not acc_src:
            raise UserError(_(
                'Cannot find a stock input account for the product %s. You must define one on the product category, or on the location, before processing this operation.') % (
                                self.product_id.display_name))
        if not acc_dest:
            raise UserError(_(
                'Cannot find a stock output account for the product %s. You must define one on the product category, or on the location, before processing this operation.') % (
                                self.product_id.display_name))
        if not acc_valuation:
            raise UserError(_(
                'You don\'t have any stock valuation account defined on your product category. You must define one before processing this operation.'))
        journal_id = accounts_data['stock_journal'].id

        return journal_id, acc_src, acc_dest, acc_valuation

    @api.multi
    def _is_scrapped(self):
        """ Check if the move should be considered as a scrapped opération from an another  the company so that the cost method
        will be able to apply the correct logic.

        :return: True if the move is leaving the company else False
        """
        self.ensure_one()
        for move_line in self.move_line_ids.filtered(lambda ml: not ml.owner_id):
            if move_line.location_id.usage == 'transit' and (
                    move_line.location_dest_id.usage == 'inventory' and move_line.location_dest_id.scrap_location):
                return True
        return False

    @api.multi
    def _create_account_move_line(self, credit_account_id, debit_account_id, journal_id):
        self.ensure_one()
        AccountMove = self.env['account.move']
        quantity = self.env.context.get('forced_quantity', self.product_qty)
        # quantity = quantity if self._is_in() else -1 * quantity

        # Make an informative `ref` on the created account move to differentiate between classic
        # movements, vacuum and edition of past moves.
        ref = self.picking_id.name
        if self.env.context.get('force_valuation_amount'):
            if self.env.context.get('forced_quantity') == 0:
                ref = 'Revaluation of %s (negative inventory)' % ref
            elif self.env.context.get('forced_quantity') is not None:
                ref = 'Correction of %s (modification of past move)' % ref

        move_lines = []

        total_cost = 0.0

        """ Seul les BL généront de nouveaux frais de ventes"""
        if self.picking_type_id.code == 'outgoing':
            if self.product_id.apply_price_structure and not self.picking_id.regime_id and self._is_out() \
                    and self.location_dest_id.usage == 'customer':
                raise UserError(_(
                    """Attention !!! Afin d'appliquer les charges liées à une structure de prix, un régime de vente doit
                     être indiqué sur le bon de livraison """))

            if self.product_id.apply_price_structure and self.picking_id.regime_id:
                # move_lines += self.with_context(forced_ref=ref).prepare_sale_charges_account_move_line(quantity)
                move_lines += self.charges_ids.prepare_sale_charges_account_move_line(quantity, self.with_context(forced_ref=ref))

        elif self.picking_type_id.code in ['internal', 'incoming']:

            if self.picking_type_id.internal_type == 'transfert':
                # move_lines += self.with_context(forced_ref=ref).prepare_transfert_charges_account_move_line(quantity)
                move_lines += self.charges_ids.prepare_transfert_charges_account_move_line(quantity, self.with_context(forced_ref=ref))
                for line in move_lines:
                    line[2]['stock_move_id'] = self.id
            elif self.picking_type_id.internal_type == 'reclassement':
                # move_lines += self.with_context(forced_ref=ref).prepare_reclassement_charges_account_move_line(quantity)
                self.move_dest_ids.ensure_one()
                move_lines += self.charges_ids.prepare_reclassement_charges_account_move_line(quantity, self.move_dest_ids.with_context(forced_ref=ref))
                for line in move_lines:
                    line[2]['stock_move_id'] = self.reclassement_line_id.stock_move_ids.filtered(lambda x: x._is_in()).id
            elif self.picking_type_id.code == 'incoming':
                move_lines += self.charges_ids.prepare_purchase_charges_account_move_line(quantity, self.with_context(forced_ref=ref))
                for line in move_lines:
                    line[2]['stock_move_id'] = self.id

            if move_lines:
                # total_charges = sum(move_lines.mapped('credit'))
                total_charges = sum([move[2]['credit'] for move in move_lines])
                if self.picking_type_id.internal_type == 'reclassement':
                    total_charges = sum(self.move_dest_ids.charges_ids.mapped('cost'))
                else:
                    total_charges = sum(self.charges_ids.mapped('cost'))
                total_cost = abs(self.value) + abs(total_charges)
                



        if total_cost:
            if self._is_out():
                if self.picking_type_id.internal_type == 'transfert':
                    self.internal_picking_line_id.charge_out_amount = total_charges / self.internal_picking_line_id.quantity_load
                if self.origin_returned_move_id:
                    move_lines += self.with_context(forced_ref=ref, force_credit_valuation_amount=total_cost)._prepare_account_move_line(quantity, abs(self.value), credit_account_id, debit_account_id)
                else:
                    move_lines += self.with_context(forced_ref=ref, force_debit_valuation_amount=total_cost)._prepare_account_move_line(quantity, abs(self.value), credit_account_id, debit_account_id)
            elif self._is_in():
                if self.picking_type_id.internal_type == 'reclassement':
                    self.reclassement_line_id.charge_in_amount = total_charges / self.reclassement_line_id.quantity_dest
                if self.picking_type_id.internal_type == 'transfert':
                    self.internal_picking_line_id.charge_in_amount = total_charges / self.internal_picking_line_id.quantity_done
                if self.origin_returned_move_id:
                    move_lines += self.with_context(forced_ref=ref, force_credit_valuation_amount=total_cost)._prepare_account_move_line(quantity, abs(self.value), credit_account_id, debit_account_id)
                else:
                    move_lines += self.with_context(forced_ref=ref, force_debit_valuation_amount=total_cost)._prepare_account_move_line(quantity, abs(self.value), credit_account_id, debit_account_id)

                # move_lines += self.with_context(forced_ref=ref, force_credit_valuation_amount=total_cost)._prepare_account_move_line(quantity, abs(self.value), credit_account_id, debit_account_id)
            else:
                raise UserError("""Impossibilité de déterminer le sens du mouvement dans cette opération comptable de transfert ou reclassement!!!""")
        else:
            move_lines += self.with_context(forced_ref=ref)._prepare_account_move_line(quantity, abs(self.value), credit_account_id, debit_account_id)

        if move_lines:
            # date = self._context.get('force_period_date', fields.Date.context_today(self))
            date = self._context.get('force_period_date', self.date_expected)
            new_account_move = AccountMove.sudo().create({
                'journal_id': journal_id,
                'line_ids': move_lines,
                'date': date,
                'ref': ref,
                'stock_move_id': self.id,
            })
            new_account_move.post()

    @api.multi
    def _prepare_account_move_line(self, qty, cost, credit_account_id, debit_account_id):
        """
        Generate the account.move.line values to post to track the stock valuation difference due to the
        processing of the given quant.
        """
        self.ensure_one()

        if self._context.get('force_valuation_amount'):
            valuation_amount = self._context.get('force_valuation_amount')
        else:
            valuation_amount = cost

        # the standard_price of the product may be in another decimal precision, or not compatible with the coinage of
        # the company currency... so we need to use round() before creating the accounting entries.
        if self._context.get('force_debit_valuation_amount'):
            debit_value = self._context.get('force_debit_valuation_amount')
        else:
            debit_value = self.company_id.currency_id.round(valuation_amount)

        # check that all data is correct
        if self.company_id.currency_id.is_zero(debit_value) and not self.env['ir.config_parameter'].sudo().get_param('stock_account.allow_zero_cost'):
            raise UserError(_("The cost of %s is currently equal to 0. Change the cost or the configuration of your product to avoid an incorrect valuation.") % (self.product_id.display_name,))
        if self._context.get('force_credit_valuation_amount'):
            credit_value = self._context.get('force_credit_valuation_amount')
        else:
            credit_value = self.company_id.currency_id.round(valuation_amount)


        valuation_partner_id = self._get_partner_id_for_valuation_lines()
        res = [(0, 0, line_vals) for line_vals in self._generate_valuation_lines_data(valuation_partner_id, qty, debit_value, credit_value, debit_account_id, credit_account_id).values()]

        return res

    @api.model
    def _run_valuation(self, quantity=None):
        """Attribut le cout du stock au movement de stock"""
        self.ensure_one()
        if self.product_id.uom_id.id != self.product_uom.id:
            print("Les unité d'entré et de stockage sont différent")
            # TODO: on appelle le wizard de conversion des mouvements²
        value_to_return = 0
        if self.origin_returned_move_id:
            # price_unit = self.product_id.standard_price
            # if self.origin_returned_move_id:
            self.origin_returned_move_id.ensure_one()
            # price_unit = -self.origin_returned_move_id.price_unit
            price_unit = self.origin_returned_move_id.price_unit
            if self._is_in():
                valued_move_lines = self.move_line_ids.filtered(lambda ml: not ml.location_id._should_be_valued()
                                                                           and ml.location_dest_id._should_be_valued()
                                                                           and not ml.owner_id)
            elif self._is_out():
                valued_move_lines = self.move_line_ids.filtered(lambda ml: ml.location_id._should_be_valued()
                                                                           and not ml.location_dest_id._should_be_valued()
                                                                           and not ml.owner_id)
            else:
                valued_move_lines = self.move_line_ids

            valued_quantity = 0
            for valued_move_line in valued_move_lines:
                if not valued_move_line._is_same_category()[0] \
                        and valued_move_line.product_uom_id.category_id == valued_move_line.product_id.uom_po_id.category_id:
                    product_po_qty = valued_move_line.product_uom_id._compute_quantity(valued_move_line.qty_done, valued_move_line.product_id.uom_po_id)
                    valued_quantity += product_po_qty * valued_move_line.inter_uom_factor
                else:
                    valued_quantity += valued_move_line.product_uom_id._compute_quantity(valued_move_line.qty_done, self.product_id.uom_id)

            if self.product_id.cost_method in ['standard', 'average']:
                curr_rounding = self.company_id.currency_id.rounding
                value = float_round(price_unit * (valued_quantity if quantity is None else quantity), precision_rounding=curr_rounding)
                value_to_return = value if quantity is None else self.value + value
                self.write({
                    'value': value_to_return,
                    'price_unit': value / valued_quantity,
                })

        elif self._is_in():
            valued_move_lines = self.move_line_ids.filtered(lambda ml: not ml.location_id._should_be_valued() and ml.location_dest_id._should_be_valued() and not ml.owner_id)
            valued_quantity = 0
            for valued_move_line in valued_move_lines:
                if not valued_move_line._is_same_category()[0] \
                        and valued_move_line.product_uom_id.category_id == valued_move_line.product_id.uom_po_id.category_id:
                    product_po_qty = valued_move_line.product_uom_id._compute_quantity(valued_move_line.qty_done, valued_move_line.product_id.uom_po_id)
                    valued_quantity += product_po_qty * valued_move_line.inter_uom_factor
                else:
                    valued_quantity += valued_move_line.product_uom_id._compute_quantity(valued_move_line.qty_done, self.product_id.uom_id)

            # Note: we always compute the fifo `remaining_value` and `remaining_qty` fields no
            # matter which cost method is set, to ease the switching of cost method.
            price_unit = self._get_price_unit()
            value = price_unit * (quantity or valued_quantity)
            value_to_return = value if quantity is None or not self.value else self.value
            vals = {
                'price_unit': price_unit,
                'value': value_to_return,
                'remaining_value': value if quantity is None else self.remaining_value + value,
            }
            vals['remaining_qty'] = valued_quantity if quantity is None else self.remaining_qty + quantity

            if self.product_id.cost_method == 'standard':
                value = self.product_id.standard_price * (quantity or valued_quantity)
                value_to_return = value if quantity is None or not self.value else self.value
                vals.update({
                    'price_unit': self.product_id.standard_price,
                    'value': value_to_return,
                })
            self.write(vals)
        elif self._is_out():
            valued_move_lines = self.move_line_ids.filtered(lambda ml: ml.location_id._should_be_valued() and not ml.location_dest_id._should_be_valued() and not ml.owner_id)
            valued_quantity = 0
            for valued_move_line in valued_move_lines:
                if not valued_move_line._is_same_category()[0] and valued_move_line.inter_uom_factor:
                    valued_quantity += valued_move_line.product_uom_id.with_context(inter_uom_factor=valued_move_line.inter_uom_factor)._compute_quantity(valued_move_line.qty_done, self.product_id.uom_id)
                else:
                    valued_quantity += valued_move_line.product_uom_id._compute_quantity(valued_move_line.qty_done, self.product_id.uom_id)
            self.env['stock.move']._run_fifo(self, quantity=quantity)
            if self.product_id.cost_method in ['standard', 'average']:
                curr_rounding = self.company_id.currency_id.rounding


                # if self.move_dest_ids and self.move_dest_ids.mapped("product_id")

                # value = -float_round(self.product_id.standard_price * (valued_quantity if quantity is None else quantity), precision_rounding=curr_rounding)
                value = float_round(self.product_id.standard_price * (valued_quantity if quantity is None else quantity), precision_rounding=curr_rounding)
                if self.product_id.cost_method in ['average']:
                    """Modifie le cout d'une ligne de stock quant"""
                    quant_id = self.env['stock.quant']._gather(self.product_id, self.location_id)
                    quant_id.ensure_one()
                    # value = -float_round(quant_id.cost * (valued_quantity if quantity is None else quantity), precision_rounding=curr_rounding)
                    value = float_round(quant_id.cost * (valued_quantity if quantity is None else quantity), precision_rounding=curr_rounding)
                value_to_return = value if quantity is None else self.value + value
                self.write({
                    'value': value_to_return,
                    'price_unit': value / valued_quantity,
                })
        elif self._is_dropshipped() or self._is_dropshipped_returned():
            curr_rounding = self.company_id.currency_id.rounding
            if self.product_id.cost_method in ['fifo']:
                price_unit = self._get_price_unit()
                # see test_dropship_fifo_perpetual_anglosaxon_ordered
                self.product_id.standard_price = price_unit
            else:
                price_unit = self.product_id.standard_price
            value = float_round(self.product_qty * price_unit, precision_rounding=curr_rounding)
            value_to_return = value if self._is_dropshipped() else -value
            # In move have a positive value, out move have a negative value, let's arbitrary say
            # dropship are positive.
            self.write({
                'value': value_to_return,
                'price_unit': price_unit if self._is_dropshipped() else -price_unit,
            })
        elif self.internal_picking_line_id and self._is_scrapped():
            valued_move_lines = self.move_line_ids
            valued_quantity = 0
            for valued_move_line in valued_move_lines:
                valued_quantity += valued_move_line.product_uom_id._compute_quantity(valued_move_line.qty_done, self.product_id.uom_id)
            self.env['stock.move']._run_fifo(self, quantity=quantity)
            if self.product_id.cost_method in ['standard', 'average']:
                curr_rounding = self.company_id.currency_id.rounding
                value = float_round(self.internal_picking_line_id.cmp_in_amount * (valued_quantity if quantity is None else quantity), precision_rounding=curr_rounding)
                value_to_return = value if quantity is None else self.value + value
                self.write({
                    'value': value_to_return,
                    'price_unit': value / valued_quantity,
                })

        if self.internal_picking_line_id:
            if self._is_out():
                self.internal_picking_line_id.cmp_out_amount = value / self.internal_picking_line_id.quantity_load
            elif self._is_in():
                self.internal_picking_line_id.cmp_in_amount = (self.internal_picking_line_id.cmp_out_amount + self.internal_picking_line_id.charge_out_amount)

        return value_to_return

    def _generate_valuation_lines_data(self, partner_id, qty, debit_value, credit_value, debit_account_id, credit_account_id):
        """ Supprime la ligne de différence de prix dans le cas des transfert
        """
        self.ensure_one()
        if self.picking_type_id.code in ['internal', 'incoming']:
            internal_type = self.picking_type_id.internal_type

            if self._context.get('forced_ref'):
                ref = self._context['forced_ref']
            else:
                if internal_type == 'transfert' or self.picking_type_id.code == 'incoming':
                    ref = self.picking_id.name
                elif internal_type == 'reclassement':
                    ref = self.origin
                else:
                    ref = self.origin


            stock_move_id_debit = self
            stock_move_id_credit = self
            if internal_type == 'reclassement':
                if self._is_out():
                    stock_move_out = self
                    stock_move_out.move_dest_ids.ensure_one()
                    stock_move_in = stock_move_out.move_dest_ids
                elif self._is_in():
                    stock_move_in = self
                    self.move_origin_ids.ensure_one()
                    stock_move_out = stock_move_in.move_orig_ids

                stock_move_id_debit = stock_move_in
                stock_move_id_credit = stock_move_out


                        # debit_line_vals = stock_move_in._prepare_account_move_line(quantity, abs(self.value), credit_account_id, debit_account_id)


            debit_line_vals = {
                'name': self.name,
                'product_id': self.product_id.id,
                'quantity': qty,
                'product_uom_id': self.product_id.uom_id.id,
                'ref': ref,
                'partner_id': partner_id,
                'debit': debit_value if debit_value > 0 else 0,
                'credit': -debit_value if debit_value < 0 else 0,
                'account_id': debit_account_id,
                'stock_move_id': stock_move_id_debit.id
            }

            credit_line_vals = {
                'name': self.name,
                'product_id': self.product_id.id,
                'quantity': qty,
                'product_uom_id': self.product_id.uom_id.id,
                'ref': ref,
                'partner_id': partner_id,
                'credit': credit_value if credit_value > 0 else 0,
                'debit': -credit_value if credit_value < 0 else 0,
                'account_id': credit_account_id,
                'stock_move_id': stock_move_id_credit.id

            }

            rslt = {'credit_line_vals': credit_line_vals, 'debit_line_vals': debit_line_vals}

        else:
            rslt = super(StockMove, self)._generate_valuation_lines_data(partner_id, qty, debit_value, credit_value,
                                                                     debit_account_id, credit_account_id)
            for line in rslt:
                rslt[line]['stock_move_id'] = self.id

        if self.purchase_line_id:
            purchase_currency = self.purchase_line_id.currency_id
            if purchase_currency != self.company_id.currency_id:
                # Do not use price_unit since we want the price tax excluded. And by the way, qty
                # is in the UOM of the product, not the UOM of the PO line.
                # product_po_uom_qty = self.purchase_line_id.price_subtotal / self.purchase_line_id.product_qty
                if self.product_id.uom_id.category_id != self.product_uom.category_id and self.product_id.uom_po_id.category_id == self.product_uom.category_id :
                    purchase_price_unit = self.purchase_line_id.price_unit / self.inter_uom_factor
                else:
                    purchase_price_unit = (
                        self.purchase_line_id.price_subtotal / self.purchase_line_id.product_uom_qty
                        if self.purchase_line_id.product_uom_qty
                        else self.purchase_line_id.price_unit
                    )
                currency_move_valuation = purchase_currency.round(purchase_price_unit * abs(qty))
                rslt['credit_line_vals']['amount_currency'] = rslt['credit_line_vals'][
                                                                  'credit'] and -currency_move_valuation or currency_move_valuation
                rslt['credit_line_vals']['currency_id'] = purchase_currency.id
                rslt['debit_line_vals']['amount_currency'] = rslt['debit_line_vals'][
                                                                 'credit'] and -currency_move_valuation or currency_move_valuation
                rslt['debit_line_vals']['currency_id'] = purchase_currency.id

        return rslt

    def action_done_stock_move_new(self):
        self.product_price_update_before_done()
        get_param = self.env['ir.config_parameter'].sudo().get_param

        self.filtered(lambda move: move.state == 'draft')._action_confirm()  # MRP allows scrapping draft moves
        moves = self.exists().filtered(lambda x: x.state not in ('done', 'cancel'))
        moves_todo = self.env['stock.move']

        # Cancel moves where necessary ; we should do it before creating the extra moves because
        # this operation could trigger a merge of moves.
        for move in moves:
            if move.quantity_done <= 0:
                if float_compare(move.product_uom_qty, 0.0, precision_rounding=move.product_uom.rounding) == 0:
                    move._action_cancel()

        # Create extra moves where necessary
        for move in moves:
            if move.state == 'cancel' or move.quantity_done <= 0:
                continue

            moves_todo |= move._create_extra_move()

        # Split moves where necessary and move quants
        for move in moves_todo:
            # To know whether we need to create a backorder or not, round to the general product's
            # decimal precision and not the product's UOM.
            rounding = self.env['decimal.precision'].precision_get('Product Unit of Measure')
            if float_compare(move.quantity_done, move.product_uom_qty, precision_digits=rounding) < 0:
                # Need to do some kind of conversion here

                qty_split = move.product_uom.with_context(inter_uom_factor=move.inter_uom_factor)._compute_quantity(move.product_uom_qty - move.quantity_done, move.product_id.uom_id, rounding_method='HALF-UP')
                if get_param('stock.propagate_uom') == '1':
                    qty_split = move.product_uom_qty - move.quantity_done
                new_move = move._split(qty_split)
                for move_line in move.move_line_ids:
                    if move_line.product_qty and move_line.qty_done:
                        # FIXME: there will be an issue if the move was partially available
                        # By decreasing `product_qty`, we free the reservation.
                        # FIXME: if qty_done > product_qty, this could raise if nothing is in stock
                        try:
                            move_line.write({'product_uom_qty': move_line.qty_done})
                        except UserError:
                            pass
                move._unreserve_initial_demand(new_move)
        moves_todo.mapped('move_line_ids')._action_done()
        # Check the consistency of the result packages; there should be an unique location across
        # the contained quants.
        for result_package in moves_todo\
                .mapped('move_line_ids.result_package_id')\
                .filtered(lambda p: p.quant_ids and len(p.quant_ids) > 1):
            if len(result_package.quant_ids.mapped('location_id')) > 1:
                raise UserError(_('You cannot move the same package content more than once in the same transfer or split the same package into two location.'))
        picking = moves_todo.mapped('picking_id')
        # moves_todo.write({'state': 'done', 'date': fields.Datetime.now()})
        moves_todo.write({'state': 'done', })
        for move in moves_todo:
            move.date = move.date_expected

        moves_todo.mapped('move_dest_ids')._action_assign()

        # We don't want to create back order for scrap moves
        # Replace by a kwarg in master
        if self.env.context.get('is_scrap'):
            res = moves_todo

        if picking:
            picking._create_backorder()
        res = moves_todo

        for move in res:
            # Apply restrictions on the stock move to be able to make
            # consistent accounting entries.
            if move._is_in() and move._is_out():
                raise UserError(_("The move lines are not in a consistent state: some are entering and other are leaving the company."))
            company_src = move.mapped('move_line_ids.location_id.company_id')
            company_dst = move.mapped('move_line_ids.location_dest_id.company_id')
            try:
                if company_src:
                    company_src.ensure_one()
                if company_dst:
                    company_dst.ensure_one()
            except ValueError:
                raise UserError(_("The move lines are not in a consistent states: they do not share the same origin or destination company."))
            if company_src and company_dst and company_src.id != company_dst.id:
                raise UserError(_("The move lines are not in a consistent states: they are doing an intercompany in a single step while they should go through the intercompany transit location."))
            move._run_valuation()
        for move in res.filtered(lambda m: m.product_id.valuation == 'real_time' and (m._is_in() or m._is_out() or m._is_dropshipped() or m._is_dropshipped_returned())):
            move._account_entry_move()
        # return res
        self.mapped('purchase_line_id').sudo()._update_received_qty()
        return res

    def action_done_stock_move(self):
        self.product_price_update_before_done()
        get_param = self.env['ir.config_parameter'].sudo().get_param

        self.filtered(lambda move: move.state == 'draft')._action_confirm()  # MRP allows scrapping draft moves
        moves = self.exists().filtered(lambda x: x.state not in ('done', 'cancel'))
        moves_todo = self.env['stock.move']

        # Cancel moves where necessary ; we should do it before creating the extra moves because
        # this operation could trigger a merge of moves.
        for move in moves:
            if move.quantity_done <= 0:
                if float_compare(move.product_uom_qty, 0.0, precision_rounding=move.product_uom.rounding) == 0:
                    move._action_cancel()

        # Create extra moves where necessary
        for move in moves:
            if move.state == 'cancel' or move.quantity_done <= 0:
                continue

            moves_todo |= move._create_extra_move()

        # Split moves where necessary and move quants
        for move in moves_todo:
            # To know whether we need to create a backorder or not, round to the general product's
            # decimal precision and not the product's UOM.
            rounding = self.env['decimal.precision'].precision_get('Product Unit of Measure')
            if float_compare(move.quantity_done, move.product_uom_qty, precision_digits=rounding) < 0:
                # Need to do some kind of conversion here

                qty_split = move.product_uom.with_context(inter_uom_factor=move.inter_uom_factor)._compute_quantity(move.product_uom_qty - move.quantity_done, move.product_id.uom_id, rounding_method='HALF-UP')
                if get_param('stock.propagate_uom') == '1':
                    qty_split = move.product_uom_qty - move.quantity_done
                new_move = move._split(qty_split)
                for move_line in move.move_line_ids:
                    if move_line.product_qty and move_line.qty_done:
                        # FIXME: there will be an issue if the move was partially available
                        # By decreasing `product_qty`, we free the reservation.
                        # FIXME: if qty_done > product_qty, this could raise if nothing is in stock
                        try:
                            move_line.write({'product_uom_qty': move_line.qty_done})
                        except UserError:
                            pass
                move._unreserve_initial_demand(new_move)
        moves_todo.mapped('move_line_ids')._action_done()
        # Check the consistency of the result packages; there should be an unique location across
        # the contained quants.
        for result_package in moves_todo\
                .mapped('move_line_ids.result_package_id')\
                .filtered(lambda p: p.quant_ids and len(p.quant_ids) > 1):
            if len(result_package.quant_ids.mapped('location_id')) > 1:
                raise UserError(_('You cannot move the same package content more than once in the same transfer or split the same package into two location.'))
        picking = moves_todo.mapped('picking_id')
        # moves_todo.write({'state': 'done', 'date': fields.Datetime.now()})
        moves_todo.write({'state': 'done'})
        moves_todo.write({'state': 'done', })
        for move in moves_todo:
            move.date = move.date_expected
        moves_todo.mapped('move_dest_ids')._action_assign()

        # We don't want to create back order for scrap moves
        # Replace by a kwarg in master
        if self.env.context.get('is_scrap'):
            return moves_todo

        if picking:
            picking._create_backorder()
        return moves_todo

    def _action_done(self):

        res = self.action_done_stock_move_new()
        # res = self.action_done_stock_move()
        # res = super(StockMove, self)._action_done()

        for move in res.filtered(lambda m: m.product_id.valuation == 'real_time' and m.internal_picking_line_id and m._is_scrapped()):
            print ('Scrapp BL: ', move.picking_id.name)
            move._account_entry_move()
        return res

    def _split(self, qty, restrict_partner_id=False):
        """ Splits qty from move move into a new move

        :param qty: float. quantity to split (given in product UoM)
        :param restrict_partner_id: optional partner that can be given in order to force the new move to restrict its choice of quants to the ones belonging to this partner.
        :param context: dictionay. can contains the special key 'source_location_id' in order to force the source location when copying the move
        :returns: id of the backorder move created """
        self = self.with_prefetch() # This makes the ORM only look for one record and not 300 at a time, which improves performance
        if self.state in ('done', 'cancel'):
            raise UserError(_('You cannot split a stock move that has been set to \'Done\'.'))
        elif self.state == 'draft':
            # we restrict the split of a draft move because if not confirmed yet, it may be replaced by several other moves in
            # case of phantom bom (with mrp module). And we don't want to deal with this complexity by copying the product that will explode.
            raise UserError(_('You cannot split a draft move. It needs to be confirmed first.'))
        if float_is_zero(qty, precision_rounding=self.product_id.uom_id.rounding) or self.product_qty <= qty:
            return self.id

        decimal_precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')

        # `qty` passed as argument is the quantity to backorder and is always expressed in the
        # quants UOM. If we're able to convert back and forth this quantity in the move's and the
        # quants UOM, the backordered move can keep the UOM of the move. Else, we'll create is in
        # the UOM of the quants.
        # uom_qty = self.product_id.uom_id.with_context(inter_uom_factor=self.inter_uom_factor)._compute_quantity(qty, self.product_uom, rounding_method='HALF-UP')
        # product_uom_qty = self.product_uom_qty
        # if float_compare(qty, self.product_uom.with_context(inter_uom_factor=self.inter_uom_factor)._compute_quantity(uom_qty, self.product_id.uom_id, rounding_method='HALF-UP'), precision_digits=decimal_precision) == 0:
        #     defaults = self._prepare_move_split_vals(uom_qty)
        # else:
        defaults = self.with_context(force_split_uom_id=self.product_uom.id)._prepare_move_split_vals(qty)

        if restrict_partner_id:
            defaults['restrict_partner_id'] = restrict_partner_id

        # TDE CLEANME: remove context key + add as parameter
        if self.env.context.get('source_location_id'):
            defaults['location_id'] = self.env.context['source_location_id']
        new_move = self.with_context(rounding_method='HALF-UP').copy(defaults)

        # FIXME: pim fix your crap
        # Update the original `product_qty` of the move. Use the general product's decimal
        # precision and not the move's UOM to handle case where the `quantity_done` is not
        # compatible with the move's UOM.
        # new_product_qty = self.product_id.uom_id.with_context(inter_uom_factor=self.inter_uom_factor)._compute_quantity(self.product_qty - qty, self.product_uom, round=False)
        # new_product_qty = self.product_id.uom_id.with_context(inter_uom_factor=self.inter_uom_factor)._compute_quantity(self.product_qty - qty, self.product_uom, round=False)
        new_product_qty = self.product_uom_qty - qty
        self.with_context(do_not_propagate=True, do_not_unreserve=True, rounding_method='HALF-UP').write({'product_uom_qty': new_product_qty})
        new_move = new_move._action_confirm(merge=False)
        return new_move.id

    def _account_entry_move(self):
        """ Accounting Valuation Entries """
        self.ensure_one()
        # if not self.picking_type_id.internal_type  == 'reclassement' and  self.picking_type_id.default_location_src_id.usage == 'reclassement':
        if self.picking_type_id.id != self.env.ref('smp_inventory.picking_type_reclassement_in').id:
            if self.product_id.type != 'product':
                # no stock valuation for consumable products
                return False
            if self.restrict_partner_id:
                # if the move isn't owned by the company, we don't make any valuation
                return False

            location_from = self.location_id
            location_to = self.location_dest_id

            company_from = self._is_out() and self.mapped('move_line_ids.location_id.company_id') or False
            company_to = self._is_in() and self.mapped('move_line_ids.location_dest_id.company_id') or False

            # Create Journal Entry for products arriving in the company; in case of routes making the link between several
            # warehouse of the same company, the transit location belongs to this company, so we don't need to create accounting entries
            if self._is_in():
                journal_id, acc_src, acc_dest, acc_valuation = self._get_accounting_data_for_valuation()
                if location_from and location_from.usage == 'customer':  # goods returned from customer
                    self.with_context(force_company=company_to.id)._create_account_move_line(acc_dest, acc_valuation, journal_id)
                else:
                    self.with_context(force_company=company_to.id)._create_account_move_line(acc_src, acc_valuation, journal_id)

            # Create Journal Entry for products leaving the company
            if self._is_out():
                journal_id, acc_src, acc_dest, acc_valuation = self._get_accounting_data_for_valuation()
                if location_to and location_to.usage == 'supplier':  # goods returned to supplier
                    self.with_context(force_company=company_from.id)._create_account_move_line(acc_valuation, acc_src, journal_id)
                else:
                    self.with_context(force_company=company_from.id)._create_account_move_line(acc_valuation, acc_dest, journal_id)

            if self.internal_picking_line_id and self._is_scrapped():
                company_from = self.internal_picking_line_id.internal_picking_id.location_src_id.company_id
                # company_to = self.internal_picking_line_id.internal_picking_id.location_dest_id.company_id
                journal_id, acc_src, acc_dest, acc_valuation = self._get_accounting_data_for_valuation()
                if location_to and location_to.usage == 'inventory':  # goods returned to supplier
                    self.with_context(force_company=company_from.id)._create_account_move_line(acc_valuation, acc_src, journal_id)
                else:
                    self.with_context(force_company=company_from.id)._create_account_move_line(acc_valuation, acc_dest, journal_id)

            if self.company_id.anglo_saxon_accounting:
                # Creates an account entry from stock_input to stock_output on a dropship move. https://github.com/odoo/odoo/issues/12687
                journal_id, acc_src, acc_dest, acc_valuation = self._get_accounting_data_for_valuation()
                if self._is_dropshipped():
                    self.with_context(force_company=self.company_id.id)._create_account_move_line(acc_src, acc_dest, journal_id)
                elif self._is_dropshipped_returned():
                    self.with_context(force_company=self.company_id.id)._create_account_move_line(acc_dest, acc_src, journal_id)

            if self.company_id.anglo_saxon_accounting:
                #eventually reconcile together the invoice and valuation accounting entries on the stock interim accounts
                self._get_related_invoices()._anglo_saxon_reconcile_valuation(product=self.product_id)

    def _assign_picking(self):
        """ Try to assign the moves to an existing picking that has not been
        reserved yet and has the same procurement group, locations and picking
        type (moves should already have them identical). Otherwise, create a new
        picking to assign them to. """
        Picking = self.env['stock.picking']
        for move in self:
            if not move.picking_type_id.no_picking:
                recompute = False
                picking = move._search_picking_for_assignation()
                if picking:
                    if picking.partner_id.id != move.partner_id.id or picking.origin != move.origin:
                        # If a picking is found, we'll append `move` to its move list and thus its
                        # `partner_id` and `ref` field will refer to multiple records. In this
                        # case, we chose to  wipe them.
                        picking.write({
                            'partner_id': False,
                            'origin': False,
                        })
                else:
                    recompute = True
                    picking = Picking.create(move._get_new_picking_values())
                move.write({'picking_id': picking.id})
                move._assign_picking_post_process(new=recompute)
                # If this method is called in batch by a write on a one2many and
                # at some point had to create a picking, some next iterations could
                # try to find back the created picking. As we look for it by searching
                # on some computed fields, we have to force a recompute, else the
                # record won't be found.
                if recompute:
                    move.recompute()
        return True

    @api.one
    @api.depends('product_id', 'product_uom', 'product_uom_qty', 'inter_uom_factor')
    def _compute_product_qty(self):
        if self.product_id.uom_id.category_id != self.product_uom.category_id:

            if self.product_id.uom_po_id.category_id == self.product_uom.category_id:
                if not self.inter_uom_factor:
                    self.inter_uom_factor = self.inter_uom_factor
                factor = self.inter_uom_factor
                product_qty = self.product_uom_qty * factor
                rounding_method = 'UP'
                self.product_qty = tools.float_round(product_qty, precision_rounding=self.product_id.uom_id.rounding, rounding_method=rounding_method)
        else:
            rounding_method = self._context.get('rounding_method', 'UP')
            self.product_qty = self.product_uom._compute_quantity(self.product_uom_qty, self.product_id.uom_id,
                                                                  rounding_method=rounding_method)

    @api.multi
    def update_account_entry_move(self):
        # if self.mapped('account_move_ids'):
        """On post toutes les pièces comptable"""
        self.mapped('account_move_ids').button_cancel()
        am_pool = self.env['account.move']
        aml_pool = self.env['account.move.line']
        start = timeit.timeit()
        for move in self:

            # TODO Identifie pièce comptable
            stock_account_move = move.account_move_ids
            if not stock_account_move:
                raise UserError(""" Aucune pièce comptable trouvée pour l'opération %s avec l'id %s !!""" % (
                move.reference, move.id))
            if len(stock_account_move) > 1 :
                raise UserError(""" Plusieurs pièces comptable pour une ligne d'article ont été trouvées avec les ID suivant: %s !!""" % ', '.join([str(id) for id in stock_account_move.ids]))
            stock_account_move.ensure_one()
            _logger.debug("""PC: %s""" % stock_account_move.ref)

            to_update = []
            if move.product_id.product_tmpl_id.type == 'product':
                """ Mise à jours des écritures de charge"""
                if move.charges_ids:
                    move_charge_account_move_line_ids = move.charges_ids.filtered(lambda r: r.account_move_line_ids and r.state != 'done')
                    for charge in move_charge_account_move_line_ids:
                        debit_line, credit_line = charge.get_move_charge_accounting_entry()
                        expense, income = charge._get_charge_account()
                        if debit_line.charge_id and debit_line.account_id.id in (expense, income):
                            to_update.append((1, debit_line.id, {'debit': abs(charge.cost)}))
                        if credit_line.charge_id and credit_line.account_id.id in (expense, income):
                            to_update.append((1, credit_line.id, {'credit': abs(charge.cost)}))

                # TODO Récupère les écriture comptable de stock
                src_value = move.value
                dest_value = move.value + sum(move.charges_ids.mapped('cost'))

                trigger_cost_valuation = move.picking_type_id.trigger_cost_valuation

                debit = src_value
                credit = src_value

                debit_line, credit_line = move.get_debit_credit_line()
                assert debit_line.ensure_one() and credit_line.ensure_one()

                # # TODO Identifie les écritures concerné
                # stock_account_move_line = stock_account_move.line_ids.filtered(lambda x: x.stock_move_id and not x.charge_id)
                # assert len(stock_account_move_line) == 2
                # assert 1 <= len(stock_account_move_line.mapped('stock_move_id')) <= 2
                # assert move in stock_account_move_line.mapped('stock_move_id')

                # TODO Identifie ligne de débit et crédit
                journal_id, acc_src, acc_dest, acc_valuation = move._get_accounting_data_for_valuation()



                # -------------------------------  Mise à jour -----------------------------------------------

                if trigger_cost_valuation:
                    debit = dest_value

                to_update.append((1, debit_line.id, {'debit': abs(debit)}))
                to_update.append((1, credit_line.id, {'credit': abs(credit)}))

                if move.picking_type_id.code == 'incoming' and move.purchase_line_id:
                    if move.purchase_line_id.order_id.currency_id != move.purchase_line_id.order_id.company_id.currency_id :
                        invoice_line_id = move.invoice_line_id
                        currency_amount = move.quantity_done * move.invoice_line_id.price_unit
                        to_update.append((1, debit_line.id, {'amount_currency': currency_amount}))
                        to_update.append((1, credit_line.id, {'amount_currency': -currency_amount}))

                debit_value = str([(x[1], x[2].get('debit')) for x in to_update if x[2].get('debit')])[1:-1]
                credit_value = str([(x[1], x[2].get('credit')) for x in to_update if x[2].get('credit')])[1:-1]

                query = """UPDATE account_move_line as aml set
                 %s = t.value,
                 balance = %s 
                from (values %s) as t(id,value) 
                where aml.id = t.id
                """
                q_debit = query % ('debit', 't.value', debit_value.replace(" ", ""))
                q_credit = query % ('credit', '-t.value', credit_value.replace(" ", ""))
                self.env.cr.execute(q_debit)
                self.env.cr.execute(q_credit)


                ids = [x[1] for x in to_update]
                self.env['account.move.line'].invalidate_cache(fnames=['debit', 'credit', 'balance'], ids=ids)
                self.env['account.move'].invalidate_cache(fnames=['line_ids'], ids=ids)

                # ------------------------------------------------------------------------------
                # Charges sans Ecriture Comptable
                to_create = []
                # created_ids = self.env['account.move.line']
                for charge in move.charges_ids.filtered(lambda r: r.state == 'draft' and not r.account_move_line_ids):
                    charge_move_line_dict = charge.prepare_account_move_line_from_charge()
                    to_create.append(charge_move_line_dict['provision'])
                    if charge_move_line_dict.get('expense', False):
                        # created_ids +=  aml_pool.create(charge_move_line_dict['expense'])
                        to_create.append(charge_move_line_dict['expense'])


                if to_create:
                    created_ids = aml_pool.create(to_create)

                    # stock_account_move.line_ids = [(4, x.id) for x in created_ids]


                for aml in stock_account_move.line_ids:
                    print("name: %s, account : %s, debit: %s, credit: %s" % (aml.name, aml.account_id.name, aml.debit, aml.credit,))
                balance = sum(stock_account_move.line_ids.mapped('debit')) - sum(stock_account_move.line_ids.mapped('credit'))
                print("To_create: ", to_create)
                print("*"*100)
                print("""PC: %s , Balance: %s""" % (stock_account_move.ref, balance))
                _logger.debug("""PC: %s , Balance: %s""" % (stock_account_move.ref, balance))
        end1 = timeit.timeit()
        _logger.info("""%s second to write %s stock move account move""" % ((end1 - start), len(self)))

        # """On post toutes les pièces comptable"""
        self.mapped('account_move_ids').action_post()
        end2 = timeit.timeit()
        _logger.info("""%s second to post %s stock move account move""" % ((end1 - start), len(self)))

    @api.multi
    def get_debit_credit_line(self):
        self.ensure_one()
        # TODO update stock cost
        # TODO Identifie pièce comptable
        stock_account_move = self.account_move_ids
        if not stock_account_move:
            raise UserError(
                """ Aucune pièce comptable trouvée pour l'opération %s avec l'id %s !!""" % (self.reference, self.id))
        stock_account_move.ensure_one()

        # TODO Identifie les écritures de stocks oncerné
        stock_account_move_line = stock_account_move.line_ids.filtered(lambda x: x.stock_move_id and not x.charge_id)
        assert len(stock_account_move_line) == 2
        assert 1 <= len(stock_account_move_line.mapped('stock_move_id')) <= 2
        assert self in stock_account_move_line.mapped('stock_move_id')

        journal_id, acc_src, acc_dest, acc_valuation = self._get_accounting_data_for_valuation()

        if self._is_out():
            credit_line = stock_account_move_line.filtered(lambda x: x.account_id.id == acc_valuation)
            credit = self.value
            debit_line = stock_account_move_line - credit_line
            if len(stock_account_move_line.mapped('stock_move_id')) == 1:
                debit = abs(self.value)
            else:
                debit = abs(self.value) + sum(self.charges_ids.mapped('cost'))
        elif self._is_in():
            debit_line = stock_account_move_line.filtered(lambda x: x.account_id.id == acc_valuation)
            credit_line = stock_account_move_line - debit_line
        elif self._is_scrapped():
            debit_line = stock_account_move_line.filtered(lambda x: x.account_id.id == acc_src)
            credit_line = stock_account_move_line - debit_line

        return debit_line, credit_line

    @api.multi
    def create_charges(self):
        """
        Permet la création de charge à patir de la structure descharges
        Annule

        :return: True
        """
        for move in self.filtered(lambda r: r.state == 'done'):
            move.charges_ids.filtered(lambda r: r.state not in ('done')).unlink()


            if move.picking_type_id.code == 'outgoing':
                location_id = move.location_id if move._is_out() else move.location_dest_id

                if not move.origin_returned_move_id:
                    sale_charges_ids = move.env['sale.charges'].get_all_specics_structures(
                        move.date, move.product_id, location_id, move.picking_id.regime_id).filtered(
                        lambda r: r.rubrique_id not in move.charges_ids.mapped('rubrique_id'))

                    if sale_charges_ids:
                        for charge in sale_charges_ids:
                            print("*"*2 + '\n' + charge.rubrique_id.name)
                            cost = self.env.user.company_id.currency_id.round(move.product_qty * charge.value)
                            charge_id = move.charges_ids.create([{
                                'stock_move_id': move.id,
                                'rubrique_id': charge.rubrique_id.id,
                                'sale_charge_id': charge.id,
                                'cost': cost,
                            }])

                    move.update_stock_move_value()
                    move.update_account_entry_move()

            return True

    @api.multi
    def action_get_charges(self):
        self.ensure_one()
        action_ref = self.env.ref('smp_inventory.smp_stock_move_charges_action')
        if not action_ref:
            return False
        action_data = action_ref.read()[0]
        action_data['domain'] = [('id', 'in', self.charges_ids.ids)]
        return action_data

    @api.model
    def _run_fifo(self, move, quantity=None):
        """ Value `move` according to the FIFO rule, meaning we consume the
        oldest receipt first. Candidates receipts are marked consumed or free
        thanks to their `remaining_qty` and `remaining_value` fields.
        By definition, `move` should be an outgoing stock move.

        :param quantity: quantity to value instead of `move.product_qty`
        :returns: valued amount in absolute
        """
        move.ensure_one()

        # Deal with possible move lines that do not impact the valuation.
        valued_move_lines = move.move_line_ids.filtered(lambda ml: ml.location_id._should_be_valued() and not ml.location_dest_id._should_be_valued() and not ml.owner_id)
        valued_quantity = 0
        for valued_move_line in valued_move_lines:
            if not valued_move_line._is_same_category()[0] and valued_move_line.inter_uom_factor:
                valued_quantity += valued_move_line.product_uom_id.with_context(inter_uom_factor=valued_move_line.inter_uom_factor)._compute_quantity(valued_move_line.qty_done, move.product_id.uom_id)
            else:
                valued_quantity += valued_move_line.product_uom_id._compute_quantity(valued_move_line.qty_done, move.product_id.uom_id)

        # Find back incoming stock moves (called candidates here) to value this move.
        qty_to_take_on_candidates = quantity or valued_quantity
        candidates = move.product_id._get_fifo_candidates_in_move_with_company(move.company_id.id)
        new_standard_price = 0
        tmp_value = 0  # to accumulate the value taken on the candidates
        for candidate in candidates:
            new_standard_price = candidate.price_unit
            if candidate.remaining_qty <= qty_to_take_on_candidates:
                qty_taken_on_candidate = candidate.remaining_qty
            else:
                qty_taken_on_candidate = qty_to_take_on_candidates

            # As applying a landed cost do not update the unit price, naivelly doing
            # something like qty_taken_on_candidate * candidate.price_unit won't make
            # the additional value brought by the landed cost go away.
            candidate_price_unit = candidate.remaining_value / candidate.remaining_qty
            value_taken_on_candidate = qty_taken_on_candidate * candidate_price_unit
            candidate_vals = {
                'remaining_qty': candidate.remaining_qty - qty_taken_on_candidate,
                'remaining_value': candidate.remaining_value - value_taken_on_candidate,
            }
            candidate.write(candidate_vals)

            qty_to_take_on_candidates -= qty_taken_on_candidate
            tmp_value += value_taken_on_candidate
            if qty_to_take_on_candidates == 0:
                break

        # Update the standard price with the price of the last used candidate, if any.
        if new_standard_price and move.product_id.cost_method == 'fifo':
            move.product_id.sudo().with_context(force_company=move.company_id.id) \
                .standard_price = new_standard_price

        # If there's still quantity to value but we're out of candidates, we fall in the
        # negative stock use case. We chose to value the out move at the price of the
        # last out and a correction entry will be made once `_fifo_vacuum` is called.
        if qty_to_take_on_candidates == 0:
            move.write({
                'value': -tmp_value if not quantity else move.value or -tmp_value,  # outgoing move are valued negatively
                'price_unit': -tmp_value / (move.product_qty or quantity),
            })
        elif qty_to_take_on_candidates > 0:
            last_fifo_price = new_standard_price or move.product_id.standard_price
            negative_stock_value = last_fifo_price * -qty_to_take_on_candidates
            tmp_value += abs(negative_stock_value)
            vals = {
                'remaining_qty': move.remaining_qty + -qty_to_take_on_candidates,
                'remaining_value': move.remaining_value + negative_stock_value,
                'value': tmp_value,
                'price_unit': last_fifo_price,
            }
            move.write(vals)
        return tmp_value

    @api.multi
    def correct_stock_move(self):
        # move_ids = self.search([('origin_returned_move_id', '=', )])
        move_ids = self.search([]).filtered(lambda x: x.origin_returned_move_id)
        move_ids = move_ids
        for move in move_ids:
            if move.origin_returned_move_id:
                move.price_unit = abs(move.price_unit)
                move.value = abs(move.value)
                for charge in move.charges_ids:
                    charge.cost_unit = abs(charge.cost_unit)
                    charge.cost = abs(charge.cost)
                move.landed_cost_value = abs(move.landed_cost_value)

    @api.model
    def get_initial_stock_state(self, start_date, product_ids, locations):



        domain = " location_id in %s AND state = 'done'"
        args = (tuple(locations.ids),)

        # case 0: Filter on company
        if self.env.user.company_id:
            domain += ' AND company_id = %s'
            args += (self.company_id.id,)

        # case 3: Filter on One product
        if product_ids:
            domain += ' AND product_id = %s'
            args += (tuple(product_ids.ids),)

        if start_date:
            domain += ' AND date_expected BETWEEN %s AND %s'
            date_from = start_date
            args += (date_from.strftime('%Y-%m-%d'), date_from.strftime('%Y-%m-%d'),)

        domain_in = domain.replace('location_id', 'location_dest_id')
        args += args

        self.env.cr.execute("""
                select 
                    product_id,
                    sum(product_qty) as product_qty,
                    sum(value) as value,
                    sum(landed_cost_value) as landed_cost_value,
                    location_id

                from (
                    SELECT 
                        product_id, 
                        SUM(-product_qty) as product_qty, 
                        SUM(-landed_cost_value) as value,
                        SUM(-landed_cost_value) as value,
                     location_id

                    FROM stock_move
                        LEFT JOIN product_product ON product_product.id = stock_move.product_id
                        LEFT JOIN stock_picking_type ON stock_picking_type.id = stock_move.picking_type_id
                    WHERE %s
                    GROUP BY product_id, location_id

                    UNION

                    SELECT 
                        product_id, 
                        SUM(product_qty) as product_qty, 
                        SUM(CASE 
                            WHEN stock_picking_type.code != 'outgoing' THEN value + landed_cost_value ELSE value
                            END ) as value, 
                        location_dest_id as location_id

                    FROM stock_move
                        LEFT JOIN product_product ON product_product.id = stock_move.product_id
                        LEFT JOIN stock_picking_type ON stock_picking_type.id = stock_move.picking_type_id

                    WHERE %s
                    GROUP BY product_id, location_dest_id
                    ) as inventory

                GROUP BY product_id, location_id
            """ % (domain, domain_in), args)
        res = self.env.cr.dictfetchall()

        return res

    @api.model
    def get_excel_report(self):
        res = defaultdict(lambda: {'qty': 0.0, 'charges':0.0})
        for sm_id in self:
            if sm_id._is_out():
                sens = 'out'

            elif sm_id._is_in():
                sens = 'in'
            elif sm_id._is_scrapped():
                sens = 'scrapped'
            else:
                sens = 'UNKNOW'

            sign = -1 if sens == 'out' else 1

            sm_dict = {
                'id': sm_id.id,
                'sens': sens,
                'date': sm_id.date_expected,
                'picking_type': sm_id.picking_type_id.name,
                'picking_type_id': sm_id.picking_type_id.code,
                'origin': sm_id.origin,
                'reference': sm_id.reference,
                'location_id': sm_id.location_dest_id.name if sens == 'in' else sm_id.location_id.name,
                'product_id': sm_id.product_id.product_tmpl_id.name,
                'qty': sign * sm_id.product_qty,
                'cost_unit': sm_id.price_unit,
                'value': sm_id.value,
                'charges': sm_id.landed_cost_value,
            }
            for k, v in sm_dict.items():
                res[sm_id.id][k] = v

        non_fichier = "Reporting des stocks.xlsx"
        # Use a temp filename to keep pandas happy.
        writer = pd.ExcelWriter(non_fichier, engine='xlsxwriter')

        # Set the filename/file handle in the xlsxwriter.workbook object.
        data_buffer = io.BytesIO()
        writer.book.filename = data_buffer

        company = self.env.user.company_id
        logo = base64.decodebytes(company.logo_web)

        df = pd.DataFrame.from_dict(res, orient="index")
        del res
        translate_dict = {
            'id': 'ID',
            'date': 'Date',
            'sens': 'Sens',
            'picking_type': "Opération",
            'picking_type_id': "Type d'opération",
            'origin': "Origin",
            'reference': "Reférence",
            'location_id': "Location",
            'product_id': "Article",
            'qty': "Quantité",
            'cost_unit': "Coût Unitaire",
            'value': "Valeur Stock",
            'charges': "Valeur Charge",
        }

        sens_column = [k for k, v in translate_dict.items()]
        df = df[sens_column]
        df.rename(columns=translate_dict, inplace=True)

        # Write the data frame to the StringIO object.
        df.to_excel(writer, index=False, sheet_name=non_fichier)
        worksheet_table_header = writer.sheets[non_fichier]
        end_row = len(df.index)
        end_column = len(df.columns) - 1
        cell_range = xls.utility.xl_range(0, 0, end_row, end_column)
        header = [{'header': di} for di in df.columns.tolist()]
        worksheet_table_header.add_table(cell_range, {'header_row': True, 'columns': header})

        workbook = writer.book
        workbook.set_properties({
            'title': 'Reporting Des Stocks',
            'author': 'Aly Kane',
            'company': 'DisruptSol',
            'comments': 'Created with Python and XlsxWriter'})
        writer.save()

        file = base64.encodebytes(data_buffer.getvalue())
        # data_buffer.close()

        # workbook.close()
        wizard_id = self.env['report.wizard'].create({'data': file, 'name': non_fichier})

        return {
            'view_mode': 'form',
            'view_id': self.env.ref('smp_inventory.report_wizard_form').id,
            'res_id': wizard_id.id,
            'res_model': 'report.wizard',
            'view_type': 'form',
            'type': 'ir.actions.act_window',
            # 'context': self._context,
            'target': 'new',
        }

    @api.multi
    def get_returned_move(self):
        # Deux types de mouvement retournés:
        # 1. les entrants qui sont des retours des sortants
        # 2. les sortants qui sont des retours des entrants

        # Mouvement qui sont des retours
        return_move_ids = self.filtered(lambda x: x.origin_returned_move_id)

        # Mouvement qui ont été retourné des retour
        returned_move_ids = self.mapped('move_dest_ids').mapped('origin_returned_move_id').filtered(
            lambda r: r in self)

        return {'returned_move_ids':returned_move_ids, 'return_move_ids': return_move_ids}

    def action_show_details(self):
        """ Returns an action that will open a form view (in a popup) allowing to work on all the
        move lines of a particular move. This form view is used when "show operations" is not
        checked on the picking type.
        """
        self.ensure_one()

        # If "show suggestions" is not checked on the picking type, we have to filter out the
        # reserved move lines. We do this by displaying `move_line_nosuggest_ids`. We use
        # different views to display one field or another so that the webclient doesn't have to
        # fetch both.
        if self.picking_id.picking_type_id.show_reserved:
            view = self.env.ref('stock.view_stock_move_operations')
        else:
            view = self.env.ref('stock.view_stock_move_nosuggest_operations')

        view = self.env.ref('smp_inventory.view_move_form')

        picking_type_id = self.picking_type_id or self.picking_id.picking_type_id
        return {
            'name': _('Detailed Operations'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'stock.move',
            'views': [(view.id, 'form')],
            'view_id': view.id,
            'target': 'new',
            'res_id': self.id,
            'context': dict(
                self.env.context,
                show_lots_m2o=self.has_tracking != 'none' and (
                            picking_type_id.use_existing_lots or self.state == 'done' or self.origin_returned_move_id.id),
                # able to create lots, whatever the value of ` use_create_lots`.
                show_lots_text=self.has_tracking != 'none' and picking_type_id.use_create_lots and not picking_type_id.use_existing_lots and self.state != 'done' and not self.origin_returned_move_id.id,
                show_source_location=self.location_id.child_ids and self.picking_type_id.code != 'incoming',
                show_destination_location=self.location_dest_id.child_ids and self.picking_type_id.code != 'outgoing',
                show_package=not self.location_id.usage == 'supplier',
                show_reserved_quantity=self.state != 'done'
            ),
        }

    @api.multi
    def _update_reserved_quantity(self, need, available_quantity, location_id, lot_id=None, package_id=None,
                                  owner_id=None, strict=True):
        """ Create or update move lines.
        """
        self.ensure_one()

        if not lot_id:
            lot_id = self.env['stock.production.lot']
        if not package_id:
            package_id = self.env['stock.quant.package']
        if not owner_id:
            owner_id = self.env['res.partner']

        taken_quantity = min(available_quantity, need)

        # `taken_quantity` is in the quants unit of measure. There's a possibility that the move's
        # unit of measure won't be respected if we blindly reserve this quantity, a common usecase
        # is if the move's unit of measure's rounding does not allow fractional reservation. We chose
        # to convert `taken_quantity` to the move's unit of measure with a down rounding method and
        # then get it back in the quants unit of measure with an half-up rounding_method. This
        # way, we'll never reserve more than allowed. We do not apply this logic if
        # `available_quantity` is brought by a chained move line. In this case, `_prepare_move_line_vals`
        # will take care of changing the UOM to the UOM of the product.
        if not strict:
            taken_quantity_move_uom = self.product_id.uom_id._compute_quantity(taken_quantity, self.product_uom,
                                                                               rounding_method='DOWN')
            taken_quantity = self.product_uom._compute_quantity(taken_quantity_move_uom, self.product_id.uom_id,
                                                                rounding_method='HALF-UP')

        quants = []

        if self.product_id.tracking == 'serial':
            rounding = self.env['decimal.precision'].precision_get('Product Unit of Measure')
            if float_compare(taken_quantity, int(taken_quantity), precision_digits=rounding) != 0:
                taken_quantity = 0

        try:
            if not float_is_zero(taken_quantity, precision_rounding=self.product_id.uom_id.rounding):
                quants = self.env['stock.quant']._update_reserved_quantity(
                    self.product_id, location_id, taken_quantity, lot_id=lot_id,
                    package_id=package_id, owner_id=owner_id, strict=strict
                )
        except UserError:
            taken_quantity = 0

        # Find a candidate move line to update or create a new one.
        for reserved_quant, quantity in quants:
            to_update = self.move_line_ids.filtered(lambda m: m.product_id.tracking != 'serial' and
                                                              m.location_id.id == reserved_quant.location_id.id and
                                                              m.lot_id.id == reserved_quant.lot_id.id and
                                                              m.package_id.id == reserved_quant.package_id.id and
                                                              m.owner_id.id == reserved_quant.owner_id.id)
            if to_update:
                ref_category_id = self.product_id.uom_id.category_id.id
                to_update[0].with_context(bypass_reservation_update=True).product_uom_qty += self.product_id.uom_id.with_context(ref_category_id=ref_category_id)._compute_quantity(quantity, to_update[0].product_uom_id, rounding_method='HALF-UP')
            else:
                if self.product_id.tracking == 'serial':
                    for i in range(0, int(quantity)):
                        self.env['stock.move.line'].create(self._prepare_move_line_vals(quantity=1, reserved_quant=reserved_quant))
                else:
                    self.env['stock.move.line'].create(
                        self._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant))
        return taken_quantity

    @api.multi
    def stock_move_create_returns(self):
        # TODO sle: the unreserve of the next moves could be less brutal
        self.ensure_one()

        return_move_id = self.copy()
        return_move_id.write({
            'state': 'draft',
            'date_expected': fields.Datetime.now(),
            'location_id': self.location_dest_id.id,
            'location_dest_id': self.location_id.id,
            'origin_returned_move_id': self.id,
            })

        # COPY CHARGE:

        return return_move_id


        # for return_move in self:
        #     return_move.move_dest_ids.filtered(lambda m: m.state not in ('done', 'cancel'))._do_unreserve()
        #
        # # create new picking for returned products
        # picking_type_id = self.picking_id.picking_type_id.return_picking_type_id.id or self.picking_id.picking_type_id.id
        # new_picking = self.picking_id.copy({
        #     'move_lines': [],
        #     'picking_type_id': picking_type_id,
        #     'state': 'draft',
        #     'origin': _("Return of %s") % self.picking_id.name,
        #     'location_id': self.picking_id.location_dest_id.id,
        #     'location_dest_id': self.location_id.id})
        # new_picking.message_post_with_view('mail.message_origin_link',
        #     values={'self': new_picking, 'origin': self.picking_id},
        #     subtype_id=self.env.ref('mail.mt_note').id)
        # returned_lines = 0
        # for return_line in self.product_return_moves:
        #     if not return_line.move_id:
        #         raise UserError(_("You have manually created product lines, please delete them to proceed."))
        #     # TODO sle: float_is_zero?
        #     if return_line.quantity:
        #         returned_lines += 1
        #         vals = self._prepare_move_default_values(return_line, new_picking)
        #         r = return_line.move_id.copy(vals)
        #         vals = {}
        #
        #         # +--------------------------------------------------------------------------------------------------------+
        #         # |       picking_pick     <--Move Orig--    picking_pack     --Move Dest-->   picking_ship
        #         # |              | returned_move_ids              ↑                                  | returned_move_ids
        #         # |              ↓                                | return_line.move_id              ↓
        #         # |       return pick(Add as dest)          return toLink                    return ship(Add as orig)
        #         # +--------------------------------------------------------------------------------------------------------+
        #         move_orig_to_link = return_line.move_id.move_dest_ids.mapped('returned_move_ids')
        #         move_dest_to_link = return_line.move_id.move_orig_ids.mapped('returned_move_ids')
        #         vals['move_orig_ids'] = [(4, m.id) for m in move_orig_to_link | return_line.move_id]
        #         vals['move_dest_ids'] = [(4, m.id) for m in move_dest_to_link]
        #         r.write(vals)
        # if not returned_lines:
        #     raise UserError(_("Please specify at least one non-zero quantity."))
        #
        # new_picking.action_confirm()
        # new_picking.action_assign()
        # return new_picking.id, picking_type_id

    # def _prepare_move_default_values(self, return_line, new_picking):
    #     vals = {
    #         'product_id': return_line.product_id.id,
    #         'product_uom_qty': return_line.quantity,
    #         'product_uom': return_line.product_id.uom_id.id,
    #         'picking_id': new_picking.id,
    #         'state': 'draft',
    #         'date_expected': fields.Datetime.now(),
    #         'location_id': return_line.move_id.location_dest_id.id,
    #         'location_dest_id': self.location_id.id or return_line.move_id.location_id.id,
    #         'picking_type_id': new_picking.picking_type_id.id,
    #         'warehouse_id': self.picking_id.picking_type_id.warehouse_id.id,
    #         'origin_returned_move_id': return_line.move_id.id,
    #         'procure_method': 'make_to_stock',
    #     }
    #     return vals






