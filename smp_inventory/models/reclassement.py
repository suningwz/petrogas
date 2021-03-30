# -*- coding: utf-8 -*-

from odoo import api, fields, models, _, exceptions, tools
from odoo.exceptions import UserError, ValidationError
import time
from datetime import datetime, timedelta, date
from odoo.addons import decimal_precision as dp
from odoo.tools.float_utils import float_compare, float_is_zero


class Reclassement (models.Model):

    _name = "reclassement"
    _description = "Reclassement"

    name = fields.Char('Séquence', default="/", copy=False)

    location_id = fields.Many2one('stock.location', 'Dépot', domain=[('usage', '=', 'internal')],
                                       required=True, states={'draft': [('readonly', False)]})
    date_sent = fields.Date("Creation date", states={'draft': [('readonly', False), ('required', True)]},
                            default=fields.Date.today)
    date_done = fields.Date('Date de reclassement', states={'open': [('readonly', False),('required', True)]})
    creater_id = fields.Many2one('res.users', 'Created by', readonly=True)
    finisher_id = fields.Many2one('res.users', 'Confirmed by', readonly=True)
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.user.company_id.id,
                                 readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('sent', 'Sent'), ('done', 'Done')],
                             'Status', default='draft', required=True)
    reclassement_line_ids = fields.One2many('reclassement.line', 'reclassement_id', string="Reclassements Lines")


    @api.multi
    def copy_data(self, default=None):
        if default is None:
            default = {}
        if 'order_line' not in default:
            default['reclassement_line_ids'] = [(0, 0, line.copy_data()[0]) for line in self.reclassement_line_ids]
        return super(Reclassement, self).copy_data(default)

    @api.multi
    def check_reclassement(self,):
        if not self.reclassement_line_ids:
            raise UserError("""Veuillez saisir des lignes à reclasser.""")
        self.reclassement_line_ids.check_line()

    @api.multi
    def sent(self):
        self.ensure_one()
        self.check_reclassement()
        if self.name == '/':
            self.name = self.env['ir.sequence'].next_by_code('product.reclassement')
        for line in self.reclassement_line_ids:
            move_ids = line.stock_move_ids
            for sens in ['out','in']:
                print('sens: ', sens)
                move = line._create_stock_moves(sens)
                if sens == 'in':
                    move_ids.ensure_one()
                    move.move_orig_ids = [(4, x.id) for x in move_ids]
                    move_ids.move_dest_ids = [(4, move.id)]
                move_ids |= move
            line.stock_move_ids._action_confirm(merge=False)

        self.state = 'sent'
        self.creater_id = self.env.user

    @api.multi
    def done(self):
        self.ensure_one()
        self.check_reclassement()
        # TODO Create Picking
        for line in self.reclassement_line_ids:
            for move in line.stock_move_ids.sorted(lambda x: x.id):
                move.quantity_done = move.product_uom_qty
                move._action_done()
            sm_out = line.stock_move_ids.filtered(lambda x: x._is_out())
            sm_in = line.stock_move_ids.filtered(lambda x: x._is_in())
            line.cmp_out_amount = sm_out.price_unit
            line.charge_in_amount = sm_in.landed_cost_value / sm_out.product_qty
            line.cmp_in_amount = sm_in.price_unit

        self.state = 'done'
        self.finisher_id = self.env.user


