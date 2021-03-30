# -*- coding: utf-8 -*-

import calendar
# from builtins import __generator

import odoo.addons.decimal_precision as dp
from datetime import datetime, timedelta
from odoo import api, models, fields, _, exceptions
import  pandas as pd
import base64,io
from resizeimage import resizeimage
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT
from odoo.exceptions import AccessError, UserError
import logging
_logger = logging.getLogger(__name__)

try:
    import xlsxwriter
except ImportError:
    _logger.debug('Can not import xlsxwriter`.')


D_LEDGER = {'general': {'name': _('General Ledger'),
                        'group_by': 'account_id',
                        'model': 'account.account',
                        'short': 'code',
                        'field': ['code', 'name'],
                        },
            'partner': {'name': _('Partner Ledger'),
                        'group_by': 'partner_id',
                        'model': 'res.partner',
                        'short': 'name',
                        'field': ['code', 'name'],
                        },
            'journal': {'name': _('Journal Ledger'),
                        'group_by': 'journal_id',
                        'model': 'account.journal',
                        'short': 'code',
                        'field': ['code', 'name'],
                        },
            'open': {'name': _('Open Ledger'),
                     'group_by': 'account_id',
                     'model': 'account.account',
                     'short': 'code',
                     'field': ['code', 'name'],
                     },
            'aged': {'name': _('Aged Balance'),
                     'group_by': 'partner_id',
                     'model': 'res.partner',
                     'short': 'name',
                     'field': ['code', 'name'],
                     },
            'analytic': {'name': _('Analytic Ledger'),
                         'group_by': 'analytic_account_id',
                         'model': 'account.analytic.account',
                         'short': 'name',
                         'field': ['code', 'name'],
                         },

            }

TRANSALE_DICT = {
    'account_id': _('Account'),
    'partner_id': _('Partner'),
    'analytic_id': _('Analytic Account'),
    'journal_id': _('Journal'),
    'T_0_30': _('0-30'),
    'T_30_60': _('30-60'),
    'T_90_120': _('30-60'),
}

ROW_TABLE_START, COL_TABLE_START = 6, 0


