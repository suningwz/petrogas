# -*- coding: utf-8 -*-

import calendar
# from builtins import __generator

import odoo.addons.decimal_precision as dp
from datetime import datetime, timedelta
from odoo import api, models, fields, _, exceptions
import  pandas as pd
import base64,io
# from resizeimage import resizeimage
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
ROW_JUMP = 3

class AccountingReportWizard(models.TransientModel):
    _name = 'accounting.report.wizard'
    _description = 'Accounting Report Wizard'
    _inherit = "account.common.report"


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
    date_to = fields.Date(string='End Date', help='Use to compute the entrie matched with future.')
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

    @api.onchange('report_type')
    def onchage_report_type(self):
        self.account_ids = [(5, )]

    @api.onchange('partner_ids')
    def onchage_partner_ids(self):

        self.account_ids = [(5, )]
        # self.account_ids = [(4, x.id) for x in self.search_account().ids]

    @api.multi
    def search_account(self):
        domain = [('deprecated', '=', False), ('company_id', '=', self.company_id.id)]

        if self.account_ids:
            return self.account_ids
        elif self.report_type in ('partner', 'aged',):
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
        else:
            return self.env['account.account'].search([])

    @api.multi
    def search_partner(self):
        if self.partner_ids:
            return self.partner_ids
        elif self.report_type in ('partner', 'aged'):
            return self.env['res.partner'].search([])
        return False

    @api.multi
    def search_analytic_account(self):
        if self.report_type == 'analytic':
            if self.analytic_account_select_ids:
                return self.analytic_account_select_ids
            else:
                return self.env['account.analytic.account'].search([])
        return False
    
    def get_report_domain(self):
        domain = [('company_id', '=', self.company_id.id)]

        account_ids = self.search_account()
        domain += [('account_id', 'in', account_ids.ids)]

        partner_ids = self.search_partner()
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
            domain += [('analytic_id', 'in', self.search_analytic_account().ids)]

        if self.report_type == 'aged':
            domain += [('partner_id', 'in', self.search_partner().ids)]

        if self.target_move == 'posted':
            domain += [('move_id.state', '=', 'posted')]



        return domain

    def get_group_key(self):
        group_key = ['account_id']
        key = D_LEDGER[self.report_type]['group_by']
        if key != 'account_id':
            group_key += [key]
        return group_key

    def get_aml_grouped_node_object(self):
        group_by = self.get_group_key()

        domain = [('date', '<=', self.date_to)]
        domain += self.get_report_domain()

        couples = self.env['account.move.line'].read_group(domain=domain, fields=group_by, groupby=group_by, lazy=False)

        return couples, group_by

    def get_amount(self, aml_grouped=None, group_by=None, date_from=None, date_to=None):
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

    def get_aml(self, aml_grouped=None, group_by=None, date_from=None, date_to=None):
        assert aml_grouped
        assert group_by
        assert date_to

        domain = [(group, '=', aml_grouped[group][0]) for group in group_by]
        domain += [('date', '<=', date_to)]
        if date_from:
            domain += [('date', '>=', date_from)]
        res = self.env['account.move.line'].search(domain)
        return res

    def compute_data(self):

        def get_general_balance(accounting_chart):
            res = {}
            # print(accounting_chart.name, ' **', accounting_chart.child_ids.ids)
            for child in accounting_chart.child_ids:
                if child.child_ids and child.user_type_id.type is 'view':
                    res[child.id] = get_general_balance(child)
                else:
                    res[child.id] = list(filter(lambda d: d['account_id'] is child.id , aml_grouped_dict))
            return res

        aml_grouped_dict, group_by = self.get_aml_grouped_node_object()

        if not aml_grouped_dict:
            raise exceptions.UserError(_("""No account entries was founded preceding the date %s""") % self.date_to)

        # TODO: order aml_grouped: to do that use account_parent

        for aml_grouped in aml_grouped_dict:

            debit, credit, balance = self.get_amount(aml_grouped, group_by, date_from=None, date_to=self.date_from)
            aml_grouped['initial'] = balance
            debit, credit, balance = self.get_amount(aml_grouped, group_by, date_from=self.date_from, date_to=self.date_to)
            aml_grouped['debit'] = debit
            aml_grouped['credit'] = debit
            aml_grouped['balance'] = balance

            if not self.summary:
                aml_grouped['aml_ids'] = self.get_aml(aml_grouped, group_by, date_from=self.date_from, date_to=self.date_to)

        res = get_general_balance(self.accounting_chart)

        return aml_grouped_dict, group_by

    def _get_header_table(self, group_by=['account_id'], summary=False):
        aml_pool = self.env['account.move.line']
        fields_to_exclude = ['__count', '__domain']

        col_fields = group_by

        if not summary:
            col_fields = ['date'] + group_by

            if 'journal_id' not in group_by:
                col_fields += ['journal_id']

            if 'partner_id' not in group_by:
                col_fields += ['partner_id']

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

    def get_dataframe(self, aml_group=[], group_by=['account_id']):

        if not aml_group and group_by:
            aml_group, group_by = self.get_aml_grouped_node_object()

        aml_pool = self.env['account.move.line']
        aa_pool = self.env['account.account']
        opening_move_ids = self.fiscalyear_id.opening_move_ids and self.fiscalyear_id.opening_move_ids or False
        header_table = self._get_header_table(group_by, summary=False)
        lines =[]
        for couple in aml_group:
            # domain = [(key, '=', couple[key][0]) for key in group_by]
            domain = [r for r in couple['__domain'] if isinstance(r, tuple)]
            # ################################## Balance Initiale ################################################"
            account_id = aa_pool.search([('id', '=', couple['account_id'][0])])
            if self.report_type != 'open':
                domain_init = [(key, '=', couple[key][0]) for key in group_by]
                # domain_init = [(key, '=', couple[key][0]) for key in group_by if 'account_id' not in group_by]
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

            lines += aml_pool.search(domain_line, order="date asc").read([k for k in header_table.keys()])
            for line in lines:
                for k, v in line.items():
                    if isinstance(v, tuple):
                        line[k] = v[1]
            # lines += [init_line] + aml_pool.search(domain_line).read([k for k in header_table.keys()], load='name')

        df = pd.DataFrame(lines)

        h = self._get_header_field_type(header_table)
        col_to_round = [k for k, v in h.items() if v['type'] == 'monetary']
        decimals = self.env.user.company_id.currency_id.decimal_places or 2
        # decimals = pd.Series([self.env.user.company_id.currency_id.decimal_places or 2 for c in col_to_round], index=col_to_round)
        df[col_to_round] = df[col_to_round].round(decimals).fillna(0)
        # df[col_to_round] = df[col_to_round].style.format('${0:,.2f}')
        # df.to_excel('/home/disruptsol/Desktop/test.xls')

        return header_table, df

    def get_summary_dataframe(self, df, header_table, group_by):

        # Group by Dataframe
        col_name = [key for key in group_by]
        # header_table['initial'] = {'name': _('Initial'), 'type': 'monetary'}
        ht = {key: header_table[key] for key in group_by + ['initial', 'debit', 'credit', 'balance']}

        # dfg_init = df[(df.move_id == 'Initial Balance')][col_name + ['balance']].groupby(by=col_name,
        dfg_init = df[(df.id == 'init')][col_name + ['balance']].groupby(by=col_name,
                                                                                         as_index=False).sum()
        dfg_init = pd.DataFrame(dfg_init).rename(columns={'balance': 'initial'})
        decimals = self.env.user.company_id.currency_id.decimal_places or 2
        # dfg_init['initial'] = dfg_init['initial'].round(decimals).fillna(0)

        dfg = df[(df.id != 'init')][col_name + ['debit', 'credit']].groupby(by=col_name, as_index=False).sum()
        dfg = pd.DataFrame(dfg)

        # Reoder columns
        # dfg = dfg[list(ht.keys())]

        dff = df[group_by].drop_duplicates()
        dff = dff.merge(dfg_init, how='left', on=col_name)
        dff = dff.merge(dfg, how='left', on=col_name)
        dff[['initial', 'debit', 'credit']] = dff[['initial', 'debit', 'credit']].round(decimals).fillna(0)
        dff['balance'] = dff['initial'] + dff['debit'] - dff['credit']

        return dff

    def sheet_column_format(self, df, header_table, format_table, writer, sheet_name):


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
        header = []
        for k, v in header_table.items():
            if v['type'] == 'monetary':
                header.append({'header': v['name'],  'total_function': 'sum'})
            else:
                header.append({'header': v['name']})
        # header = [{'header': v['name'], 'total_function': 'sum'} for k, v in header_table.items()]
        # header = [{'header': v['name']} for k, v in header_table.items()]
        first_row = row
        first_col = col
        last_row = len(df) + first_row + 1
        last_col = len(list(df.columns)) -1
        worksheet.add_table(first_row, first_col, last_row, last_col,{'columns': header, 'style': 'Table Style Light 9', 'total_row': True})
        # worksheet.add_table(first_row, first_col, last_row, last_col,{'columns': header, 'style': 'Table Style Light 9'})

        row = last_row + ROW_JUMP

        return row

    def _get_header_field_type(self,header_table):
        ht = header_table.copy()
        fields_dict = self.env['account.move.line'].fields_get()
        for key in ht.keys():

            if key is 'initial':
                ht[key] = {'name': _('Initial'), 'type': 'monetary'}
            elif key is 'cumul':
                ht[key] = {'name': _('Cumul'), 'type': 'monetary'}
            elif fields_dict.get(key, False):
                ht[key] = {'name': ht[key], 'type': fields_dict[key]['type']}
            else:
                raise exceptions.UserError(_('No type has been found for the field %s. Please contact your administrator.') % key)
        # ht = {key: {'name': ht[key], 'type': fields_dict[key]['type']} for key in ht.keys()}
        return ht

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


        # aml_grouped, group_by = self.compute_data()


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
                del df_sub['id']
                if self.report_type in ('general','partner','journal'):
                    df_sub['cumul'] = df_sub['balance'].expanding().sum()
                    header_table['cumul'] = {'name': _('Cumul'), 'type': 'monetary'}

                # df_sub['cumul'] = df_sub['balance'].shift(1)
                # df_sub['cumul'] = df_sub['cumul'] + df_sub['balance']
                row = self.print_excel_dataframe(df_sub, header_table, writer, row, col, sheet_name)
            worksheet = writer.sheets[sheet_name]
            _header_sheet(worksheet)
            # *********************************************************
            # set Columns format
            # *********************************************************

            self.sheet_column_format(df, header_table, format_table, writer, sheet_name)

        else:
            sheet_name = _('Summary')

            # Group by Dataframe
            header_table['initial'] = {'name': _('Initial'), 'type': 'monetary'}
            header_table = {key: header_table[key] for key in group_by + ['initial', 'debit', 'credit', 'balance']}
            dfg = self.get_summary_dataframe(df, header_table, group_by)
            row, col = ROW_TABLE_START, COL_TABLE_START
            if len(group_by) > 1:
                couples = dfg[group_by[:-1]].drop_duplicates().to_dict('records')
                for couple in couples:
                    # # group = []
                    # for key, value in couple.items():
                    #     group = key + ' == "' + str(value) + '"'
                    group = ' & '.join([key + ' == "' + str(value) + '"' for key, value in couple.items()])
                    df_sub = dfg.query(group)
                    row = self.print_excel_dataframe(df_sub, header_table, writer, row, col, sheet_name)
            else:
                row = self.print_excel_dataframe(dfg, header_table, writer, row, col, sheet_name)

            self.sheet_column_format(dfg, header_table, format_table, writer, sheet_name)
            worksheet = writer.sheets[sheet_name]
            _header_sheet(worksheet)

        # ########################### Save worbook ###################################
        # workbook.close()
        writer.save()
        file = output.getvalue()
        file = base64.encodebytes(file)
        output.close()

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

    def print_pdf_report(self):
        return self.check_report()

    @api.multi
    def check_report(self):
        self.ensure_one()
        data = {}
        data['ids'] = self.env.context.get('active_ids', [])
        data['model'] = self.env.context.get('active_model', 'ir.ui.menu')
        # data['form'] = self.read(['date_from', 'date_to', 'journal_ids', 'target_move', 'company_id'])[0]
        data['form'] = self.read(self.fields_get_keys())[0]
        for field in data['form']:
            if isinstance(data['form'][field], tuple):
                data['form'][field] = data['form'][field][1]
        used_context = self._build_contexts(data)
        data['form']['used_context'] = dict(used_context, lang=self.env.context.get('lang') or 'en_US')
        return self.with_context(discard_logo_check=True)._print_report(data)

    @api.multi
    def _print_report(self, data):
        # data = self.pre_print_report(data)
        records = self.env[data['model']].browse(data.get('ids', []))
        return self.env.ref('smp_accounting.action_report_smp_accounting_wizard').report_action(records, data=data)

