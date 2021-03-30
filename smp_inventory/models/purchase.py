# -*- coding: utf-8 -*-

from datetime import datetime
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, SUPERUSER_ID, _
from odoo.osv import expression
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools.float_utils import float_compare
from odoo.exceptions import UserError, AccessError
from odoo.tools.misc import formatLang
from odoo.addons import decimal_precision as dp



class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'


    purchase_order_cost_ids = fields.One2many('purchase.order.cost', 'po_id')
    cost_visible = fields.Boolean('Cost Visible', compute="_is_cost_visble", readonly = True)
    currency_rate = fields.Float('Currency rate', digits=(12, 6), default=1.0)
    currency_rate_visible = fields.Boolean('Currency rate visible')

    @api.onchange("currency_id")
    def _get_currency_rate_visible(self):
        if self.currency_id:
            self.currency_rate_visible = False
            if self.currency_id != self.env.user.company_id.currency_id:
                self.currency_rate_visible = True

    @api.onchange("currency_id")
    def _get_currency_rate(self):
        if self.currency_id:
            if self.currency_id != self.env.user.company_id.currency_id:
                from_currency = self.currency_id
                to_currency = self.env.user.company_id.currency_id
                company = self.env.user.company_id
                date = self.date_order
                currency_rate = self.env['res.currency']._get_conversion_rate(from_currency, to_currency, company, date)
                currency_rate = from_currency.rate
                self.currency_rate = currency_rate
            else:
                self.currency_rate = 1

    @api.depends("purchase_order_cost_ids")
    def _is_cost_visble(self):
        if self.purchase_order_cost_ids:
            self.cost_visible = True
        else:
            self.cost_visible = False

    @api.multi
    def compute_cost_landing(self):
        for po_id in self:
            """on supprime les po_line_cost_ids existants"""
            po_id.purchase_order_cost_ids.mapped('po_cost_line_ids').unlink()

            """on recrées les po_line_cost_ids"""
            po_id.purchase_order_cost_ids.create_cost_line()

            """on calcule les charges"""
            po_id.purchase_order_cost_ids.compute_landed_cost()

            po_id.order_line._update_po_cost()

    @api.multi
    def get_weight_volume(self):
        self.ensure_one()
        lines_to_input = self.purchase_order_cost_ids.filtered(lambda x: x.split_method in ('by_weight', 'by_volume'))
        if lines_to_input:
            print('6666')
            Po_Wizard = self.env['purchase.order.cost.wizard']
            # co = lines_to_input.po_line_ids
            # cox = [(4, p.id) for p in lines_to_input.po_line_ids]
            wiz = Po_Wizard.create({
                'po_line_ids': [(4, p.id) for p in lines_to_input.po_line_ids],
                'po_id': self.id})
            view_id = self.env.ref('smp_inventory.purchase_order_cost_wizard_form')
            action = Po_Wizard.get_formview_action()
            action['res_id'] = wiz.id
            action['view_id'] = view_id.id
            action['target'] = 'new'
            return action
        else:
            self.compute_cost_landing()
            # TODO: Ouvrir wizard de saisie

    # @api.multi
    # def compute_landed_cost(self):
    #     AdjustementLines = self.env['stock.valuation.adjustment.lines']
    #     AdjustementLines.search([('cost_id', 'in', self.ids)]).unlink()
    #
    #     digits = dp.get_precision('Product Price')(self._cr)
    #     towrite_dict = {}
    #     for cost in self.filtered(lambda cost: cost.picking_ids):
    #         total_qty = 0.0
    #         total_cost = 0.0
    #         total_weight = 0.0
    #         total_volume = 0.0
    #         total_line = 0.0
    #         all_val_line_values = cost.get_valuation_lines()
    #         for val_line_values in all_val_line_values:
    #             for cost_line in cost.cost_lines:
    #                 val_line_values.update({'cost_id': cost.id, 'cost_line_id': cost_line.id})
    #                 self.env['stock.valuation.adjustment.lines'].create(val_line_values)
    #             total_qty += val_line_values.get('quantity', 0.0)
    #             total_weight += val_line_values.get('weight', 0.0)
    #             total_volume += val_line_values.get('volume', 0.0)
    #
    #             former_cost = val_line_values.get('former_cost', 0.0)
    #             # round this because former_cost on the valuation lines is also rounded
    #             total_cost += tools.float_round(former_cost, precision_digits=digits[1]) if digits else former_cost
    #
    #             total_line += 1
    #
    #         for line in cost.cost_lines:
    #             value_split = 0.0
    #             for valuation in cost.valuation_adjustment_lines:
    #                 value = 0.0
    #                 if valuation.cost_line_id and valuation.cost_line_id.id == line.id:
    #                     if line.split_method == 'by_quantity' and total_qty:
    #                         per_unit = (line.price_unit / total_qty)
    #                         value = valuation.quantity * per_unit
    #                     elif line.split_method == 'by_weight' and total_weight:
    #                         per_unit = (line.price_unit / total_weight)
    #                         value = valuation.weight * per_unit
    #                     elif line.split_method == 'by_volume' and total_volume:
    #                         per_unit = (line.price_unit / total_volume)
    #                         value = valuation.volume * per_unit
    #                     elif line.split_method == 'equal':
    #                         value = (line.price_unit / total_line)
    #                     elif line.split_method == 'by_current_cost_price' and total_cost:
    #                         per_unit = (line.price_unit / total_cost)
    #                         value = valuation.former_cost * per_unit
    #                     else:
    #                         value = (line.price_unit / total_line)
    #
    #                     if digits:
    #                         value = tools.float_round(value, precision_digits=digits[1], rounding_method='UP')
    #                         fnc = min if line.price_unit > 0 else max
    #                         value = fnc(value, line.price_unit - value_split)
    #                         value_split += value
    #
    #                     if valuation.id not in towrite_dict:
    #                         towrite_dict[valuation.id] = value
    #                     else:
    #                         towrite_dict[valuation.id] += value
    #     for key, value in towrite_dict.items():
    #         AdjustementLines.browse(key).write({'additional_landed_cost': value})
    #     return True


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _compute_default_date_planned(self):
        return self.order_id.date_order

    date_planned = fields.Datetime(string='Scheduled Date', required=True, index=True, default=_compute_default_date_planned)
    cost_landing_value = fields.Float(compute='_compute_cost_landing',string='Cost landing', store=True, default=0.0)
    price_total_all_cost = fields.Monetary(compute='_compute_cost_landing', string='Total with cost', store=True)
    po_cost_line_ids = fields.One2many('purchase.order.cost.line','po_line_id')
    volume = fields.Float('Volume', required=True, digits=dp.get_precision('Product UoS'), default=lambda self: self.product_id.volume)
    weight = fields.Float('Weight', required=True, digits=dp.get_precision('Product UoS'), default=lambda self: self.product_id.weight)
    cost_visible = fields.Boolean('Cost Visible', related="order_id.cost_visible", readonly = True)

    @api.multi
    def _update_po_cost(self):
        for po_line_id in self:
            cost_landing_value = sum(po_line_id.po_cost_line_ids.mapped('value'))
            po_line_id.cost_landing_value = cost_landing_value
            po_line_id.price_total_all_cost = po_line_id.price_total + cost_landing_value

    @api.depends('product_qty', 'price_unit', 'taxes_id')
    def _compute_amount(self):
        for line in self:
            vals = line._prepare_compute_all_values()
            taxes = line.taxes_id.compute_all(
                vals['price_unit'],
                vals['currency_id'],
                vals['product_qty'],
                vals['product'],
                vals['partner'])
            line.update({
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })

    @api.multi
    @api.depends('product_uom', 'product_qty', 'product_id.uom_id')
    def _compute_product_uom_qty(self):
        for line in self:
            if line.product_id.uom_id != line.product_uom:
                if line.product_id.is_uom_inter_category and line.product_uom.category_id == line.product_id.uom_po_id.category_id:
                    product_uom_qty = line.product_uom._compute_quantity(line.product_qty, line.product_id.uom_po_id)
                    line.product_uom_qty = line.product_id.inter_uom_factor * product_uom_qty
                else:
                    line.product_uom_qty = line.product_uom._compute_quantity(line.product_qty, line.product_id.uom_id)
            else:
                line.product_uom_qty = line.product_qty

    @api.multi
    def _get_stock_move_price_unit(self):
        self.ensure_one()
        line = self[0]
        order = line.order_id
        price_unit = line.price_unit
        if line.taxes_id:
            price_unit = line.taxes_id.with_context(round=False).compute_all(
                price_unit, currency=line.order_id.currency_id, quantity=1.0, product=line.product_id, partner=line.order_id.partner_id
            )['total_excluded']
        if line.product_uom.id != line.product_id.uom_id.id:
            if line.product_id.is_uom_inter_category and line.product_uom.category_id == line.product_id.uom_po_id.category_id:
                price_unit *= (line.product_uom.factor / line.product_id.uom_po_id.factor) / line.product_id.inter_uom_factor
            else:
                # line.product_uom_qty = line.product_uom._compute_quantity(line.product_qty, line.product_id.uom_id)
                price_unit *= line.product_uom.factor / line.product_id.uom_id.factor
        if order.currency_id != order.company_id.currency_id:
            price_unit = order.currency_id.with_context(force_currency_rate=self.order_id.currency_rate)._convert(
                price_unit, order.company_id.currency_id, self.company_id, self.date_order or fields.Date.today(), round=False)
        return price_unit

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
        price_unit = self._get_stock_move_price_unit()
        for move in self.move_ids.filtered(lambda x: x.state != 'cancel' and not x.location_dest_id.usage == "supplier"):
            qty += move.product_uom._compute_quantity(move.product_uom_qty, self.product_uom, rounding_method='HALF-UP')
        template = {
            # truncate to 2000 to avoid triggering index limit error
            # TODO: remove index in master?
            'name': (self.name or '')[:2000],
            'product_id': self.product_id.id,
            'product_uom': self.product_uom.id,
            'date': self.order_id.date_order,
            'date_expected': self.date_planned,
            'location_id': self.order_id.partner_id.property_stock_supplier.id,
            'location_dest_id': self.order_id._get_destination_location(),
            'picking_id': picking.id,
            'partner_id': self.order_id.dest_address_id.id,
            'move_dest_ids': [(4, x) for x in self.move_dest_ids.ids],
            'state': 'draft',
            'purchase_line_id': self.id,
            'company_id': self.order_id.company_id.id,
            'price_unit': price_unit,
            'picking_type_id': self.order_id.picking_type_id.id,
            'group_id': self.order_id.group_id.id,
            'origin': self.order_id.name,
            'route_ids': self.order_id.picking_type_id.warehouse_id and [(6, 0, [x.id for x in self.order_id.picking_type_id.warehouse_id.route_ids])] or [],
            'warehouse_id': self.order_id.picking_type_id.warehouse_id.id,
        }
        diff_quantity = self.product_qty - qty
        if float_compare(diff_quantity, 0.0,  precision_rounding=self.product_uom.rounding) > 0:
            quant_uom = self.product_id.uom_id
            get_param = self.env['ir.config_parameter'].sudo().get_param
            if self.product_uom.id != quant_uom.id and get_param('stock.propagate_uom') != '1':
                if self.product_id.is_uom_inter_category and self.product_uom.category_id == self.product_id.uom_po_id.category_id:
                    product_uom_quantity = self.product_uom._compute_quantity(diff_quantity, self.product_id.uom_po_id, rounding_method='HALF-UP')
                    product_qty = product_uom_quantity * self.product_id.inter_uom_factor
                    template['inter_uom_factor'] = self.product_id.inter_uom_factor
                else:
                    product_qty = self.product_uom._compute_quantity(diff_quantity, quant_uom, rounding_method='HALF-UP')
                template['product_uom'] = quant_uom.id
                template['product_uom_qty'] = product_qty
            else:
                template['product_uom_qty'] = diff_quantity
            if self.product_uom.id != self.product_id.uom_id.id:
                if self.product_id.is_uom_inter_category and self.product_uom.category_id == self.product_id.uom_po_id.category_id:
                    template['inter_uom_factor'] = self.product_id.inter_uom_factor

            res.append(template)
        return res

    @api.multi
    def _create_stock_moves(self, picking):
        stock_move_ids = super(PurchaseOrderLine,self)._create_stock_moves(picking)
        for stock_move_id in stock_move_ids:
            stock_move_id.charges_ids.create_purchase_charges(stock_move_id)
        return stock_move_ids



    # def _creates_stock_moves_charges(self):
    #     for po_line in self:
    #         for po_cost_line in po_line.po_cost_line_ids:
    #             cost = self.env.user.company_id.currency_id.round(abs(po_cost_line))
    #             self.env['stock.move.charges'].create({'stock_move_id': move.id,
    #                                                    'rubrique_id': po_cost_line.rubrique_id.id,
    #                                                    'purchase_charge_id': po_line.id,
    #                                                    'cost': facteur * cost,})
    #             cost = self.env.user.company_id.currency_id.round(abs(move.product_qty * charge.value))
    #             charge_id = move.charges_ids.create([{
    #                 'stock_move_id': move.id,
    #                 'rubrique_id': charge.rubrique_id.id,
    #                 'transfert_charge_id': charge.id,
    #                 'cost': facteur * cost,
    #             }])


