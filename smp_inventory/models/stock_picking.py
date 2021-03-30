# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.multi
    def _get_default_picking_id(self):
        if self.context.get('active_model') == 'stock.picking':
            active_id = self.context.get('active_id', False)
            return self.context.get('active_id', False)

    @api.multi
    def confirm_product_qty(self):
        self.ensure_one()
        # transfert_wizard_id =  self.env.context.get('transfert_wizard_id', False)
        SPP = self.env['stock.partial.picking']
        action = SPP.get_formview_action()
        # action['context'] = {'default_picking_id': self.id, 'default_transfert_wizard_id': transfert_wizard_id}
        action['context'] = {'default_picking_id': self.id}
        action['target'] = 'new'
        return action

    @api.multi
    def action_get_account_moves(self):
        action_ref = self.env.ref('account.action_move_journal_line')
        # action_ref = self.env.ref('account.view_move_line_tree')
        if not action_ref:
            return False
        action_data = action_ref.read()[0]
        action_data['domain'] = [('id', 'in', self.mapped('move_lines').mapped('account_move_ids').ids)]
        return action_data

    @api.multi
    def button_validate_new(self):
        """ We display the wizard to check and display quantity to receipt if operating unit category  is different from storage unit category ** Wizard 1 *** """
    # def process(self):
        # TODO: """""""" Confirmation product_qty""""
        if self.mapped('move_lines').filtered(lambda x: x.product_id.uom_id.category_id != x.product_uom.category_id):
            return self.confirm_product_qty()
        return self.button_validate()

    @api.multi
    def button_validate(self):
        self.ensure_one()
        if not self.move_lines and not self.move_line_ids:
            raise UserError(_('Please add some items to move.'))

        # If no lots when needed, raise error
        picking_type = self.picking_type_id
        precision_digits = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        no_quantities_done = all(float_is_zero(move_line.qty_done, precision_digits=precision_digits) for move_line in self.move_line_ids.filtered(lambda m: m.state not in ('done', 'cancel')))
        no_reserved_quantities = all(float_is_zero(move_line.product_qty, precision_rounding=move_line.product_uom_id.rounding) for move_line in self.move_line_ids)
        if no_reserved_quantities and no_quantities_done:
            raise UserError(_('You cannot validate a transfer if no quantites are reserved nor done. To force the transfer, switch in edit more and encode the done quantities.'))

        if picking_type.use_create_lots or picking_type.use_existing_lots:
            lines_to_check = self.move_line_ids
            if not no_quantities_done:
                lines_to_check = lines_to_check.filtered(
                    lambda line: float_compare(line.qty_done, 0,
                                               precision_rounding=line.product_uom_id.rounding)
                )

            for line in lines_to_check:
                product = line.product_id
                if product and product.tracking != 'none':
                    if not line.lot_name and not line.lot_id:
                        raise UserError(_('You need to supply a Lot/Serial number for product %s.') % product.display_name)

        if no_quantities_done:
            view = self.env.ref('stock.view_immediate_transfer')
            wiz = self.env['stock.immediate.transfer'].create({'pick_ids': [(4, self.id)]})
            return {
                'name': _('Immediate Transfer?'),
                'type': 'ir.actions.act_window',
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'stock.immediate.transfer',
                'views': [(view.id, 'form')],
                'view_id': view.id,
                'target': 'new',
                'res_id': wiz.id,
                'context': self.env.context,
            }

        # for move in self.move_lines:
        #     ckjcds = float_compare(move.quantity_done, move.product_uom_qty,precision_rounding=move.product_uom.rounding)
        get_overprocessed_stock_moves = self.move_lines.filtered(lambda move: move.product_uom_qty != 0 and float_compare(move.quantity_done, move.product_uom_qty,precision_rounding=move.product_uom.rounding) == 1)
        skip_overprocessed_check = self._context.get('skip_overprocessed_check')
        if get_overprocessed_stock_moves and not skip_overprocessed_check:
        # if self._get_overprocessed_stock_moves() and not self._context.get('skip_overprocessed_check'):
            view = self.env.ref('stock.view_overprocessed_transfer')
            wiz = self.env['stock.overprocessed.transfer'].create({'picking_id': self.id})
            return {
                'type': 'ir.actions.act_window',
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'stock.overprocessed.transfer',
                'views': [(view.id, 'form')],
                'view_id': view.id,
                'target': 'new',
                'res_id': wiz.id,
                'context': self.env.context,
            }

        # Check backorder should check for other barcodes
        if self._check_backorder():
            action =  self.action_generate_backorder_wizard()
            return action
        self.action_done()
        return

    @api.multi
    def assign_stock_picking_action_server(self):
        for pick in self:
            if pick.state in ['assigned']:
                for move in pick.move_lines.filtered(lambda m: m.state not in ['done', 'cancel']):
                    for move_line in move.move_line_ids:
                        move_line.qty_done = move_line.product_uom_qty
                pick.action_done()

    def confirm_stock_picking_action_server(self):
        for pick in self:
            if pick.state in ['confirm']:
                # for move in pick.move_lines.filtered(lambda m: m.state not in ['done', 'cancel']):
                pick.action_assign()

    @api.multi
    def update_sale_charge_with_regime(self):
        """
        Mais a jours les charges de vente.
        :return: None
        """
        for pick in self.filtered(lambda r: r.picking_type_id.code == 'outgoing' and r.regime_id and r.state == 'done'):
            pick.move_ids_without_package.filtered(lambda r: r.product_id.apply_price_structure).create_charges()



