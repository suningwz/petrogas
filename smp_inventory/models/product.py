# -*- coding: utf-8 -*-
from datetime import date,timedelta
from odoo import models, fields, api, exceptions, _, tools
from  odoo.exceptions import ValidationError
from odoo.addons import decimal_precision as dp


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