class PurchaseOrderCost(models.Model):
    _name = 'purchase.order.cost'
    _description = 'Purchase Order Landed Cost '

    SPLIT_METHOD = [
        ('equal', 'Equal'),
        ('by_quantity', 'By Quantity'),
        ('by_current_cost_price', 'By Current Cost'),
        ('by_weight', 'By Weight'),
        ('by_volume', 'By Volume'),
    ]

    STATES = {
        'draft':[('readonly', False)]
    }
    # , readonly = True, states = STATES
    name = fields.Char('Description')
    state = fields.Selection(related="po_id.state",string='State')
    rubrique_id = fields.Many2one('product.product', 'Product', required=True, domain=[('type','=','service')])
    po_id = fields.Many2one('purchase.order', 'Purchase Order ', required=True, ondelete='cascade')
    po_line_ids = fields.Many2many('purchase.order.line')
    po_cost_line_ids = fields.One2many('purchase.order.cost.line', 'po_cost_id',string='Ligne de charges')
    value = fields.Float('Value', digits=dp.get_precision('Product Price'), required=True)
    split_method = fields.Selection(SPLIT_METHOD, string='Split Method', required=True)
    account_id = fields.Many2one('account.account', 'Account', domain=[('deprecated', '=', False)])
    to_invoice = fields.Boolean('To Invoice', readonly=True, states=STATES)
    partner_id = fields.Many2one('res.partner','Supplier',domain=[('supplier','=',True)])

    @api.onchange('rubrique_id')
    def onchange_rubrique_id(self):
        self.name = self.rubrique_id.name or ''
        self.split_method = 'equal'
        self.value = 0.0
        self.account_id = self.rubrique_id.property_account_income_id.id or\
                          self.rubrique_id.categ_id.property_account_income_categ_id.id



    @api.model
    def create(self, vals):
        # vals['name'] = self.env['ir.sequence'].get('bulletin.bulletin') or '/'
        res_id = super(PurchaseOrderCost, self).create(vals)
        return res_id


    @api.multi
    def create_cost_line(self):
        for po_cost in self:
            if po_cost.po_line_ids:
                for po_line in po_cost.po_line_ids:
                    res ={
                        'volume': 0.0,
                        'quantity': 0.0,
                        'weight': 0.0,
                        'value': 0.0,
                        'po_line_id': po_line.id,
                        'po_cost_id': po_cost.id,
                        'rubrique_id': po_cost.rubrique_id.id,
                    }
                    po_cost.po_cost_line_ids.create(res)

    @api.multi
    def compute_landed_cost(self):
        for cost in self:
            total_qty = sum(cost.po_cost_line_ids.mapped('product_uom_qty'))
            total_cost = sum(cost.po_cost_line_ids.mapped('po_line_id').mapped('price_subtotal'))
            total_weight = sum(cost.po_cost_line_ids.mapped('weight'))
            total_volume = sum(cost.po_cost_line_ids.mapped('volume'))
            total_line = len(cost.po_cost_line_ids)

            for po_cost_line in cost.po_cost_line_ids:
                if cost.split_method == 'by_quantity' and total_qty:
                    per_unit = (po_cost_line.po_line_id.product_uom_qty / total_qty)
                    value = cost.value * per_unit
                elif cost.split_method == 'by_weight' and total_weight:
                    per_unit = (po_cost_line.po_line_id.weight / total_weight)
                    value = cost.value * per_unit
                elif cost.split_method == 'by_volume' and total_volume:
                    per_unit = (po_cost_line.po_line_id.volume / total_volume)
                    value = cost.value * per_unit
                elif cost.split_method == 'equal':
                    value = (cost.value / total_line)
                elif cost.split_method == 'by_current_cost_price' and total_cost:
                    per_unit = (po_cost_line.po_line_id.price_subtotal / total_cost)
                    value = cost.value * per_unit
                else:
                    value = (cost.value / total_line)

                po_cost_line.value = value


