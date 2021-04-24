# -*- coding: utf-8 -*-
from datetime import date,timedelta
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    unique_picking = fields.Boolean("Bon de livraison Unique", help=""" Si cochez généra un bon de livraison séparé 
    pour ce produit à chaque fois que ce produit se trouvera sur un bon de comande. """)
    sale_price_ids = fields.One2many('product.sale.price', 'product_id',
                                     string= "Structured Product Sale Price",
                                     domain=[('end_date', '=', None),('state','=', 'done')])


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.multi
    def price_compute(self, price_type, uom=False, currency=False, company=False):
        # TDE FIXME: delegate to template or not ? fields are reencoded here ...
        # compatibility about context keys used a bit everywhere in the code
        if not uom and self._context.get('uom'):
            uom = self.env['uom.uom'].browse(self._context['uom'])
        if not currency and self._context.get('currency'):
            currency = self.env['res.currency'].browse(self._context['currency'])

        products = self
        if price_type == 'standard_price':
            # standard_price field can only be seen by users in base.group_user
            # Thus, in order to compute the sale price from the cost for users not in this group
            # We fetch the standard price as the superuser
            products = self.with_context(force_company=company and company.id or self._context.get('force_company', self.env.user.company_id.id)).sudo()

        prices = dict.fromkeys(self.ids, 0.0)
        for product in products:
            # start_date = product._context['date']
            start_date = product._context.get('date', False)
            location_id = product._context.get('location_id', False)
            regime_id = product._context.get('regime_id', False)
            partner_id = product._context.get('partner', False)
            transport_type = product._context.get('transport_type', False)

            if location_id:
                location_id = self.env['stock.location'].search([('id', '=', location_id)])[0]
            if regime_id:
                regime_id = self.env['regime.douanier'].search([('id', '=', regime_id)])[0]
            if transport_type:
                transport_type = self.env['transport.picking.type'].search([('id', '=', transport_type)])[0]
            # if partner_id:
            #     partner_id = self.env['regime.douanier'].search([('id', '=', partner_id)])[0]

            # Récupère le prix de la matrice de prix structurelle.
            if all([product.apply_price_structure, start_date, location_id, regime_id]):
                prices[product.id] = self.env['product.sale.price'].get_specific_records(start_date, product, location_id, regime_id).value
            else:
                prices[product.id] = product[price_type] or 0.0

            if transport_type and transport_type.charge.id == product.id:
                transport_cost_id = self.env['transport.picking'].get_transport_cost_from_sale_order_line(transport_type, location_id, partner_id)
                prices[product.id] = transport_cost_id and transport_cost_id.value or (product[price_type] or 0.0)

            if price_type == 'list_price':
                prices[product.id] += product.price_extra
                # we need to add the price from the attributes that do not generate variants
                # (see field product.attribute create_variant)
                if self._context.get('no_variant_attributes_price_extra'):
                    # we have a list of price_extra that comes from the attribute values, we need to sum all that
                    prices[product.id] += sum(self._context.get('no_variant_attributes_price_extra'))

            if uom:
                prices[product.id] = product.uom_id._compute_price(prices[product.id], uom)

            # Convert from current user company currency to asked one
            # This is right cause a field cannot be in more than one currency
            if currency:
                prices[product.id] = product.currency_id._convert(
                    prices[product.id], currency, product.company_id, fields.Date.today())

        return prices