# -*- coding: utf-8 -*-
from datetime import date,timedelta
from odoo import models, fields, api, exceptions, _, tools
from  odoo.exceptions import ValidationError
from odoo.addons import decimal_precision as dp
from odoo.tools.float_utils import float_compare, float_round, float_is_zero



class ProductTemplate(models.Model):
    _inherit = 'product.template'

    apply_price_structure = fields.Boolean("Price Structure", help="""Sale Price and cost landing depend of a price structure""")
    # type = fields.Selection(selection_add=[('asset', 'Asset')])
    property_stock_account_valuation = fields.Many2one(
        'account.account', 'Stock Valuation Account', company_dependent=True,
        domain=[('deprecated', '=', False)],
        help="When real-time inventory valuation is enabled on a product,"
             " this account will hold the current value of the products.",)
#     TODO: Rajouter compte de transit
    property_stock_account_transit = fields.Many2one(
        'account.account', 'Stock Transit Account', company_dependent=True,
        domain=[('deprecated', '=', False)],
        help="Compte de transit utliser lors des transferts.",)
#     TODO: Rajouter compte d'inventaire
    property_stock_account_inventory = fields.Many2one(
        'account.account', 'Stock Inventory Account', company_dependent=True,
        domain=[('deprecated', '=', False)],
        help="Compte d'inventaire de stock",)
#     TODO: Rajouter compte de perte
    property_stock_account_loss = fields.Many2one(
        'account.account', 'Stock Loss Account', company_dependent=True,
        domain=[('deprecated', '=', False)],
        help="Compte de perte de stock.",)

    is_uom_inter_category = fields.Boolean("The measurement unit categories are different")
    inter_uom_factor = fields.Float(string='Conversion Factor', digits=(0, 6))

    _sql_constraints = [('unique_name', 'UNIQUE(name)', 'The name must be unique'),
                        ('unique_default_code', 'UNIQUE(default_code)', 'The code must be unique')]

    @api.constrains('uom_id', 'uom_po_id')
    def _check_uom(self):
        if any(template.uom_id and template.uom_po_id and template.uom_id.category_id != template.uom_po_id.category_id for template in self):
            precision = max(self.uom_id.rounding, self.uom_po_id.rounding)
            if tools.float_is_zero(self.inter_uom_factor, precision_digits=precision):
                raise ValidationError(_('The default Unit of Measure and the purchase Unit of Measure must be in the same category.'))
        return True

    @api.multi
    def _get_product_accounts(self):
        """ Add the stock accounts related to product to the result of super()
        @return: dictionary which contains information regarding stock accounts and super (income+expense accounts)
        """
        accounts = super(ProductTemplate, self)._get_product_accounts()
        # res = self._get_asset_accounts()
        accounts.update({
            # 'stock_input': res['stock_input'] or self.property_stock_account_input or self.categ_id.property_stock_account_input_categ_id,
            # 'stock_output': res['stock_output'] or self.property_stock_account_output or self.categ_id.property_stock_account_output_categ_id,
            'stock_valuation': self.property_stock_account_valuation or self.categ_id.property_stock_valuation_account_id or False,
            'stock_transit': self.property_stock_account_transit or False,
            'stock_loss': self.property_stock_account_loss or False,
        })
        return accounts

    @api.onchange('uom_id','uom_po_id')
    def _onchange_uom_po_id(self):
        self.ensure_one()
        if self.uom_id and self.uom_po_id:
            self.update_inter_uom_category_visibility()

    @api.onchange('uom_id','uom_po_id')
    def update_inter_uom_category_visibility(self):
        if self.uom_id.category_id == self.uom_po_id.category_id:
            self.is_uom_inter_category = False
            self.inter_uom_factor = None
        else:
            self.is_uom_inter_category = True


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.multi
    def _select_seller(self, partner_id=False, quantity=0.0, date=None, uom_id=False, params=False):
        self.ensure_one()
        if date is None:
            date = fields.Date.context_today(self)
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')

        res = self.env['product.supplierinfo']
        sellers = self._prepare_sellers(params)
        if self.env.context.get('force_company'):
            sellers = sellers.filtered(lambda s: not s.company_id or s.company_id.id == self.env.context['force_company'])
        for seller in sellers:
            # Set quantity in UoM of seller
            quantity_uom_seller = quantity
            if quantity_uom_seller and uom_id and uom_id != seller.product_uom:
                quantity_uom_seller = uom_id.with_context(inter_uom_factor=self.inter_uom_factor)._compute_quantity(quantity_uom_seller, seller.product_uom)

            if seller.date_start and seller.date_start > date:
                continue
            if seller.date_end and seller.date_end < date:
                continue
            if partner_id and seller.name not in [partner_id, partner_id.parent_id]:
                continue
            if float_compare(quantity_uom_seller, seller.min_qty, precision_digits=precision) == -1:
                continue
            if seller.product_id and seller.product_id != self:
                continue

            res |= seller
            break
        return res