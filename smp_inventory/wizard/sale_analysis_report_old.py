# -*- coding: utf-8 -*-
# © 2019 DisruptSol
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, api, fields, tools, _
from odoo.exceptions import ValidationError
from _collections import defaultdict
from datetime import  date
import xlsxwriter as xls
import io, base64
import pandas as pd

class SaleAnalysisReport(models.TransientModel):
    _name = 'sale.analysis.report'
    _description = 'Reporting des ventes'

    start_date = fields.Date(string="Date de départ",default=fields.Date.today())
    end_date = fields.Date(string="Date de fin",default=fields.Date.today())
    partner_ids =fields.Many2many('res.partner')
    # product_ids = fields.Many2many('product.product', domain=[('type', '=', 'product')])
    # picking_type_ids = fields.Many2many('stock.picking.type')
    # location_ids = fields.Many2many('stock.location')

    @api.multi
    def _get_domain(self):
        self.ensure_one()
        domain=[]
        if self.start_date:
            domain += [('date_order','>=',self.start_date)]

        if self.end_date:
            domain += [('date_order','<=',self.end_date)]

        if self.partner_ids:
            domain += [('partner_id', 'in', self.partner_ids.ids)]
        return domain

    def _get_sale_order(self):
        self.ensure_one()
        domain = self._get_domain()
        so_ids = self.env['sale.order'].search(domain)
        # ai_ids = self.env['account_invoice'].search(domain)
        # sp_ids = self.env['stock.picking'].search(domain)
        # sm_ids = self.env['stock.move'].search(domain)
        res = defaultdict(lambda x:{'Date':None,
                                    'Bon de Commande':None,
                                    'Régime': None,
                                    'Dépôt': None,
                                    'Facture':None,
                                    'Bon de Livraison':None,
                                    'Article':None,
                                    'Quantité':0.0,
                                    'P.U':0.0,
                                    'Total':0.0 ,
                                    })
        for so in so_ids.filtered(lambda x: x.state == 'sale').sorted(lambda x: x.date_order):
            for line in so.order_line:
                res[line.id] = {
                    'Date': so.date_order,
                    'Régime': so.regime_id.name if so.regime_id else None,
                    'Dépôt': so.location_id.name if so.location_id else None,
                    'Bon de Commande': so.name,
                    'Facture': ', '.join(line.invoice_lines.mapped('name')),
                    'Bon de Livraison': ', '.join(line.move_ids.mapped('name')),
                    'Article': line.product_id.product_tmpl_id.name,
                    'Quantité Commandé': line.product_uom_qty,
                    'Quantité Livré': line.qty_delivered,
                    'Quantité Facturé': line.qty_invoiced,
                    'P.U': line.price_unit,
                    'Total Commandé': line.price_unit * line.product_uom_qty,
                    'Total Livré': line.price_unit * line.qty_delivered,
                    'Total Facturé': line.price_unit * line.qty_invoiced,
                }
        return res

    def excel_write(self):
        res = self._get_sale_order()
        df = pd.DataFrame.from_dict(res,orient="index")
        wb_name = "Reporting des ventes.xlsx"
        writer = pd.ExcelWriter('pandas_simple.xlsx', engine='xlsxwriter')
        data_bytes = io.BytesIO()
        wb = xls.Workbook(data_bytes,{'in_memory': True})
        ws = wb.add_worksheet('Bon de commande')

        row = 0
        col = 0

        "Table Header"
        # for key in res

        for k, v in res.items():
            for item in v:
                ws.write(row + list(res.keys()).index(k) , col + list(v.keys()).index(item), v[item])


        file = base64.encodestring(data_bytes.getvalue())
        data_bytes.close()

        wb.close()
        wizard_id = self.env['report.wizard'].create({'data':file, 'name':wb_name})

        return {
            'view_mode': 'form',
            'view_id': self.env.ref('smp_inventory.report_wizard_form').id,
            'res_id': wizard_id.id,
            'res_model': 'report.wizard',
            'view_type': 'form',
            'type': 'ir.actions.act_window',
            # 'context': self._context,
            'target': 'new',
        }


    @api.multi
    def process(self):
        self.ensure_one()
        res = self.excel_write()
        return res


# class SaleAnalysis(models.Model):
#     _name = 'sale.analysis'
#     _description = 'Analyse des ventes'
#     _auto = False
#
#     date = fields.Date("Date")
#     product_id = fields.Many2one('product.product', 'Article',readonly=True)
#     location_id = fields.Many2one('stock.location', 'Emplacement', readonly=True)
#     product_qty =  fields.Float("Quantité",readonly=True)
#     price_unit =  fields.Float("Prix Unitaire",readonly=True)
#     value = fields.Float("Valeur Hors Charges",readonly=True)
#     charge_value = fields.Float("Valeur des Charges",readonly=True)
#     total_value = fields.Float("Valeur Total",readonly=True)
#
#     @api.model_cr
#     def init(self):
#         tools.drop_view_if_exists(self.env.cr, self._table)
#
#         query = """
#         CREATE OR REPLACE VIEW stock_move_analysis AS (
#         Select
#                 sm.id as id,
#                 sm.date as date,
#                 CASE
#                     when spt.code = 'outgoing' then 'Clients'
#                     when spt.code = 'incoming' then 'Fournisseurs'
#                     else 'Interne'
#                 END as category,
#                 sm.picking_type_id as picking_type_id,
#                 sm.product_id as product_id,
#                 sm.location_id as location_id,
#                 -1*sm.product_qty as product_qty,
#                 sm.price_unit as price_unit,
#                 sm.value as value,
#                 sm.landed_cost_value as  charge_value,
#                 sm.value + sm.landed_cost_value as total_value
#             from stock_move as sm
#                 left join stock_picking_type as spt on spt.id = sm.picking_type_id
#             where location_id in  ( select id from stock_location where usage like 'internal')
#                 and sm.state='done'
#             UNION
#             Select
#                 sm.id as id,
#                 sm.date as date,
#                 CASE
#                     when spt.code = 'outgoing' then 'Clients'
#                     when spt.code = 'incoming' then 'Fournisseurs'
#                     else 'Interne'
#                 END as category,
#                 sm.picking_type_id as picking_type_id,
#                 sm.product_id as product_id,
#                 sm.location_dest_id as location_id,
#                 sm.product_qty as product_qty,
#                 sm.price_unit as price_unit,
#                 sm.value as value,
#                 sm.landed_cost_value as  charge_value,
#                 sm.value + sm.landed_cost_value as total_value
#             from stock_move as sm
#                 left join stock_picking_type as spt on spt.id = sm.picking_type_id
#             where location_dest_id in  ( select id from stock_location where usage like 'internal')
#                 and sm.state='done'
#         )
#         """
#         self.env.cr.execute(query)