class AccountingReportWizard(models.TransientModel):
    _name = 'accounting.report.wizard'
    _description = 'Accounting Report Wizard'

    @api.model
    def _get_default_fiscal_year(self):
        fiscalyear_id = self.env['account.fiscal.year'].search([], order="date_from desc")
        if not fiscalyear_id:
            if not fiscalyear_id:
                raise exceptions.UserError(_("""'There is no fiscal year defined.\n Please create one from the configuration of the accounting menu.'"""))
        return fiscalyear_id[0]

    fiscalyear_id = fields.Many2one('account.fiscal.year', 'Fiscal Year', required=True, default=lambda self: self.env['account.fiscal.year'].find())
    period_id = fields.Many2one('account.period', string='Accounting Period')
    date_from =fields.Date('Date From',  help='Use to compute initial balance.')
    date_to = fields.Date(string='End Date', help='Use to compute the entrie matched with futur.')
    report_type = fields.Selection([('general', 'General Ledger'),
         ('partner', 'Partner Ledger'),
         ('journal', 'Journal Ledger'),
         ('open', 'Open Ledger'),
         ('aged', 'Aged Balance'),
         ('analytic', 'Analytic Ledger')],string='Type', default='general', required=True, help=' * General Ledger : Journal entries group by account\n'
        ' * Partner Leger : Journal entries group by partner, with only payable/recevable accounts\n'
        ' * Journal Ledger : Journal entries group by journal, without initial balance\n'
        ' * Open Ledger : Openning journal at Start date\n')

    summary = fields.Boolean('Trial Balance', default=False, help=' * Check : generate a trial balance.\n'
                             ' * Uncheck : detail report.\n')
    target_move = fields.Selection([('posted', 'All Posted Entries'),('all', 'All Entries'),
                                    ], string='Target Moves', required=True, default='posted')
    reconciled = fields.Boolean('Reconciled')

    partner_type = fields.Selection([('customer', 'Customers'),('supplier', 'Suppliers'),('employee', 'Employees'),
                                         ('all', 'All Partners Type')], string="Partners Type", required=True, default='all')
    
    account_ids = fields.Many2many('account.account', string='Account')
    partner_ids = fields.Many2many('res.partner', string="Partners in report")
    journal_ids = fields.Many2many('account.journal', string='Journals', required=True,
                                   default=lambda self: self.env['account.journal'].search([('company_id', '=', self.env.user.company_id.id)]),
                                   help='Select journal, for the Open Ledger you need to set all journals.')
    analytic_ids = fields.Many2many('account.analytic.account', string='Analytic Account')

    company_id = fields.Many2one('res.company', string='Company', readonly=True,
                                 default=lambda self: self.env.user.company_id)
    company_currency_id = fields.Many2one('res.currency', related='company_id.currency_id',
                                          string="Company Currency", readonly=True,
                                          help='Utility field to express amount currency', store=True)
    accounting_chart = fields.Many2one('account.account', string='Accounting Chart',
                                       domain=[('user_type_id.type', '=', 'view'), ('parent_id', '=', False)],
                                       default = lambda self: self.env['account.account'].get_accounting_chart()[0])

    # default = lambda self: self.env['account.journal'].search([('company_id', '=', self.env.user.company_id.id)])

    # @api.onchange('fiscalyear_id')
    # def onchange_fiscalyear_id(self):
    #     if self.fiscalyear_id:
    #         self.period_id = False
    #         self.date_from = self.fiscalyear_id.date_from
    #         self.date_to = self.fiscalyear_id.date_to
    #     else:
    #         self.date_from = False
    #         self.date_to = False
    @api.onchange('fiscalyear_id', 'period_id')
    def onchange_period_id(self):
        if self.fiscalyear_id and self.period_id:
            self.date_from = self.period_id.date_from
            self.date_to = self.period_id.date_to
        elif self.fiscalyear_id and not self.period_id:
            self.date_from = self.fiscalyear_id.date_from
            self.date_to = self.fiscalyear_id.date_to
        else:
            self.period_id = False
            self.date_from = False
            self.date_to = False


    def _search_account(self):
        domain = [('deprecated', '=', False), ('company_id', '=', self.company_id.id)]




        if self.report_type in ('partner', 'aged',):
            if self.partner_type == 'supplier':
                acc_type = ('supplier',)
            elif self.partner_type == 'customer':
                acc_type = ('customer',)
            elif self.partner_type == 'employee':
                acc_type = ('employee',)
            else:
                acc_type = ('supplier', 'customer','employee')
            domain.append(('type_third_parties', 'in', acc_type))
            return self.env['account.account'].search(domain)

        elif self.account_ids:
            return self.account_ids
        else:
            return self.env['account.account'].search([])


    def _search_partner(self):
        if self.report_type in ('partner', 'aged'):
            if self.partner_ids:
                return self.partner_ids
            return self.env['res.partner'].search([])

        return []

    def _search_analytic_account(self):
        if self.report_type == 'analytic':
            if self.analytic_account_select_ids:
                return self.analytic_account_select_ids
            else:
                return self.env['account.analytic.account'].search([])
        return False
    
    def get_report_domain(self):
        domain = [('company_id', '=', self.company_id.id)]

        account_id = self.search([])
        if account_id:
            domain += [('account_id', 'in', self._search_account().ids)]

        if self.report_type == 'partner':
            partner_ids = self._search_partner()
            if partner_ids:
                domain += [('partner_id', 'in', partner_ids.ids)]

        if self.report_type == 'journal':
            domain += [('journal_id', 'in', self.journal_ids.ids)]

        if self.report_type == 'open':
            if self.fiscalyear_id.opening_move_ids:
                domain += [('move_id', 'in', self.fiscalyear_id.opening_move_ids.ids)]
            else:
                raise exceptions.UserError(_("""Any opening move has been found."""))


        if self.report_type == 'analytic':
            domain += [('analytic_id', 'in', self._search_analytic_account().ids)]

        if self.report_type == 'aged':
            domain += [('partner_id', 'in', self._search_partner().ids)]

        if self.target_move == 'posted':
            domain += [('move_id.state', '=', 'posted')]



        return domain

    
    def _get_group_key(self):
        group_key = list(set(['account_id'] + [D_LEDGER[self.report_type]['group_by']]))
        return group_key

    def get_aml_grouped_node_object(self):
        group_by = self._get_group_key()

        # domain = group_by.copy()
        domain = [('date', '<=', self.date_to)]
        domain += self.get_report_domain()

        couples = self.env['account.move.line'].read_group(domain=domain, fields=group_by, groupby=group_by, lazy=False)

        return couples, group_by

    def _get_amount(self, aml_grouped=None, group_by=None, date_from=None, date_to=None):
        assert aml_grouped
        assert group_by
        assert date_to

        domain = [(group, '=', aml_grouped[group][0]) for group in group_by]
        domain += [('date', '<=', date_to)]
        if date_from:
            domain += [('date', '>=', date_from)]

        amount_dict = self.env['account.move.line'].read_group(domain=domain, fields=['debit', 'credit', 'balance'],
                                                           groupby=group_by, lazy=False)
        if amount_dict:
            assert len(amount_dict) == 1
            return amount_dict[0]['debit'], amount_dict[0]['credit'], amount_dict[0]['balance']
        return 0, 0, 0

    def _get_aml(self, aml_grouped=None, group_by=None, date_from=None, date_to=None):
        assert aml_grouped
        assert group_by
        assert date_to

        domain = [(group, '=', aml_grouped[group][0]) for group in group_by]
        domain += [('date', '<=', date_to)]
        if date_from:
            domain += [('date', '>=', date_from)]
        res = self.env['account.move.line'].search(domain)
        return res

    def _compute_data(self):

        def _get_general_balance(accounting_chart):
            res = {}
            print(accounting_chart.name, ' **', accounting_chart.child_ids.ids)
            for child in accounting_chart.child_ids:
                if child.child_ids and child.user_type_id.type is 'view':
                    res[child.id] = _get_general_balance(child)
                else:
                    res[child.id] = list(filter(lambda d: d['account_id'] is child.id , aml_grouped_dict))
            return res

        aml_grouped_dict, group_by = self.get_aml_grouped_node_object()

        if not aml_grouped_dict:
            raise exceptions.UserError(_("""No account entries was founded preceding the date %s""") % self.date_to)

        # TODO: order aml_grouped: to do that use account_parent

        for aml_grouped in aml_grouped_dict:

            debit, credit, balance = self._get_amount(aml_grouped, group_by, date_from=None, date_to=self.date_from)
            aml_grouped['initial'] = balance
            debit, credit, balance = self._get_amount(aml_grouped, group_by, date_from=self.date_from, date_to=self.date_to)
            aml_grouped['debit'] = debit
            aml_grouped['credit'] = debit
            aml_grouped['balance'] = balance

            if not self.summary:
                aml_grouped['aml_ids'] = self._get_aml(aml_grouped, group_by, date_from=self.date_from, date_to=self.date_to)

        res = _get_general_balance(self.accounting_chart)

        return aml_grouped_dict, group_by

    # def _compute_data_new(self):
    #     # If summary alors une table
    #
    #     aml_grouped_dict, group_by = self._get_aml_grouped_node_object()
    #
    #     domain = [(key, 'in', [couple[key] for couple in aml_grouped_dict]) for key in group_by]
    #     self.accounting_chart.get_accounting_value(self.date_from, self.date_to)
    #
    #     def _get_general_balance(accounting_chart):
    #         res = {}
    #         print(accounting_chart.name, ' **', accounting_chart.child_ids.ids)
    #         for child in accounting_chart.child_ids:
    #             if child.child_ids and child.user_type_id.type is 'view':
    #                 res[child.id] = _get_general_balance(child)
    #             else:
    #                 res[child.id] = list(filter(lambda d: d['account_id'] is child.id , aml_grouped_dict))
    #         return res
    #
    #     aml_grouped_dict, group_by = self._get_aml_grouped_node_object()
    #     if not aml_grouped_dict:
    #         raise exceptions.UserError(_("""No account entries was founded preceding the date %s""") % self.date_to)
    #
    #     for aml_grouped in aml_grouped_dict:
    #
    #         debit, credit, balance = self._get_amount(aml_grouped, group_by, date_from=None, date_to=self.date_from)
    #         aml_grouped['initial'] = balance
    #         debit, credit, balance = self._get_amount(aml_grouped, group_by, date_from=self.date_from, date_to=self.date_to)
    #         aml_grouped['debit'] = debit
    #         aml_grouped['credit'] = debit
    #         aml_grouped['balance'] = balance
    #
    #         if not self.summary:
    #             aml_grouped['aml_ids'] = self._get_aml(aml_grouped, group_by, date_from=self.date_from, date_to=self.date_to)
    #
    #     res = _get_general_balance(self.accounting_chart)
    #
    #     # If not summary: on doit afficher les détails. Le découpage des table se fera par couple inscrit dans la var group_by
    #     if not self.summary:
    #         if self.report_type == 'view':
    #             print('aged summary report')
    #         else:
    #             for couple in aml_grouped_dict:
    #                 aml_ids = self.env['account.account'].search([couple['domain']])
    #                 couple['aml_ids'] = aml_ids
    #     else:
    #         if self.report_type == 'general':
    #             self.accounting_chart.get_chart_tree_dict_new()
    #         elif self.report_type == 'partner':
    #
    #         elif self.report_type == 'analytic':
    #
    #         elif self.report_type == 'open':
    #
    #         elif self.report_type == 'aged':
    #
    #     return aml_grouped_dict, group_by




    @api.model
    def get_couple_tree_dict(self, couples, group_by):

        # res = [[key for key in group_by] for couple in couples]
        res = [{key: couple[key][0] for key in group_by} for couple in couples]

        d = {}
        d[res]

        return res

    def generated_summary_worksheet(self, sheet,  aml_group=[], group_by=['account_id']):
        assert aml_group
        aa_pool = self.env['account.account']
        aml_pool = self.env['account.move.line']
        fields_to_exclude = ['__count', '__domain']

        # Header de la table:

        # On doit grouper et ordonner les couples selon group by
        for couple in aml_group:
            (couple[key][0] for key in group_by)

        #  on crée les tables selon le groupage et l'ordonnancement



        row, col = 6, 1
        for couple in aml_group:
            domain = [(key, '=', couple[key]) for key in group_by]
            aa = aa_pool.search([('account_id', '=', couple['account_id'][0])])
            if aa:
                initial, debit, credit, balance = aa.get_accounting_value(self.date_from, self.date_to, domain=domain )
                col = 1
                for key in couple.keys():
                    sheet.write(row, col, ['fields'][key]['string'])
                    col += 1
                for value in [initial, debit, credit, balance]:
                    sheet.write(row, col, ['fields'][key]['string'])
                    col += 1
                row += 1

        return True

    def generated_aged_summary_worksheet(self, sheet, aml_group=[], group_by=['account_id']):
        assert aml_group
        aa_pool = self.env['account.account']
        aml_pool = self.env['account.move.line']
        fields_to_exclude = ['__count', '__domain']

        # group_name =

        row, col = 6, 1
        for couple in aml_group:
            domain = [(key, '=', couple[key]) for key in group_by]
            aa = aa_pool.search([('account_id', '=', couple['account_id'][0])])
            
            

            if aa:
                initial, debit, credit, balance = aa.get_accounting_value(self.date_from, self.date_to, domain=domain)
                col = 1
                for key in couple.keys():
                    sheet.write(row, col, ['fields'][key]['string'])
                    col += 1
                for value in [initial, debit, credit, balance]:
                    sheet.write(row, col, ['fields'][key]['string'])
                    col += 1
                row += 1

        return True

    def _get_header_table(self, group_by=['account_id'], summary=False):
        aml_pool = self.env['account.move.line']
        fields_to_exclude = ['__count', '__domain']

        col_fields = group_by

        if not summary:
            col_fields = ['date'] + group_by

            if 'journal_id' not in group_by:
                col_fields += ['journal_id']

            if self.reconciled:
                col_fields += ['full_reconcile_id']

            col_fields += ['move_id']
            col_fields += ['name']

        col_fields += ['debit', 'credit', 'balance']

        header_table = {key :aml_pool.fields_get()[key]['string'] for key in col_fields}

        return header_table

    def get_cell_initial_value(self, key=False, header_table=False, initial=False, models=False, summary=False):
        assert key, header_table
        # assert initial
        model = list(filter(lambda r: r['key'] == key, models))
        if model:
            model = model[0]

        if key == 'date':
            return self.date_from

        elif model and key in list(model.values()):
            return model['id'].display_name

        elif key == 'debit':
            return initial > 0 and initial or 0

        elif key == 'credit':
            return initial < 0 and abs(initial) or 0

        elif key == 'balance':
            return initial
        else:
            return _('Initial Balance')

    def generate_detail_worksheet(self, sheet, aml_group=[], group_by=['account_id']):
        assert aml_group
        aml_pool = self.env['account.move.line']
        col_fields = ['date', 'account_id', 'partner_id', ]

        opening_move_ids = self.fiscalyear_id.opening_move_ids and self.fiscalyear_id.opening_move_ids  or False

        # table header =
        header_table = self._get_header_table(group_by, summary=False)

        row, col = 6, 1
        row_jump_table = 2

        for couple in aml_group:

            start_row = row
            # # ############################### Labels du tableau ###################################################"
            for key, title in header_table.items():
                sheet.write(row, list(header_table.keys()).index(key) + 1, title)
            row += 1


            # ##################################################################################"
            domain = [(key, '=', couple[key][0]) for key in group_by]
            models = [{'key': key, 'model': aml_pool.fields_get()[key]['relation'], 'id': couple[key][0]}
                      for key in group_by]
            for model in models:
                model['id'] = self.env[model['model']].search([('id', '=', model['id'])])

            # ################################## Balance Initiale ################################################"

            aa_model = list(filter(lambda r: r['key'] == 'account_id', models))[0]
            assert aa_model
            domain_init = [(key, '=', couple[key][0]) for key in group_by if 'account_id' not in group_by]
            initial = aa_model['id'].get_accounting_initial_value(self.date_from, domain=domain_init)

            h = []
            for k in header_table.keys():
                c = list(header_table.keys()).index(k) +1
                value = self.get_cell_initial_value(k, header_table, initial, models, False)
                sheet.write(row, c, value)
            row += 1

            # ################################ Ecriture de la période ##################################################"

            domain_line = [('date', '>=', self.date_from), ('date', '<=', self.date_to)] + domain
            if self.report_type is 'open' and opening_move_ids:
                domain_line += [('move_id', 'in', opening_move_ids.ids)]
            elif self.report_type is not 'open' and opening_move_ids:
                domain_line += [('move_id', 'not in', opening_move_ids.ids)]
            elif self.report_type is 'open' and not opening_move_ids:
                raise exceptions.UserError(_("Please set opening move entries."))

            lines = aml_pool.search(domain_line)

            for line in lines:
                res = line.read([k for k in header_table.keys()])[0]
                for k in header_table.keys():
                    col = list(header_table.keys()).index(k) + 1
                    value = isinstance(res[k], tuple) and res[k][1] or res[k]
                    sheet.write(row, col, value)
                row += 1

            # header = [{'header': v} for k, v in header_table.items()]
            header = [{'header': v} for k, v in header_table.items()]
            # worksheet_table_header.add_table(cell_range, {'header_row': True, 'columns': header})
            aml_pool.fields_get()
            # for k, v in header_table.items:
                # v['type']

            sheet.add_table(start_row, 1, row-1, len(header_table), {'columns': header, 'style': 'Table Style Light 9'})

            row += row_jump_table

        return True

    def get_dataframe(self, aml_group=[], group_by=['account_id']):

        if not aml_group and group_by:
            aml_group, group_by = self.get_aml_grouped_node_object()

        aml_pool = self.env['account.move.line']
        aa_pool = self.env['account.account']
        opening_move_ids = self.fiscalyear_id.opening_move_ids and self.fiscalyear_id.opening_move_ids or False
        header_table = self._get_header_table(group_by, summary=False)
        lines =[]
        for couple in aml_group:
            domain = [(key, '=', couple[key][0]) for key in group_by]

            # ################################## Balance Initiale ################################################"
            account_id = aa_pool.search([('id', '=', couple['account_id'][0])])
            if self.report_type != 'open':
                domain_init = [(key, '=', couple[key][0]) for key in group_by if 'account_id' not in group_by]
                initial_balance = account_id.get_accounting_initial_value(self.date_from, domain=domain_init)
                init_line = {'id': 'init'}
                for key in header_table.keys():
                    if key == 'date':
                        value = self.date_from
                    elif key in group_by:
                        value = couple[key][1]
                    elif key == 'debit':
                        value = initial_balance > 0 and initial_balance or 0
                    elif key == 'credit':
                        value = initial_balance < 0 and abs(initial_balance) or 0
                    elif key == 'balance':
                        value = initial_balance
                    else:
                        value = _('Initial Balance')
                    init_line[key] = value
                lines += [init_line]


                # ################################ Ecriture de la période ##################################################"

            domain_line = [('date', '>=', self.date_from), ('date', '<=', self.date_to)] + domain
            if self.report_type == 'open' and opening_move_ids:
                domain_line += [('move_id', 'in', opening_move_ids.ids)]
            elif self.report_type != 'open' and opening_move_ids:
                domain_line += [('move_id', 'not in', opening_move_ids.ids)]
            elif self.report_type == 'open' and not opening_move_ids:
                raise exceptions.UserError(_("Please set opening move entries."))

            lines += aml_pool.search(domain_line).read([k for k in header_table.keys()])
            for line in lines:
                for k, v in line.items():
                    if isinstance(v, tuple):
                        line[k] = v[1]
            # lines += [init_line] + aml_pool.search(domain_line).read([k for k in header_table.keys()], load='name')

        df = pd.DataFrame(lines)
        del df['id']
        # df.to_excel('/home/disruptsol/Desktop/test.xls')

        return header_table, df


    def print_excel_report(self):

        def _header_sheet(sheet):
            # sheet.write(0, 4, D_LEDGER [self.report_type]['name'], report_format)
            # logo = self.company_id.logo_web
            logo4 = io.BytesIO(base64.b64decode(self.company_id.logo_web))
            # logo4 = resizeimage.resize_cover(logo, [200, 100])

            sheet.insert_image('A1', 'logo', {'image_data': logo4})

            sheet.merge_range(0, 4, 1, 10, D_LEDGER[self.report_type]['name'], report_format)

            sheet.write(2, 0, _('Company:'), bold)
            sheet.write(3, 0, self.company_id.name, )
            sheet.write(4, 0, _('Print on %s') % fields.Date.context_today(self))

            sheet.write(2, 2, _('Start Date : %s ') % self.date_from if self.date_from else '')
            sheet.write(3, 2, _('End Date : %s ') % self.date_to if self.date_to else '')

            sheet.write(2, 4, _('Target Moves:'), bold)
            sheet.write(3, 4, _('All Entries') if self.target_move == 'all' else _('All Posted Entries'))

            sheet.write(2, 6,
                        _('Only UnReconciled Entries') if self.reconciled is False else _('With Reconciled Entries'),
                        bold)


        # aml_grouped, group_by = self._compute_data()


        # output = io.BytesIO()
        # workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        aml_pool = self.env['account.move.line']

        # output = io.StringIO()
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter', datetime_format='dd/mm/yyyy hh:mm:ss',date_format='dd/mm/yyyy')
        workbook = writer.book


        nom_fichier = self.company_id.name + ' - ' + D_LEDGER[self.report_type]['name'] + _(' From %s to %s') % (self.date_from, self.date_to)
        workbook.set_properties({
            'title': nom_fichier,
            'author': 'Aly Kane',
            'company': 'DisruptSol',
            'comments': 'Created with Python and XlsxWriter'})



        # TODO: Ecrire dans un fichier excel

        num_format = '_-* # ##0,00_-[$' + self.company_currency_id.symbol + ']'
        bold = workbook.add_format({'bold': True})
        middle = workbook.add_format({'bold': True, 'top': 1})
        left = workbook.add_format({'bold': True})
        right = workbook.add_format({'right': 1, 'top': 1})
        top = workbook.add_format({'top': 1})
        currency_format = workbook.add_format({'num_format': num_format})
        # currency_format = workbook.add_format({'num_format': num_format})
        c_middle = workbook.add_format({'bold': True, 'top': 1, 'num_format': num_format})
        report_format = workbook.add_format({'font_size': 24,
                                             'bold': True,
                                             'underline': True,
                                             'bg_color': '#4F81BD'})
        rounding = self.env.user.company_id.currency_id.decimal_places or 2
        lang_code = self.env.user.lang or 'en_US'
        date_format = self.env['res.lang']._lang_get(lang_code).date_format

        format_table = {
            'monetary': (20,currency_format),
            'many2one': (20, left),
            'date': (10, None),
            'int': None,
            'text': (50, left),
            'char': (50, left),
        }


        # ##############################################################
        aml_grouped_dict, group_by = self.get_aml_grouped_node_object()

        header_table, df = self.get_dataframe(aml_grouped_dict, group_by)
        fields_dict = aml_pool.fields_get()
        header_table = {key: {'name': header_table[key], 'type': fields_dict[key]['type']} for key in header_table.keys()}
        # df.to_excel(writer, sheet_name="details", index=False, startrow=ROW_TABLE_START, startcol=0)


        row, col = ROW_TABLE_START, COL_TABLE_START
        if not self.summary:
            sheet_name = _('Details')
            for couple in aml_grouped_dict:
                group = ' & '.join([key + ' == "' + str(couple[key][1]) + '"' for key in group_by])
                df_sub = df.query(group)
                row = self.print_excel_dataframe(df_sub, header_table, writer, row, col, sheet_name)
            worksheet = writer.sheets[sheet_name]
            _header_sheet(worksheet)
            # *********************************************************
            # set Columns format
            # *********************************************************

            self.sheet_format(df, header_table, format_table, writer, sheet_name)

        else:
            sheet_name = _('details')
            row = self.print_excel_dataframe(df, header_table, writer, row, col, sheet_name)
            self.sheet_format(df, header_table, format_table, writer, sheet_name)
            worksheet = writer.sheets[sheet_name]
            _header_sheet(worksheet)


            # Group by Dataframe
            col_name = [key for key in group_by]
            header_table['initial'] = {'name': _('Initial'), 'type': 'monetary'}
            header_table = {key: header_table[key] for key in group_by + ['initial', 'debit', 'credit', 'balance']}

            dfg_init = df[(df.move_id == 'Initial Balance')][ col_name + ['balance']].groupby(by=col_name, as_index=False).sum()
            dfg_init = pd.DataFrame(dfg_init).rename(columns={'balance': 'initial'})

            dfg = df[(df.move_id != 'Initial Balance')][ col_name + ['debit', 'credit', 'balance']].groupby(by=col_name, as_index=False).sum()
            dfg = pd.DataFrame(dfg)
            dfg = dfg.merge(dfg_init, how='left', on=col_name)
            dfg['balance'] = dfg['initial'] + dfg['debit'] - dfg['credit']

            # Reoder columns
            dfg = dfg[list(header_table.keys())]

            sheet_name = _('Summary')
            row, col = ROW_TABLE_START, COL_TABLE_START
            row = self.print_excel_dataframe(dfg, header_table, writer, row, col, sheet_name)
            self.sheet_format(dfg, header_table, format_table, writer, sheet_name)
            worksheet = writer.sheets[sheet_name]
            _header_sheet(worksheet)

        # ########################### Save worbook ###################################
        # workbook.close()
        writer.save()
        file = output.getvalue()
        file = base64.encodebytes(file)
        # base64.encode()
        output.close()
        # output.close()


        # ##############################################################
        wizard_id = self.env['report.wizard'].create({'data': file, 'name': nom_fichier})
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

    def sheet_format(self, df, header_table, format_table, writer, sheet_name):

        worksheet = writer.sheets[sheet_name]
        # _header_sheet(worksheet)

        for h in df.columns:
            # On cherche le type
            if header_table.get(h) and format_table.get(header_table[h]['type']):
                col_position = list(df.columns).index(h)
                format = format_table[header_table[h]['type']]
                worksheet.set_column(col_position, col_position, format[0], format[1])
            if h == 'initial':
                col_position = list(df.columns).index(h)
                format = format_table[header_table['initial']['type']]
                worksheet.set_column(col_position, col_position, format[0], format[1])





    def print_excel_dataframe(self, df, header_table, writer, row, col, sheet_name):

        df.to_excel(writer, sheet_name, index=False, startrow=row, startcol=col)

        worksheet = writer.sheets[sheet_name]

        # *********************************************************
        # set Excel Table
        # *********************************************************

        header = [{'header': v['name']} for k, v in header_table.items()]
        first_row = row
        first_col = col
        last_row = len(df) + first_row
        last_col = len(list(df.columns)) -1
        worksheet.add_table(first_row, first_col, last_row, last_col,
                            {'columns': header, 'style': 'Table Style Light 9'})

        row = last_row + 2

        return row
