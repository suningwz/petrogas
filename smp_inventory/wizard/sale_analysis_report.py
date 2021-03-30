# -*- coding: utf-8 -*-
# © 2019 DisruptSol

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
    sale_team_ids =fields.Many2many('crm.team')
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

        if self.sale_team_ids:
            domain += [('team_id', 'in', self.sale_team_ids.ids)]

        return domain

    def _get_sale_order(self):
        self.ensure_one()
        domain = self._get_domain()
        so_ids = self.env['sale.order'].search(domain)
        # ai_ids = self.env['account_invoice'].search(domain)
        # sp_ids = self.env['stock.picking'].search(domain)
        # sm_ids = self.env['stock.move'].search(domain)
        res = defaultdict(lambda x:{
                                    'Team':None,
                                    'Date':None,
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
            # facture = line.invoice_lines.mapped

            for line in so.order_line:
                payments = []
                factures = []
                if line.invoice_lines and line.invoice_lines.mapped('invoice_id'):
                    factures = line.invoice_lines.mapped('invoice_id').mapped('number')
                    if line.invoice_lines.mapped('invoice_id').mapped('payment_group_ids'):
                        # if line.invoice_lines.mapped('invoice_id').mapped('payment_move_line_ids'):
                        # payments = line.invoice_lines.mapped('invoice_id').mapped('payment_ids').mapped('communication')
                        # payments = line.invoice_lines.mapped('invoice_id').mapped('payment_move_line_ids').mapped('move_id').mapped('ref')
                        payments_ids = line.invoice_lines.mapped('invoice_id').mapped('payment_group_ids').mapped('payment_ids')
                        for pay in payments_ids:
                            payments.append(pay.journal_id.code+':'+pay.communication if pay.communication else pay.journal_id.code)
                        # payments_amount = line.invoice_lines.mapped('invoice_id').mapped('payment_ids').mapped('communication')
                    # payment = line.invoice_lines.mapped('payment_ids').mapped('communication')
                cost = sum(line.move_ids.filtered(lambda x: x._is_out()).mapped('value')) - sum(line.move_ids.filtered(lambda x: x._is_in()).mapped('value'))
                cost_landing = sum(line.move_ids.filtered(lambda x: x._is_out()).mapped('landed_cost_value')) - sum(line.move_ids.filtered(lambda x: x._is_in()).mapped('landed_cost_value'))
                res[line.id] = {
                    'Team': so.team_id.name,
                    'Date': so.date_order,
                    'Client': so.partner_id.code +' / ' + so.partner_id.name,
                    'Régime': so.regime_id.code if so.regime_id else None,
                    'Dépôt': so.location_id.name if so.location_id else None,
                    'Bon de Commande': so.name,
                    'Facture': factures,
                    'Bon de Livraison': ', '.join(line.move_ids.mapped('reference')) if line.move_ids else '',
                    'Article': line.product_id.product_tmpl_id.name,
                    'Quantité Commandé': line.product_uom_qty,
                    'Quantité Livré': line.qty_delivered,
                    'Quantité Facturé': line.qty_invoiced,
                    'P.U': line.price_unit,
                    'Total Commandé': line.price_unit * line.product_uom_qty,
                    'Total Livré': line.price_unit * line.qty_delivered,
                    'Total Facturé': line.price_unit * line.qty_invoiced,
                    'Réglement': ', '.join(payments),
                    'Coût du stock': cost,
                    'Frais de vente': cost_landing,
                    'Marge sur frais variable': line.price_unit * line.qty_invoiced - (cost + cost_landing),
                }
        return res

    def excel_write(self):
        res = self._get_sale_order()
        df = pd.DataFrame.from_dict(res, orient="index")
        non_fichier = "Reporting des ventes.xlsx"
        company = self.env.user.company_id
        logo = base64.decodebytes(company.logo_web)

        # Use a temp filename to keep pandas happy.
        writer = pd.ExcelWriter(non_fichier, engine='xlsxwriter')

        # Set the filename/file handle in the xlsxwriter.workbook object.
        data_buffer = io.BytesIO()
        writer.book.filename = data_buffer

        # Write the data frame to the StringIO object.
        df.to_excel(writer, index=False, sheet_name=non_fichier)
        worksheet_table_header = writer.sheets[non_fichier]
        end_row = len(df.index)
        end_column = len(df.columns)-1
        cell_range = xls.utility.xl_range(0, 0, end_row, end_column)
        header = [{'header': di} for di in df.columns.tolist()]
        worksheet_table_header.add_table(cell_range, {'header_row': True, 'columns': header})

        workbook = writer.book
        workbook.set_properties({
            'title': 'Reporting Des Ventes',
            'author': 'Aly Kane',
            'company': 'DisruptSol',
            'comments': 'Created with Python and XlsxWriter'})
        writer.save()

        file = base64.encodebytes(data_buffer.getvalue())
        # data_buffer.close()

        # workbook.close()
        wizard_id = self.env['report.wizard'].create({'data':file, 'name':non_fichier})

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



        # wb = xls.Workbook(data_buffer,{'in_memory': True})
        # ws = wb.add_worksheet('Bon de commande')

        # row = 0
        # col = 0
        #
        # "Table Header"
        # # for key in res
        #
        # for k, v in res.items():
        #     for item in v:
        #         ws.write(row + list(res.keys()).index(k) , col + list(v.keys()).index(item), v[item])

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


