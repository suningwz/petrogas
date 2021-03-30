# -*- coding: utf-8 -*-

from odoo import api, fields, models, _, exceptions, tools
from odoo.exceptions import UserError, ValidationError
import time
from datetime import datetime, timedelta, date
from odoo.addons import decimal_precision as dp
from odoo.tools.float_utils import float_compare, float_is_zero


validity_date = 30

class InternalPicking (models.Model):

    _name = "internal.picking"
    _description = "Inter Location transfert"

    name = fields.Char('Séquence', default="/", copy=False)
    partner_id = ('res.partner', 'Partenaire')
    location_src_id = fields.Many2one('stock.location', 'Location Source', domain=[('usage', '=', 'internal')],
                                      required=True, states={'draft': [('readonly', False)]})
    location_dest_id = fields.Many2one('stock.location', 'Location Destination', domain=[('usage', '=', 'internal')],
                                       required=True, states={'draft': [('readonly', False)]})
    date_end_validity = fields.Date(compute='_end_validity', string='Date fin de validité', store=True)
    date_sent = fields.Date("date of issue", states={'draft': [('readonly', False), ('required', True)]})
    date_load = fields.Date('date of loading', states={'sent': [('readonly', False),('required', True)]})
    date_done = fields.Date('date of receipt', states={'open': [('readonly', False),('required', True)]})
    creater_id = fields.Many2one('res.users', 'Created by', readonly=True)
    loader_id = fields.Many2one('res.users', 'loaded by', readonly=True)
    finisher_id = fields.Many2one('res.users', 'Received by', readonly=True)
    company_id = fields.Many2one('res.company', 'Compagny', default=lambda self: self.env.user.company_id.id,
                                 readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('sent', 'Sent'), ('open', 'Loaded'), ('done', 'Received')],
                             'Status', default='draft', required=True)
    internal_picking_line_ids = fields.One2many('internal.picking.line','internal_picking_id',
                                                string= "Lignes de Transferts")

    @api.multi
    def action_cancel(self):
        for r in self.internal_picking_line_ids:
            r.action_cancel()

    @api.multi
    def copy_data(self, default=None):
        if default is None:
            default = {}
        if 'order_line' not in default:
            default['internal_picking_line_ids'] = [(0, 0, line.copy_data()[0]) for line in self.internal_picking_line_ids]
        return super(InternalPicking, self).copy_data(default)

    @api.multi
    def check_internal_picking(self, operation):
        if not self.internal_picking_line_ids:
            raise UserError("""Veuillez saisir des lignes à transferer.""")
        self.internal_picking_line_ids.check_line(operation)

    @api.multi
    def sent(self):
        self.ensure_one()
        self.check_internal_picking('sent')
        if self.name == '/':
            self.name = self.env['ir.sequence'].next_by_code('internal.picking')
        self.state = 'sent'
        for line in self.internal_picking_line_ids:
            line.quantity_load = line.quantity_ask

    @api.multi
    def load(self):
        self.ensure_one()
        self.check_internal_picking('load')
        picking_ids = self._create_picking('out')
        for picking in picking_ids.filtered(lambda x: x.state not in ('done', 'cancel')):
            for move in picking.move_lines.filtered(lambda m: m.state not in ['done', 'cancel']):
                for move_line in move.move_line_ids:
                    move_line.qty_done = move_line.product_uom_qty
            picking.action_done()
        self.state = 'open'
        for line in self.internal_picking_line_ids:
            line.quantity_done = line.quantity_load

    @api.multi
    def done(self):
        self.ensure_one()
        self.check_internal_picking('done')
        # TODO Create Picking
        picking_ids = self._create_picking('in')
        for picking in picking_ids.filtered(lambda x: x.state not in ('done', 'cancel')):
            print('BL: '+ picking.name)
            for move in picking.move_lines.filtered(lambda m: m.state not in ['done', 'cancel']):
                for move_line in move.move_line_ids:
                    move_line.qty_done = move_line.product_uom_qty
        picking_ids.action_done()
        self.state = 'done'

    @api.multi
    def print(self):
        print("Impression")

    @api.multi
    def _prepare_picking_out(self):
        self.ensure_one()
        picking_type_id = self.env.ref('smp_inventory.picking_transfert_out')
        # picking_type_id = self.env['stock.picking.type'].search([('id','=',picking_type_id)])
        picking_type_id.ensure_one()
        location_dest_id = picking_type_id.default_location_dest_id.id
        res = {
            'picking_type_id': picking_type_id.id,
            'partner_id': None,
            'name': self.name + '/OUT',
            # 'partner_id': self.partner_id.id if self.partner_id else None,
            'date': self.date_load,
            'origin': self.name,
            'location_dest_id': picking_type_id.default_location_dest_id.id,
            'location_id': self.location_src_id.id,
            'company_id': self.company_id.id,
            }
        return res

    @api.multi
    def _prepare_picking_in(self):
        self.ensure_one()
        picking_type_id = self.env.ref('stock.picking_type_internal')
        return {
            'picking_type_id': picking_type_id.id,
            # 'partner_id': self.partner_id.id if self.partner_id else None,
            'name': self.name + '/IN',
            'date': self.date_done,
            'origin': self.name,
            'location_dest_id': self.location_dest_id.id,
            'location_id': picking_type_id.default_location_src_id.id,
            'company_id': self.company_id.id,
        }

    @api.multi
    def _prepare_picking_lost(self):
        self.ensure_one()
        picking_type_id = self.env.ref('smp_inventory.picking_transfert_lost')
        return {
            'picking_type_id': picking_type_id.id,
            # 'partner_id': self.partner_id.id if self.partner_id else None,
            'name': self.name + '/LOSS',
            'date': self.date_done,
            'origin': self.name,
            'location_dest_id':  picking_type_id.default_location_dest_id.id,
            'location_id': picking_type_id.default_location_src_id.id,
            'company_id': self.company_id.id,
        }

    @api.multi
    def _create_picking(self, sens, picking_ids =None):
        self.ensure_one()
        StockPicking = self.env['stock.picking']
        if sens == 'out':
            res = self._prepare_picking_out()
        if sens == 'in':
            res = self._prepare_picking_in()
        if sens == 'loss':
            res = self._prepare_picking_lost()

        picking = StockPicking.create(res)
        # picking_ids.append(picking)
        if picking_ids:
            picking_ids = picking_ids | picking
        else:
            picking_ids = picking

        if sens == 'loss':
            internal_line_loss = self.internal_picking_line_ids.filtered(lambda x: x if not float_is_zero(x.quantity_load - x.quantity_done, x.product_uom.rounding) else False )
            moves = internal_line_loss._create_stock_moves(picking)
        else:
            moves = self.internal_picking_line_ids._create_stock_moves(picking)
        moves = moves.filtered(lambda x: x.state not in ('done', 'cancel'))._action_confirm()
        seq = 0
        for move in sorted(moves, key=lambda move: move.date_expected):
            seq += 5
            move.sequence = seq
        moves._action_assign()

        if sens == 'in':
            move_loss = self.internal_picking_line_ids.filtered(lambda x: x if not float_is_zero(x.quantity_load - x.quantity_done, x.product_uom.rounding) else False )
            if move_loss:
                picking_ids = picking_ids | (self._create_picking('loss',picking_ids))
        # picking.message_post_with_view('mail.message_origin_link',
        #     values={'self': picking, 'origin': order},
        #     subtype_id=self.env.ref('mail.mt_note').id)
        return picking_ids

    @api.multi
    def get_move_direction(self,picking):
        if picking.location_id._should_be_valued() and picking.location_dest_id._should_be_valued():
            raise UserError("""A stock move can only concern two locations which are not of internal type """)
        if picking.location_id._should_be_valued() and not picking.location_dest_id._should_be_valued():
            return 'out'
        if not picking.location_id._should_be_valued() and picking.location_dest_id._should_be_valued():
            return 'in'
        if not picking.location_id._should_be_valued() and not picking.location_dest_id._should_be_valued():
            return 'loss'


