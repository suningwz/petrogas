# -*- coding: utf-8 -*-

from odoo import api, fields, models, registry, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    regime_id = fields.Many2one(related="sale_id.regime_id", string="Regime Douanier", store=True, readonly=False)
    invoice_ids = fields.Many2many(
        comodel_name='account.invoice',
        copy=False,
        string='Invoices',
        readonly=False
    )

    @api.multi
    def action_view_invoice(self):
        """This function returns an action that display existing invoices
        of given stock pickings.
        It can either be a in a list or in a form view, if there is only
        one invoice to show.
        """
        self.ensure_one()
        action = self.env.ref('account.action_invoice_tree1')
        result = action.read()[0]
        if len(self.invoice_ids) > 1:
            result['domain'] = "[('id', 'in', %s)]" % self.invoice_ids.ids
        else:
            form_view = self.env.ref('account.invoice_form')
            result['views'] = [(form_view.id, 'form')]
            result['res_id'] = self.invoice_ids.id
        return result

    @api.multi
    def do_print_picking(self):
        for record in self:
            report_id = self.env.ref('smp_data.smp_picking_report')
            print_limit = report_id.print_limit
            no_limit_print_id = report_id.no_limit_print_id
            if no_limit_print_id:
                no_limit_print_group_id = list(no_limit_print_id.get_xml_id().values())[0]
            else:
                no_limit_print_group_id = False

            reprinting_access = False

            """ Contrôle paiement comptant"""
            if record.sale_id and record.sale_id.payment_term_id and \
                    record.sale_id.payment_term_id.line_ids[0].days == 0:
                if not self.user_has_groups('smp_sale.bc_validation_control'):
                    if not record.sale_id.invoice_ids:
                        raise UserError(_("""For an immediate payment, the invoice must be paid before to grant access to the delivery order printing. """))
                    states = all([i.state == 'done' for i in record.sale_id.invoice_ids])
                    invoice_amount = sum([i.amount_total for i in record.sale_id.invoice_ids if i.state =='paid'])
                    ordered_amount = record.sale_id.amount_total
                    if not invoice_amount == ordered_amount:
                        invoice_name = ', '.join(record.invoice_ids.mapped('number'))
                        raise UserError("""Pour un paiement au comtpant veuillez régler la ou les factures %s concernée(s) par ce BL correspond au montant du bon de commande. """ % invoice_name)
                    # TODO: Verifier quantité livré et quantité commandé
                # else:
                    # message = """Attention: Vous venez d'outepassez une procédure de vente consistant à bloquer l'inpression d'un BL au cas le client est soumis à un réglement immédiat"""
                    # mess = {
                    #     'title': "Contrôle sur les ventes aux comptant ",
                    #     'message': message
                    # }
                    # return {'warning': mess}

            """ Contrôle limitation d'impression"""
            if self.printed and print_limit:
                if no_limit_print_group_id and self.user_has_groups(no_limit_print_group_id):
                    pass
                else:
                    raise UserError(_("""Attempted re-printing: Only a user with specific access rights
                     can reprint the document."""))

        self.write({'printed': True})
        return report_id.report_action(self)

    @api.multi
    def split_process(self):
        """Use to trigger the wizard from button with correct context """
        """Adds picking split without done state."""
        for picking in self:

            # Check the picking state and condition before split
            if picking.state == 'draft':
                raise UserError(_('Mark as todo this picking please.'))
            if all([x.qty_done == 0.0 for x in picking.move_line_ids]):
                raise UserError(
                    _('You must enter the final quantity delivered in order to split your '
                      'picking in several ones.'))

            # Split moves considering the qty_done on moves
            new_moves = self.env['stock.move']
            for move in picking.move_lines:
                rounding = move.product_uom.rounding
                qty_done = move.quantity_done
                qty_initial = move.product_uom_qty
                qty_diff_compare = float_compare(
                    qty_done, qty_initial, precision_rounding=rounding
                )
                if qty_diff_compare < 0:
                    qty_split = qty_initial - qty_done
                    qty_uom_split = move.product_uom._compute_quantity(
                        qty_split,
                        move.product_id.uom_id,
                        rounding_method='HALF-UP'
                    )
                    new_move_id = move._split(qty_uom_split)
                    for move_line in move.move_line_ids:
                        if move_line.product_qty and move_line.qty_done:
                            # To avoid an error
                            # when picking is partially available
                            try:
                                move_line.write(
                                    {'product_uom_qty': move_line.qty_done})
                            except UserError:
                                pass
                    new_moves |= self.env['stock.move'].browse(new_move_id)

            # If we have new moves to move, create the backorder picking
            if new_moves:
                backorder_picking = picking.copy({
                    'name': '/',
                    'move_lines': [],
                    'move_line_ids': [],
                    'backorder_id': picking.id,
                })
                picking.message_post(
                    body=_(
                        'The backorder <a href="#" '
                        'data-oe-model="stock.picking" '
                        'data-oe-id="%d">%s</a> has been created.'
                    ) % (
                        backorder_picking.id,
                        backorder_picking.name
                    )
                )
                new_moves.write({
                    'picking_id': backorder_picking.id,
                })
                new_moves.mapped('move_line_ids').write({
                    'picking_id': backorder_picking.id,
                })
                new_moves._action_assign()

    def to_be_confirmed_manually(self):
        for move in self.move_lines:
            if move.sale_line_id.qty_to_confirm:
                return True
        return False


class StockReturnPicking(models.TransientModel):
    _inherit = "stock.return.picking"

    @api.multi
    def _create_returns(self):
        new_picking_id, pick_type_id = super(StockReturnPicking, self)._create_returns()
        new_picking = self.env['stock.picking'].browse([new_picking_id])
        new_picking.name = new_picking.name + '-' + self.picking_id.name + '-Retour'
        for move in new_picking.move_lines:
            move.reference = new_picking.name
        return new_picking_id, pick_type_id


