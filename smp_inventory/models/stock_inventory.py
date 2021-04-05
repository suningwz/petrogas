# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_utils, float_compare
import calendar as cal
from datetime import datetime, date

class Inventory(models.Model):
    _inherit = "stock.inventory"

    def action_cancel_done(self):
        for r in self:
            for move in r.move_ids:
                account_move_ids = move.mapped('account_move_ids')
                account_move_ids.sudo().button_cancel()
                account_move_ids.unlink()
                move.write({'state': 'draft'})
                move.unlink()

            for line in r.line_ids:
                domain = [('product_id', '=', line.product_id.id), ('location_id', '=', line.location_id.id)]
                quant_id = self.env['stock.quant'].search(domain)
                quant_id.ensure_one()
                diff = line.theoretical_qty - line.product_qty
                quant_id.quantity += diff

            r.state = 'cancel'

    def update_picking_type(self):
        inventory_in = self.env.ref('smp_inventory.picking_type_inventory_in')
        inventory_out = self.env.ref('smp_inventory.picking_type_inventory_out')
        for r in self:
            for move_id in r.move_ids:
                move_id.picking_type_id = inventory_in if move_id.location_id == inventory_in.default_location_src_id else inventory_out

    def _get_inventory_lines_values(self):
        # TDE CLEANME: is sql really necessary ? I don't think so
        locations = self.env['stock.location'].search([('id', 'child_of', [self.location_id.id])])
        domain = " location_id in %s AND state = 'done'"
        # domain = ' location_id in %s'
        args = (tuple(locations.ids),)

        vals = []
        Product = self.env['product.product']
        # Empty recordset of products available in stock_quants
        quant_products = self.env['product.product']
        # Empty recordset of products to filter
        products_to_filter = self.env['product.product']

        # case 0: Filter on company
        if self.company_id:
            domain += ' AND company_id = %s'
            args += (self.company_id.id,)


        # # case 1: Filter on One owner only or One product for a specific owner
        # if self.partner_id:
        #     domain += ' AND owner_id = %s'
        #     args += (self.partner_id.id,)
        # # case 2: Filter on One Lot/Serial Number
        # if self.lot_id:
        #     domain += ' AND lot_id = %s'
        #     args += (self.lot_id.id,)
        # case 3: Filter on One product
        if self.product_id:
            domain += ' AND product_id = %s'
            args += (self.product_id.id,)
            products_to_filter |= self.product_id
        # # case 4: Filter on A Pack
        # if self.package_id:
        #     domain += ' AND package_id = %s'
        #     args += (self.package_id.id,)
        # case 5: Filter on One product category + Exahausted Products
        if self.category_id:
            categ_products = Product.search([('categ_id', 'child_of', self.category_id.id)])
            domain += ' AND product_id = ANY (%s)'
            args += (categ_products.ids,)
            products_to_filter |= categ_products

        if self.date:
            domain += ' AND date_expected BETWEEN %s AND %s'
            date_from = datetime(self.date.year, 1,1,0,0,0)
            # fiscalyear_from = self.env['account.fiscal.year'].search([
            #     ('company_id', '=', self.id),
            #     ('date_from', '<=', self.date),
            #     ('date_to', '>=', self.date),
            # ], limit=1)
            # if fiscalyear_from:
            #     date_from = fiscalyear_from.date_from
            # else:
            #     raise UserError(_("Please configure a fiscalyear"))
            t = (date_from.strftime('%Y-%m-%d'), self.date.strftime('%Y-%m-%d'),)
            args += (date_from.strftime('%Y-%m-%d'), self.date.strftime('%Y-%m-%d'),)



        domain_in =  domain.replace('location_id','location_dest_id')
        args += args
        self.env.cr.execute("""
            select 
                product_id,
                sum(product_qty) as product_qty,
                sum(value) as value,
                location_id
            
            from (
                SELECT 
                    product_id, 
                    SUM(-product_qty) as product_qty, 
                    SUM(CASE 
                        WHEN stock_picking_type.code != 'outgoing' THEN -(value + landed_cost_value) ELSE -value
                        END ) as value,
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
        for product_data in res:
            # replace the None the dictionary by False, because falsy values are tested later on
            for void_field in [item[0] for item in product_data.items() if item[1] is None]:
                product_data[void_field] = False
            product_data['theoretical_qty'] = product_data['product_qty']
            product_data['product_value'] = product_data['value']
            product_data['product_theoretical_value'] = product_data['value']
            if product_data['product_id']:
                product_data['product_uom_id'] = Product.browse(product_data['product_id']).uom_id.id
                quant_products |= Product.browse(product_data['product_id'])
            vals.append(product_data)



        if self.exhausted:
            exhausted_vals = self._get_exhausted_inventory_line(products_to_filter, quant_products)
            vals.extend(exhausted_vals)
        return vals

    def action_start(self):
        for inventory in self.filtered(lambda x: x.state not in ('done','cancel')):
            vals = {'state': 'confirm'}
            if (inventory.filter != 'partial') and not inventory.line_ids:
                vals.update({'line_ids': [(0, 0, line_values) for line_values in inventory._get_inventory_lines_values()]})
            inventory.write(vals)
        return True


class InventoryLine(models.Model):
    _inherit = "stock.inventory.line"

    product_value = fields.Float('Value', digits=dp.get_precision('Account'), store=True)

    product_theoretical_value = fields.Float(
        'Theoretical Value', compute='_compute_theoretical_qty',
        digits=dp.get_precision('Account'), store=True)

    def _get_move_values(self, qty, location_id, location_dest_id, out):
        self.ensure_one()
        res = super(InventoryLine,self)._get_move_values(qty, location_id, location_dest_id, out)
        diff = self.theoretical_qty - self.product_qty
        sens = 'IN/' if diff < 0 else 'OUT/:'
        diff = self.theoretical_qty - self.product_qty
        res['picking_type_id'] = self.env.ref('smp_inventory.picking_type_inventory_in').id if diff < 0 else self.env.ref('smp_inventory.picking_type_inventory_out').id
        res['name'] = 'INV/' + sens + (self.inventory_id.name)
        res['origin'] = self.inventory_id.name
        res['ref'] = self.inventory_id.name
        res['value'] = self.product_value
        res['price_unit'] = self.product_value / qty
        res['date'] = self.inventory_id.date
        res['date_expected'] = self.inventory_id.date
        res['price_unit'] = self.product_value / qty
        return res


    @api.one
    @api.depends('location_id', 'product_id', 'package_id', 'product_uom_id', 'company_id', 'prod_lot_id', 'partner_id')
    def _compute_theoretical_qty(self):
        if not self.product_id:
            self.theoretical_qty = 0
            return
        # theoretical_qty = self.product_id.get_theoretical_quantity(
        #     self.product_id.id,
        #     self.location_id.id,
        #     lot_id=self.prod_lot_id.id,
        #     package_id=self.package_id.id,
        #     owner_id=self.partner_id.id,
        #     to_uom=self.product_uom_id.id,
        # )
        # self.theoretical_qty = theoretical_qty
        #
        locations = [self.location_id.id]
        domain = " location_id in %s AND state = 'done'"
        # domain = ' location_id in %s'
        args = (tuple(locations),)

        vals = []
        Product = self.env['product.product']
        # Empty recordset of products available in stock_quants
        quant_products = self.env['product.product']
        # Empty recordset of products to filter
        products_to_filter = self.env['product.product']

        # case 0: Filter on company
        if self.company_id:
            domain += ' AND company_id = %s'
            args += (self.company_id.id,)

        # case 3: Filter on One product
        if self.product_id:
            domain += ' AND product_id = %s'
            args += (self.product_id.id,)

        if self.inventory_id.date:
            domain += ' AND date_expected BETWEEN %s AND %s'
            date_from = datetime(self.inventory_id.date.year, 1, 1, 0, 0, 0)
            # fiscalyear_from = self.env['account.fiscal.year'].search([
            #     ('company_id', '=', self.id),
            #     ('date_from', '<=', self.date),
            #     ('date_to', '>=', self.date),
            # ], limit=1)
            # if fiscalyear_from:
            #     date_from = fiscalyear_from.date_from
            # else:
            #     raise UserError(_("Please configure a fiscalyear"))
            args += (date_from.strftime('%Y-%m-%d'), self.inventory_id.date.strftime('%Y-%m-%d'),)

        domain_in = domain.replace('location_id', 'location_dest_id')
        args += args
        self.env.cr.execute("""
                select 
                    product_id,
                    sum(product_qty) as product_qty,
                    sum(value) as value,
                    location_id
    
                from (
                    SELECT 
                        product_id, 
                        SUM(-product_qty) as product_qty, 
                        SUM(CASE 
                            WHEN stock_picking_type.code != 'outgoing' THEN -(value + landed_cost_value) ELSE -value
                            END ) as value,
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
        for product_data in res:
            # replace the None the dictionary by False, because falsy values are tested later on
            for void_field in [item[0] for item in product_data.items() if item[1] is None]:
                product_data[void_field] = False
            self.theoretical_qty = product_data['product_qty']
            # self.product_value = product_data['value']
            self.product_theoretical_value = product_data['value']