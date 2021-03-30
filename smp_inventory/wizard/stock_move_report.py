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

class StockMoveAnalysis(models.Model):
    _name = 'stock.move.analysis'
    _description = 'Analyse des stocks'
    _auto = False

    date = fields.Date("Date")
    category = fields.Char("Catégorie d'opération",readonly=True)
    picking_type_id = fields.Many2one('stock.picking.type', "Type d'Operation",readonly=True)
    product_id = fields.Many2one('product.product', 'Product',readonly=True)
    location_id = fields.Many2one('stock.location', 'Emplacement', readonly=True)
    product_qty =  fields.Float("Quantité",readonly=True)
    price_unit =  fields.Float("Prix Unitaire",readonly=True)
    value = fields.Float("Coût hors frais d'approches",readonly=True)
    charge_value = fields.Float("Frais d'approche",readonly=True)
    total_value = fields.Float("Valeur En stock",readonly=True)
    charges_not_in_stock = fields.Float("Autres Charges",readonly=True)

    @api.model_cr
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)

        query = """
        CREATE OR REPLACE VIEW stock_move_analysis AS (
        Select             
                sm.id as id,
                sm.date_expected as date,
                CASE 
                    when spt.code = 'outgoing' then 'Clients'
                    when spt.code = 'incoming' then 'Fournisseurs'
                    else 'Interne'
                END as category,
                sm.picking_type_id as picking_type_id,
                sm.product_id as product_id,
                sm.location_id as location_id,
                -1*sm.product_qty as product_qty,
                -1*sm.price_unit as price_unit,
                -1*sm.value as value,
                CASE 
                    when spt.code = 'outgoing' then 0.0
                    else -1*sm.landed_cost_value
                END as charge_value,
                CASE 
                    when spt.code = 'outgoing' then -1*sm.value
                    else -1*sm.value + -1*sm.landed_cost_value
                END as total_value,
                CASE 
                    when spt.code = 'outgoing' then -1*sm.landed_cost_value
                    else 0.0
                END as charges_not_in_stock
            from stock_move as sm
                left join stock_picking_type as spt on spt.id = sm.picking_type_id
            where location_id in  ( select id from stock_location where usage like 'internal') 
                and sm.state='done'
            UNION
            Select             
                sm.id as id,
                sm.date_expected as date,
                CASE 
                    when spt.code = 'outgoing' then 'Clients'
                    when spt.code = 'incoming' then 'Fournisseurs'
                    else 'Interne'
                END as category,
                sm.picking_type_id as picking_type_id,
                sm.product_id as product_id,
                sm.location_dest_id as location_id,
                sm.product_qty as product_qty,
                sm.price_unit as price_unit,
                sm.value as value,
                CASE 
                    when spt.code = 'outgoing' then 0.0
                    else sm.landed_cost_value
                END as charge_value,
                CASE 
                    when spt.code = 'outgoing' then sm.value
                    else sm.value + sm.landed_cost_value
                END as total_value,
                CASE 
                    when spt.code = 'outgoing' then sm.landed_cost_value
                    else 0.0
                END as charges_not_in_stock
            from stock_move as sm
                left join stock_picking_type as spt on spt.id = sm.picking_type_id
            where location_dest_id in  ( select id from stock_location where usage like 'internal') 
                and sm.state='done'     
        )
        """
        self.env.cr.execute(query)


