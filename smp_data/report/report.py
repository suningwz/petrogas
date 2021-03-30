# -*- coding: utf-8 -*-

from odoo import api, models

# class SalePickingReport(models.AbstractModel):
#     _name = 'report.smp_inventory.smp_picking_report'
#
#     @api.model
#     def _get_report_values(self, docids, data=None):
#         report_obj = self.env['ir.actions.report']
#         report = report_obj._get_report_from_name('smp_inventory.smp_picking_report')
#         docargs = {
#             'doc_ids': docids,
#             'doc_model': report.model,
#             'docs': self,
#         }
#         return docargs