class InternalPickingLine(models.Model):
    _name = "internal.picking.line"
    _description = "Inter Location transfert Line"

    @api.depends('stock_move_ids', 'stock_move_ids.value', 'stock_move_ids.landed_cost_value')
    def _update_transfert_value(self):
        for r in self:
            sm_out = r.stock_move_ids.filtered(lambda x: x._is_out())
            if sm_out:
                r.charge_out_amount =sm_out.landed_cost_value / sm_out.product_qty
                r.cmp_out_amount =sm_out.value / sm_out.product_qty
                sm_in = r.stock_move_ids.filtered(lambda x: x._is_in())
                if sm_in:
                    r.charge_in_amount =sm_in.landed_cost_value / sm_in.product_qty
                    r.cmp_in_amount =sm_in.value / sm_in.product_qty

    # state = fields.Selection([('draft', 'Draft'), ('sent', 'Emit'), ('open', 'Chargé'), ('done', 'Réceptionné')],
    #                          string='Status', required=True, readonly=True, default='draft')
    state = fields.Selection(related="internal_picking_id.state", string="Statut", readonly=True, default='draft')
    # regime_id = fields.Many2one(related="sale_id.regime_id", string="Regime Douanier", store=True, readonly=False)

    product_id = fields.Many2one('product.product', 'Product', domain=[('type', 'in', ['product', 'consu'])],
                                 index=True, required=True, states={'draft': [('readonly', False)]})
    product_uom = fields.Many2one('uom.uom', 'Unit of Measure', required=True, states={'draft': [('readonly', False)]})
    quantity_ask = fields.Float('Initial Quantity', digits=dp.get_precision('Product Unit of Measure'), states={'draft': [('readonly', False)]})
    quantity_load = fields.Float('Loaded Quantity', digits=dp.get_precision('Product Unit of Measure'), states={'sent': [('readonly', False)]}, copy=False)
    quantity_done = fields.Float('Received Quantity', digits=dp.get_precision('Product Unit of Measure'), states={'open': [('readonly', False)]}, copy=False)

    cmp_out_amount = fields.Float('Exit cost unit', compute='_update_transfert_value', store=True, readonly=True, copy=False)
    cmp_in_amount = fields.Float("Entry cost unit",  compute='_update_transfert_value', store=True, readonly=True, copy=False)
    charge_out_amount = fields.Float("Exit Fees Unit", compute='_update_transfert_value', store=True, readonly=True, copy=False)
    charge_in_amount = fields.Float("Entry Fees Unit",  compute='_update_transfert_value', store=True, readonly=True, copy=False)
    internal_picking_id = fields.Many2one('internal.picking', 'Transfert', required=True, readonly=True)
    stock_move_ids = fields.One2many('stock.move', 'internal_picking_line_id', string="Stock Move Lines",readonly=True, copy=False)







    @api.multi
    def check_line(self, sens):
        for r in self:
            if sens == 'sent':
                if not r.quantity_ask > 0:
                    raise UserError("""Veuillez Saisir une quantité initiale prévue au chargement.""")
            elif sens == 'load':
                if r.quantity_load <= 0  or  r.quantity_ask < r.quantity_load:
                    raise UserError("""Veuillez Saisir une quantité chaegée non nulle ou négatif et non supérieur à la quantité prévue.""")
            elif sens == 'done':
                if r.quantity_done <= 0 or  r.quantity_load < r.quantity_done:
                    raise UserError("""Veuillez Saisir une quantité récepttonnée non nulle ou négatif et non supérieur à la quantité prévue.""")
            else:
                raise UserError(
                    """Ce type d'opération n'est pas prévue. Contacter votre administrateur.""")

    @api.multi
    @api.onchange('product_id')
    def onchange_product_id(self):
        self.ensure_one()
        self.product_uom = self.product_id.uom_id

    @api.multi
    def _get_stock_move_price_unit(self,sens):
        self.ensure_one()
        StockQuant = self.env['stock.quant']
        price = 0.0
        if sens == 'out':
            quant_id = self.env['stock.quant']._gather(self.product_id, self.internal_picking_id.location_src_id)
            # quant_id.ensure_one()
            price =  1 * quant_id.cost
        if sens == 'in':
            # TODO: Retrouver ligne source
            price = 1 * (self.cmp_out_amount + self.charge_out_amount)
        if sens == 'loss':
            price = 1 * (self.cmp_out_amount + self.charge_out_amount)
        return price

    @api.multi
    def _prepare_stock_moves(self, picking):
        """ Prepare the stock moves data for one order line. This function returns a list of
        dictionary ready to be used in stock.move's create()
        """
        self.ensure_one()
        res = []
        if self.product_id.type not in ['product', 'consu']:
            return res

        qty = 0.0
        sens = self.internal_picking_id.get_move_direction(picking)
        price_unit = self._get_stock_move_price_unit(sens)
        if sens == 'out':
            qty_uom = self.quantity_load
            date_expected = self.internal_picking_id.date_load
            scheduled_date = self.internal_picking_id.date_load
        elif sens == 'in':
            qty_uom = self.quantity_done
            date_expected = self.internal_picking_id.date_done
            scheduled_date = self.internal_picking_id.date_done

        elif sens == 'loss':
            qty_uom = self.quantity_load - self.quantity_done
            date_expected = self.internal_picking_id.date_done
            scheduled_date = self.internal_picking_id.date_done

        qty = self.product_uom._compute_quantity(qty_uom, self.product_uom, rounding_method='HALF-UP')

        template = {
            # truncate to 2000 to avoid triggering index limit error
            # TODO: remove index in master?
            'name': self.internal_picking_id.name + ': ' + sens,
            'product_id': self.product_id.id,
            'product_uom_qty':qty,
            'product_uom': self.product_uom.id,
            'date': date_expected,
            'date_expected': date_expected,
            'scheduled_date': scheduled_date,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'picking_id': picking.id,
            'partner_id': picking.partner_id.dest_address_id.id if picking.partner_id else None,
            'state': 'draft',
            'company_id': self.internal_picking_id.company_id.id,
            'price_unit': price_unit,
            'picking_type_id': picking.picking_type_id.id,
            'origin': picking.name,
            'route_ids': picking.picking_type_id.warehouse_id and [(6, 0, [x.id for x in picking.picking_type_id.warehouse_id.route_ids])] or [],
            'warehouse_id': picking.picking_type_id.warehouse_id.id,
            'internal_picking_line_id': self.id,
        }

        if sens in ['loss','in']:
            move_orig_id = self.stock_move_ids.filtered(lambda x: x._is_out())
            move_orig_id.ensure_one()
            template['move_orig_ids'] = [(4, move_orig_id.id)]
        # diff_quantity = self.product_qty - qty
        # if float_compare(diff_quantity, 0.0,  precision_rounding=self.product_uom.rounding) > 0:
        #     quant_uom = self.product_id.uom_id
        #     get_param = self.env['ir.config_parameter'].sudo().get_param
        #     if self.product_uom.id != quant_uom.id and get_param('stock.propagate_uom') != '1':
        #         product_qty = self.product_uom._compute_quantity(diff_quantity, quant_uom, rounding_method='HALF-UP')
        #         template['product_uom'] = quant_uom.id
        #         template['product_uom_qty'] = product_qty
        #     else:
        #         template['product_uom_qty'] = diff_quantity
        res.append(template)
        return res

    @api.multi
    def _create_stock_moves(self, picking):
        values = []
        Charges = self.env['transfert.charges']
        sens = self.internal_picking_id.get_move_direction(picking)
        for line in self:
            val = line._prepare_stock_moves(picking)
            values+=val
        res = self.env['stock.move'].create(values)
        for move in res:
            internal_picking_id = move.internal_picking_line_id.internal_picking_id
            transfert_charges_ids = Charges._get_all_specics_structures(picking.date,
                                                                        self.product_id,
                                                                        internal_picking_id.location_src_id,
                                                                        internal_picking_id.location_dest_id,
                                                                        sens)
            facteur = 1
            sens = move._is_out()
            sens1 = move._is_in()
            # if move_line.location_id._should_be_valued() and not move_line.location_dest_id._should_be_valued()
            if move._is_out():
                facteur = -1
            for charge in transfert_charges_ids:
                cost = self.env.user.company_id.currency_id.round(abs(move.product_qty * charge.value))
                charge_id = move.charges_ids.create([{
                    'stock_move_id': move.id,
                    'rubrique_id': charge.rubrique_id.id,
                    'transfert_charge_id': charge.id,
                    'cost': facteur * cost,
                }])

            # move.transfert_charges_ids = [(4, x.id) for x in transfert_charges_ids]

        return res

    @api.multi
    def action_cancel(self):
        for r in self.self.stock_move_ids:
            r._action_cancel()
