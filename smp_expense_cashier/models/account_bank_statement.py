# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
import  datetime
from odoo.osv import expression
from odoo.tools import float_is_zero, pycompat
from odoo.tools import float_compare, float_round, float_repr
from odoo.tools.misc import formatLang, format_date
from odoo.exceptions import UserError, ValidationError
from _collections import defaultdict
import xlsxwriter as xls
import io, base64
import pandas as pd


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    is_bank_statement = fields.Boolean(string='Génerate a bank statement line')


class AccountBankStatement(models.Model):
    _inherit = 'account.bank.statement'

    state = fields.Selection([('draft', 'Draft'),('open', 'Open'), ('confirm', 'Closed')], string='Status', required=True, readonly=True, copy=False, default='draft')

    # state = fields.Selection(selection_add=[('draft', 'Draft')], default='draft')

    @api.constrains('journal_id','state')
    def check_unique_draft_bank_statement(self):
        if self.search_count([('journal_id','=',self.journal_id.id),('state','=','open')]) > 1:
            raise ValidationError(_('You must close all previous bank statement concerning the journal %s.') % (self.journal_id.name))
        return True

    @api.model
    def create(self, vals):
        res = super(AccountBankStatement, self).create(vals)
        print(res)
        return res

    @api.multi
    def _get_bank_report(self):

        self.ensure_one()

        res = defaultdict(lambda x:{'Date':None,
                                    'Caisse': None,
                                    'Référence': None,
                                    'Libellé': None,
                                    'Partenaire': None,
                                    'Montant': 0.0,
                                    'Rapport de dépense': None,
                                    'Ecritures Comptables': None,
                                    })
        for line in self.line_ids:
            res[line.id] = {'Date': line.date,
                            'Caisse': self.name,
                            'Référence': line.ref,
                            'Libellé': line.name,
                            'Partenaire': line.partner_id.name,
                            'Montant': line.amount,
                            'Rapport de dépense': line.expense_id.name if line.expense_id else None,
                            'Ecritures Comptables': ', '.join(line.journal_entry_ids.mapped('name')),
                            }
        return res

    def excel_report(self):
        res = self._get_bank_report()
        df = pd.DataFrame.from_dict(res, orient="index")
        non_fichier = "Rapport de caisse.xlsx"
        company = self.env.user.company_id
        logo = base64.decodebytes(company.logo_web)

        # Use a temp filename to keep pandas hap
        # py.
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
            'title': 'Rapport de caisse',
            'author': 'Aly Kane',
            'company': 'DisruptSol',
            'comments': 'Created with Python and XlsxWriter'})
        writer.save()

        file = base64.encodebytes(data_buffer.getvalue())
        # data_buffer.close()

        # workbook.close()
        wizard_id = self.env['report.wizard'].create({'data': file, 'name': non_fichier})

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


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    expense_id = fields.Many2one('hr.expense', 'expense_id')