class StockPartialPicking(models.TransientModel):
    _name = "stock.partial.picking"
    _rec_name = 'picking_id'
    _description = "Partial Picking Processing Wizard"

    line_ids = fields.One2many('stock.partial.picking.line', 'wizard_id', 'Product Moves')
    picking_id = fields.Many2one('stock.picking', 'Picking', required=True, ondelete='CASCADE', domain=[('picking_type_id.code','=','incoming')])
    # transfert_wizard_id = fields.Many2one('stock.immediate.transfert', 'Transfert Wizard' ,ondelete='CASCADE', required=True)

    @api.multi
    @api.onchange('picking_id')
    def onchanche_picking(self):
        self.ensure_one()
        line_ids = []
        for move in self.picking_id.move_lines.filtered(lambda x: x.state not in ('done', 'cancel') and x.product_id.uom_id.category_id.id != x.product_uom.category_id.id):
            line = {'stock_move_id': move.id,
                    'product_id': move.product_id.id,
                    'product_uom_qty': move.product_uom_qty if move.quantity_done == 0 else move.quantity_done,
                    'product_uom_id': move.product_uom.id,
                    'product_qty': move.product_qty if move.quantity_done == 0 else move.quantity_done * move.inter_uom_factor,
                    'uom_id': move.product_id.uom_id.id,
                    'inter_uom_factor': move.inter_uom_factor,
                    }
            line_ids.append(self.env['stock.partial.picking.line'].create(line))
        self.line_ids = [(4, x.id) for x in line_ids]

    @api.multi
    def process(self):
        self.ensure_one()
        """ On assigne la valeur saisi dans chaque au stock_move.product_qty"""
        for line in self.line_ids:
            line.check_control()
            # line.stock_move_id.manual_product_qty = True
            value = line.stock_move_id.price_unit * line.stock_move_id.product_qty
            line.stock_move_id.inter_uom_factor = line.product_qty / line.product_uom_qty
            new_price_unit = value / line.product_qty
            line.stock_move_id.price_unit = value / line.product_qty

        return self.picking_id.button_validate()


class StockPartialPickingLine(models.TransientModel):

    _name = "stock.partial.picking.line"
    _rec_name = 'product_id'

    stock_move_id = fields.Many2one('stock.move', "Move", ondelete='CASCADE')
    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    product_uom_qty = fields.Float("Quantity Operated", readonly=True)
    product_uom_id = fields.Many2one('uom.uom', "Operating Uom", readonly=True)
    product_qty = fields.Float("Stock quantity")
    uom_id = fields.Many2one('uom.uom', "Storage unit", readonly=True)
    inter_uom_factor = fields.Float("Conversion Factor", digits=(10, 4))
    # product_id = fields.Many2one('product.product', 'Article', related='stock_move_id.product_id', readonly=True)
    # inter_uom_factor = fields.Float('Convesion factor')
    # product_uom_qty = fields.Float("Quantité d'entrée", related='stock_move_id.product_uom_qty' , readonly=True)
    # product_uom_id = fields.Many2one('uom.uom', "Unité d'entrée", related='stock_move_id.product_uom', readonly=True)
    # product_qty = fields.Float("Quantité de stockage", related='stock_move_id.product_qty')
    # uom_id = fields.Many2one('uom.uom', "Unité de stockage", related='stock_move_id.product_id.uom_id', readonly=True)
    wizard_id = fields.Many2one('stock.partial.picking', string="Wizard", ondelete='CASCADE')

    @api.onchange('product_qty')
    def onchange_product_qty(self):
        if self.product_qty:
            self.inter_uom_factor = self.product_qty / self.product_uom_qty

    @api.onchange('inter_uom_factor')
    def onchange_inter_uom_factor(self):
        if self.inter_uom_factor:
            self.product_qty = self.inter_uom_factor * self.product_uom_qty

    @api.multi
    def check_control(self):
        print('stock_partial_picking_line')