class PurchaseOrderCostLine(models.Model):
    _name = 'purchase.order.cost.line'
    _description = 'Purchase Order Landed Cost Line'

    name = fields.Char('Description')
    po_line_id = fields.Many2one('purchase.order.line', 'Order Line', required=True, ondelete='cascade')
    po_cost_id = fields.Many2one('purchase.order.cost', 'Cost', required=True, ondelete='cascade')
    rubrique_id = fields.Many2one('product.product', 'Product', required=True)
    value = fields.Float('Cost', digits=dp.get_precision('Product Price'))
    account_id = fields.Many2one('account.account', 'Account', domain=[('deprecated', '=', False)], )
    split_method = fields.Selection(related='po_cost_id.split_method', string='Split Method', required=True, default='equal')
    volume = fields.Float('Volume', digits=dp.get_precision('Product UoS'),
                          default=lambda self: self.po_line_id.product_id.volume,
                          related='po_line_id.volume')
    # volume = fields.Float('Volume', required=True, digits=dp.get_precision('Product UoS'), default=lambda self: self.product_id.volume)
    weight = fields.Float('Weight', digits=dp.get_precision('Product UoS'),
                          default=lambda self: self.po_line_id.product_id.weight,
                          related='po_line_id.weight')

    product_uom_qty = fields.Float('Quantity', digits=dp.get_precision('Product UoS'),
                          default= 0.0,
                          related='po_line_id.product_qty')


class PurchaseOrderCostWizard(models.TransientModel):
    _name = 'purchase.order.cost.wizard'

    po_id = fields.Many2one('purchase.order')
    po_line_ids = fields.Many2many('purchase.order.line')

    @api.multi
    def process(self):
        self.ensure_one()
        self.po_id.compute_cost_landing()
        return True