class StockMoveReport(models.TransientModel):
    _name = 'stock.move.report'
    _description = 'Reporting des mouvement de stocks'

    start_date = fields.Date(string="Date de départ",default=fields.Date.today())
    end_date = fields.Date(string="Date de fin",default=fields.Date.today())
    product_ids = fields.Many2many('product.product', domain=[('type', '=', 'product')])
    picking_type_ids = fields.Many2many('stock.picking.type')
    location_ids = fields.Many2many('stock.location')

    @api.multi
    def _get_domain(self):
        self.ensure_one()
        domain = [('date_expected','>=',self.start_date), ('date_expected','<=',self.end_date), ('state','=','done')]

        if self.product_ids:
            product_ids = self.product_ids
        else:
            product_tmpls_ids = self.env['product.template'].search([('type', '=', 'product')])
            product_ids = self.product_ids.search([('product_tmpl_id','in',product_tmpls_ids.ids)])

        domain.append(('product_id', 'in', product_ids.ids))

        if self.picking_type_ids:
            picking_type_ids = self.picking_type_ids
        else:
            picking_type_ids = self.picking_type_ids.search([])

        domain += [('picking_type_id', 'in', picking_type_ids.ids)]

        if self.location_ids:
            location_ids = self.location_ids
        else:
            location_ids = self.env['stock.location'].search([('usage', '=', 'internal')])

        domain += ['|', ('location_id', 'in', location_ids.ids), ('location_dest_id', 'in', location_ids.ids)]

        return domain

    @api.multi
    def _get_stock_move_ids(self):
        domain = self._get_domain()
        stock_move_ids = self.env['stock.move'].search(domain)

        res = defaultdict(lambda: {'qty': 0.0, 'charges':0.0})
        for sm_id in stock_move_ids:
            if sm_id._is_out():
                sens = 'out'

            elif sm_id._is_in():
                sens = 'in'
            elif sm_id._is_scrapped():
                sens = 'scrapped'
            else:
                sens = 'UNKNOW'

            sign = -1 if sens == 'out' else 1

            sm_dict = {
                'id': sm_id.id,
                'sens': sens,
                'date': sm_id.date_expected,
                'picking_type': sm_id.picking_type_id.name,
                'picking_type_id': sm_id.picking_type_id.code,
                'origin': sm_id.origin,
                'reference': sm_id.reference,
                'location_id': sm_id.location_dest_id.name if sens=='in' else sm_id.location_id.name,
                'product_id': sm_id.product_id.product_tmpl_id.name,
                'qty': sign * sm_id.product_qty,
                'cost_unit':sm_id.price_unit,
                'value': sm_id.value,
                'charges': sm_id.landed_cost_value,
            }
            for k, v in sm_dict.items():
                res[sm_id.id][k] = v
        return res

    @api.multi
    def _get_initial_value(self):

        start_date = self.start_date.strftime("%Y-%m-%d")
        end_date = date(self.start_date.year, 1, 1).strftime("%Y-%m-%d")

        if self.product_ids:
            product_ids = self.product_ids
        else:
            product_ids = self.product_ids.search([('type', '=', 'product')])

        if self.picking_type_ids:
            picking_type_ids = self.picking_type_ids
        else:
            picking_type_ids = self.picking_type_ids.search([])

        if self.location_ids:
            location_ids = self.location_ids
        else:
            location_ids = self.location_ids.search([('usage', '=', 'internal')])

        select_query= """
            SELECT product_id,location_dest_id, sum(product_qty), sum(value), sum(landed_cost_value)
            FROM stock_move
            where
                product_id in %s
                and location_dest_id in %s
                and date_expected >= '%s'
                and date_expected <= '%s'

            GROUP BY
                product_id,
                location_dest_id
            """
        self.env.cr.execute(select_query % (tuple(product_ids.ids), tuple(location_ids.ids), start_date, end_date))
        init_sm_origin = self.env.cr.dictfetchall()

        select_query= """
            SELECT product_id,location_dest_id, sum(product_qty), sum(value), sum(landed_cost_value)
            FROM stock_move
            where
                product_id in %s
                and location_dest_id in %s
                and date_expected >= '%s'
                and date_expected <= '%s'

            GROUP BY
                product_id,
                location_dest_id
            """
        self.env.cr.execute(select_query % (tuple(product_ids.ids), tuple(location_ids.ids), start_date, end_date))
        init_sm_dest = self.env.cr.dictfetchall()

        print('init_sm_dest')

    @api.multi
    def process(self):
        self.ensure_one()


        non_fichier = "Reporting des stocks.xlsx"
        # Use a temp filename to keep pandas happy.
        writer = pd.ExcelWriter(non_fichier, engine='xlsxwriter')

        # Set the filename/file handle in the xlsxwriter.workbook object.
        data_buffer = io.BytesIO()
        writer.book.filename = data_buffer

        company = self.env.user.company_id
        logo = base64.decodebytes(company.logo_web)

        # self._get_initial_value()
        res = self._get_stock_move_ids()
        df = pd.DataFrame.from_dict(res, orient="index")
        del res
        translate_dict = {
            'id': 'ID',
            'date': 'Date',
            'sens': 'Sens',
            'picking_type': "Opération",
            'picking_type_id': "Type d'opération" ,
            'origin': "Origin",
            'reference': "Reférence",
            'location_id': "Location",
            'product_id': "Article",
            'qty': "Quantité",
            'cost_unit': "Coût Unitaire",
            'value': "Valeur Stock",
            'charges': "Valeur Charge",
        }

        sens_column = [k for k, v in translate_dict.items()]
        df = df[sens_column]
        df.rename(columns=translate_dict, inplace=True)

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
            'title': 'Reporting Des Stocks',
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
