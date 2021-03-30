# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _, exceptions, tools
from datetime import date,timedelta
from odoo.exceptions import UserError, ValidationError


class UoMCategory(models.Model):
    _inherit = 'uom.category'

    measure_type = fields.Selection(selection_add=[('oil', 'oil')])

class UoM(models.Model):
    _inherit = 'uom.uom'

    @api.multi
    def _compute_quantity(self, qty, to_unit, round=True, rounding_method='UP', raise_if_failure=True):
        """ Convert the given quantity from the current UoM `self` into a given one
            :param qty: the quantity to convert
            :param to_unit: the destination UoM record (uom.uom)
            :param raise_if_failure: only if the conversion is not possible
                - if true, raise an exception if the conversion is not possible (different UoM category),
                - otherwise, return the initial quantity
        """
        if not self:
            return qty
        self.ensure_one()
        if self.category_id.id != to_unit.category_id.id:
            inter_uom_factor = self.env.context.get('inter_uom_factor', False)
            if inter_uom_factor:
                ref_category_id = self.env.context.get('ref_category_id', False)
                if ref_category_id == self.category_id.id:
                    return qty / inter_uom_factor
                return qty * inter_uom_factor
            if raise_if_failure:
                raise UserError(_('The unit of measure %s defined on the order line doesn\'t belong to the same category than the unit of measure %s defined on the product. Please correct the unit of measure defined on the order line or on the product, they should belong to the same category.') % (self.name, to_unit.name))
            else:
                return qty
        amount = qty / self.factor
        if to_unit:
            amount = amount * to_unit.factor
            if round:
                amount = tools.float_round(amount, precision_rounding=to_unit.rounding, rounding_method=rounding_method)
        return amount

#     def _compute_quantity(self, qty, to_unit, round=True, rounding_method='UP', raise_if_failure=True):
#         """ Convert the given quantity from the current UoM `self` into a given one
#             :param qty: the quantity to convert
#             :param to_unit: the destination UoM record (uom.uom)
#             :param raise_if_failure: only if the conversion is not possible
#                 - if true, raise an exception if the conversion is not possible (different UoM category),
#                 - otherwise, return the initial quantity
#         """
#         if not self:
#             return qty
#         self.ensure_one()
#         if self.category_id.id != to_unit.category_id.id:
#             if raise_if_failure:
#                 raise UserError(_('The unit of measure %s defined on the order line doesn\'t belong to the same category than the unit of measure %s defined on the product. Please correct the unit of measure defined on the order line or on the product, they should belong to the same category.') % (self.name, to_unit.name))
#             else:
#                 return qty
#         amount = qty / self.factor
#         if to_unit:
#             amount = amount * to_unit.factor
#             if round:
#                 amount = tools.float_round(amount, precision_rounding=to_unit.rounding, rounding_method=rounding_method)
#         return amount
#