class ReclassementLine(models.Model):
    _name = "reclassement.line"
    _description = "Reclassement Line"

    state = fields.Selection(related="reclassement_id.state", string="Statut", readonly=True, default='draft')

    product_src_id = fields.Many2one('product.product', 'Produit Source', domain=[('type', 'in', ['product', 'consu'])], index=True, required=True, states={'draft': [('readonly', False)]})
    product_dest_id = fields.Many2one('product.product', 'Produit Destination', domain=[('type', 'in', ['product', 'consu'])], index=True, required=True, states={'draft': [('readonly', False)]})

    product_src_uom = fields.Many2one('uom.uom', 'Unit of Measure', required=True, states={'draft': [('readonly', False)]})
    product_dest_uom = fields.Many2one('uom.uom', 'Unit of Measure', required=True, states={'draft': [('readonly', False)]})

    quantity_src = fields.Float('Quantité Source', digits=dp.get_precision('Product Unit of Measure'), states={'draft': [('readonly', False)]}, required=True, default=0.0)
    quantity_dest = fields.Float('Quantité Destination', digits=dp.get_precision('Product Unit of Measure'), states={'sent': [('readonly', False)]}, required=True, default=0.0)

    cmp_out_amount = fields.Float('Coût unitare de sortie', readonly=True, copy=False)
    cmp_in_amount = fields.Float("Coût unitare d'entrée", readonly=True, copy=False)

    # charge_out_amount = fields.Float("Frais unitare de sortie", readonly=True, copy=False)
    charge_in_amount = fields.Float("Frais unitare d'entrée", readonly=True, copy=False)

    stock_move_ids = fields.One2many('stock.move', 'reclassement_line_id', string="Stock move lines",readonly=True, copy=False)

    reclassement_id = fields.Many2one('reclassement', 'Reclassement', required=True, readonly=True)

    @api.multi
    def check_line(self):
        for line in self:
            if not all([line.quantity_dest, line.quantity_src]):
                raise UserError("Attention! Vérifier les quantités source et de destination.Svp!")

    @api.multi
    @api.onchange('product_src_id', 'product_dest_id')
    def onchange_product_id(self):
        self.ensure_one()
        self.product_src_uom = self.product_src_id.uom_id
        self.product_dest_uom = self.product_dest_id.uom_id

    @api.multi
    def _prepare_stock_moves(self, sens):
        """ Prepare the stock moves data for one order line. This function returns a list of
        dictionary ready to be used in stock.move's create()
        """
        self.ensure_one()
        res = []
        product_id = self.product_src_id if sens == 'out' else self.product_dest_id
        if product_id.type not in ['product', 'consu']:
            return res

        reclassment_location_id = self.env.ref('smp_inventory.smp_reclassement')
        qty = 0.0

        qty_uom = self.quantity_src if sens == 'out' else self.quantity_dest
        product_uom = self.product_src_uom if sens == 'out' else self.product_dest_uom
        date_expected = self.reclassement_id.date_sent
        scheduled_date = self.reclassement_id.date_done
        location_src_id = self.reclassement_id.location_id if sens == 'out' else reclassment_location_id
        location_dest_id = reclassment_location_id if sens == 'out' else self.reclassement_id.location_id
        picking_type_id = self.env.ref('smp_inventory.picking_type_reclassement_out') if sens == 'out' else self.env.ref('smp_inventory.picking_type_reclassement_in')

        qty = product_uom._compute_quantity(qty_uom, product_id.uom_id, rounding_method='HALF-UP')

        template = {
            # truncate to 2000 to avoid triggering index limit error
            # TODO: remove index in master?
            'name': self.reclassement_id.name + ': ' + sens,
            'product_id': product_id.id,
            'product_uom_qty': qty,
            'product_uom': product_uom.id,
            'date': date_expected,
            'date_expected': date_expected,
            # 'scheduled_date': scheduled_date,
            'location_id': location_src_id.id,
            'location_dest_id': location_dest_id.id,
            # 'picking_id': picking.id,
            # 'partner_id': picking.partner_id.dest_address_id.id if picking.partner_id else None,
            'state': 'draft',
            'company_id': self.reclassement_id.company_id.id,
            # 'price_unit': price_unit,
            'picking_type_id': picking_type_id.id,
            'origin': self.reclassement_id.name + ': ' + sens,
            'route_ids': picking_type_id.warehouse_id and [(6, 0, [x.id for x in picking_type_id.warehouse_id.route_ids])] or [],
            'warehouse_id': picking_type_id.warehouse_id.id,
            'reclassement_line_id': self.id,
        }

        if sens in ['in']:
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
    def _create_stock_moves(self, sens):
        values = []
        Charges = self.env['reclassement.charges']

        for line in self:
            val = line._prepare_stock_moves(sens)
            values += val
        res = self.env['stock.move'].create(values)

        for move in res:
            facteur = 1
            if move._is_out():
                facteur = -1
            reclassement_id = move.reclassement_line_id.reclassement_id
            reclassement_charges_ids = Charges._get_all_specics_structures(move.date,
                                                                           self.product_src_id,
                                                                           self.product_dest_id,
                                                                           reclassement_id.location_id,
                                                                           sens)

            for charge in reclassement_charges_ids:
                cost = self.env.user.company_id.currency_id.round(abs(move.product_qty * charge.value))
                charge_id = move.charges_ids.create([{
                    'stock_move_id': move.id,
                    'rubrique_id': charge.rubrique_id.id,
                    'reclassement_charge_id': charge.id,
                    'cost': facteur * cost,
                }])
            # move.reclassement_charges_ids = [(4, x.id) for x in reclassement_charges_ids]
        return res