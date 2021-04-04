# # -*- coding: utf-8 -*-
# from datetime import date,timedelta
# from odoo import models, fields, api, exceptions, _
# from odoo.exceptions import UserError, ValidationError
# from odoo.tools import float_is_zero, float_compare
# from odoo.addons import decimal_precision as dp
#
#
# class SaleOrderLine(models.Model):
#     _inherit = 'sale.order.line'
#
#     @api.onchange
#     def get_transport_cost(self):
# #
# #