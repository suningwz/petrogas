# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from odoo.tools.float_utils import float_compare

# from odoo.exceptions import UserError

# from odoo.addons.purchase.models.purchase import PurchaseOrder as Purchase

from datetime import timedelta, date


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    READONLY_STATES = {
        'purchase': [('readonly', True)],
        'done': [('readonly', True)],
        'cancel': [('readonly', True)],
    }

    credoc_id = fields.Many2one('credoc.credoc', 'Crédit Documentaire', states=READONLY_STATES)
    location_dest_id = fields.Many2one('stock.location', 'Location',
                                       domain=[('usage', '=', 'internal')], states=READONLY_STATES)


    @api.onchange('partner_id', 'company_id')
    def onchange_partner_id(self):
        res = super(PurchaseOrder, self).onchange_partner_id()
        hide_credoc = True
        credoc_ids =[]
        self.credoc_id = None
        if self.partner_id:
            credoc_ids = self.env['credoc.credoc'].get_partner_credoc(self.partner_id)
            if credoc_ids:
                hide_credoc = True
        self = self.with_context(hide_credoc=hide_credoc)
        return {'domain': {'credoc_id': [('id', 'in', credoc_ids), ('state', '=', 'open')]}, 'context': self._context}

    @api.onchange('credoc_id')
    def onchange_credoc_id(self):
        self.currency_id = self.credoc_id and self.credoc_id.currency_id.id or self.env.user.company_id.currency_id
        self.payment_term_id = self.credoc_id and self.credoc_id.payment_term.id or None
        if self.order_line:
            for r in self.order_line:
                r.credoc_id =  None
                if self.credoc_id:
                    r.credoc_id = self.credoc_id

    @api.multi
    def _get_destination_location(self):
        self.ensure_one()
        res = super(PurchaseOrder,self)._get_destination_location()
        if self.location_dest_id:
            return self.location_dest_id.id

    @api.model
    def _prepare_picking(self):
        res = super(PurchaseOrder,self)._prepare_picking()
        if self.credoc_id:
            res['credoc_id'] = self.credoc_id.id
        return res

    @api.multi
    def _create_picking(self):
        StockPicking = self.env['stock.picking']
        for order in self:
            if any([ptype in ['product', 'consu'] for ptype in order.order_line.mapped('product_id.type')]):
                pickings = order.picking_ids.filtered(lambda x: x.state not in ('done', 'cancel'))
                if not pickings:
                    res = order._prepare_picking()
                    picking = StockPicking.create(res)
                else:
                    picking = pickings[0]
                moves = order.order_line._create_stock_moves(picking)
                moves = moves.filtered(lambda x: x.state not in ('done', 'cancel'))._action_confirm()
                seq = 0
                for move in sorted(moves, key=lambda move: move.date_expected):
                    seq += 5
                    move.sequence = seq
                moves._action_assign()
                picking.message_post_with_view('mail.message_origin_link',
                    values={'self': picking, 'origin': order},
                    subtype_id=self.env.ref('mail.mt_note').id)
        return True

    @api.multi
    def action_view_invoice(self):
        '''
        This function returns an action that display existing vendor bills of given purchase order ids.
        When only one found, show the vendor bill immediately.
        '''
        action = self.env.ref('account.action_vendor_bill_template')
        result = action.read()[0]
        create_bill = self.env.context.get('create_bill', False)
        # override the context to get rid of the default filtering
        result['context'] = {
            'type': 'in_invoice',
            'default_purchase_id': self.id,
            'default_currency_id': self.currency_id.id,
            'default_company_id': self.company_id.id,
            'company_id': self.company_id.id,
            'default_credoc_id': self.credoc_id.id,
        }
        # choose the view_mode accordingly
        if len(self.invoice_ids) > 1 and not create_bill:
            result['domain'] = "[('id', 'in', " + str(self.invoice_ids.ids) + ")]"
        else:
            res = self.env.ref('account.invoice_supplier_form', False)
            result['views'] = [(res and res.id or False, 'form')]
            # Do not set an invoice_id if we want to create a new bill.
            if not create_bill:
                result['res_id'] = self.invoice_ids.id or False
        result['context']['default_origin'] = self.name
        result['context']['default_reference'] = self.partner_ref
        return result


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    credoc_id = fields.Many2one('credoc.credoc', 'Crédit Documentaire', related='order_id.credoc_id')

    # @api.model
    # def create(self, values):
    #     line = super(PurchaseOrderLine, self).create(values)
    #     if line.order_id.credoc_id:
    #         line.credoc_id = line.order_id.credoc_id
    #     return line

