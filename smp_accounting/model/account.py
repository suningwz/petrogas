# -*- coding: utf-8 -*-
##############################################################################
#
#    ODOO, Open Source Management Solution
#    Copyright (C) 2016 Steigend IT Solutions
#    For more details, check COPYRIGHT and LICENSE files
#
##############################################################################
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import odoo.addons.decimal_precision as dp
from odoo.tools import safe_eval
from dateutil.relativedelta import relativedelta


    

class AccountAccount(models.Model):
    _inherit = "account.account"
    
    @api.model
    def _move_domain_get(self, domain=None):
        context = dict(self._context or {})
        domain = domain and safe_eval(str(domain)) or []
        
        date_field = 'date'
        if context.get('aged_balance'):
            date_field = 'date_maturity'
        if context.get('date_to'):
            domain += [(date_field, '<=', context['date_to'])]
        if context.get('date_from'):
            if not context.get('strict_range'):
                domain += ['|', (date_field, '>=', context['date_from']), ('account_id.user_type_id.include_initial_balance', '=', True)]
            elif context.get('initial_bal'):
                domain += [(date_field, '<', context['date_from'])]
            else:
                domain += [(date_field, '>=', context['date_from'])]

        if context.get('journal_ids'):
            domain += [('journal_id', 'in', context['journal_ids'])]

        state = context.get('state')
        if state and state.lower() != 'all':
            domain += [('move_id.state', '=', state)]

        if context.get('company_id'):
            domain += [('company_id', '=', context['company_id'])]

        if 'company_ids' in context:
            domain += [('company_id', 'in', context['company_ids'])]

        if context.get('reconcile_date'):
            domain += ['|', ('reconciled', '=', False), '|', ('matched_debit_ids.create_date', '>', context['reconcile_date']), ('matched_credit_ids.create_date', '>', context['reconcile_date'])]

        return domain
    
    
    partner_required = fields.Boolean('Partenaire Requis')
    # .# compacted = fields.Boolean('Compacte entries.',
    #                            help='If flagged, no details will be displayed in the Standard report, only compacted amounts.',
    #                            default=False)
    type_third_parties = fields.Selection([('no', 'No'), ('supplier', 'Supplier'), ('customer', 'Customer'), ('employee', 'Employee')], string='Third Partie', required=True, default='no')

    @api.model
    def get_accounting_chart(self):
        return self.with_context(show_parent_account=True).search([('parent_id', '=', False), ('user_type_id.type', '=', 'view')])

    @api.multi
    def accounting_chart_tree_json(self, date_from=None, date_to=None, level=0, profondeur=0):
        self.ensure_one()
        # print(self.code, ' * ', self.name, ' : ', self.user_type_id.type)
        account_chart = self

        res = {
            'id': self.id,
            'account_id': self.display_name,
            'level': level,
            'profondeur': profondeur,
            'type': self.user_type_id.type,
            'initial': 0.0,
            'debit': 0.0,
            'credit': 0.0,
            'balance': 0.0,
            'child_ids': []
        }

        # level += 1
        if not date_from and not date_to:
            fiscalyear_id = self.env['account.fiscal.year'].find(fields.date.today())
            date_from = fiscalyear_id.date_from
            date_to = fiscalyear_id.date_to
        child_ids = self.child_ids
        print('child_id: ', self.child_ids.ids)
        if self.user_type_id.type == 'view':
            if self.child_ids:
                profondeur += 1
                for child in self.child_ids:
                    level += 1
                    res['child_ids'].append(child.accounting_chart_tree_json(date_from, date_to, level, profondeur))
                    # res['child_ids'][child.id] = child.accounting_chart_tree_json(date_from, date_to, level, profondeur)

                res['initial'] = sum([child['initial'] for child in res['child_ids']])
                res['debit'] = sum([child['debit'] for child in res['child_ids']])
                res['credit'] = sum([child['credit'] for child in res['child_ids']])
                res['balance'] = sum([child['balance'] for child in res['child_ids']])
                # res['initial'] += res['child_ids'][child.id]['initial']
                # res['debit'] += res['child_ids'][child.id]['debit']
                # res['credit'] += res['child_ids'][child.id]['credit']
                # res['balance'] += res['child_ids'][child.id]['balance']

        else:
            initial, debit, credit, balance = self.get_accounting_value(date_from, date_to)
            res['initial'] = initial
            res['debit'] = debit
            res['credit'] = credit
            res['balance'] = balance

        return res

    @api.multi
    def get_chart_tree_json(self, date_from=None, date_to=None):
        self.ensure_one()
        assert self.user_type_id.type == 'view'

        if not date_from and not date_to:
            fiscalyear_id = self.env['account.fiscal.year'].find(fields.date.today())
            date_from = fiscalyear_id.date_from
            date_to = fiscalyear_id.date_to

        account_chart = self
        if not account_chart:
            account_chart = self.get_accounting_chart()

        res = account_chart.accounting_chart_tree_json(date_from, date_to)

        print('Get chart account')
        return res

    @api.model
    def get_chart_tree_json_to_list(self, chart_json=None):
        if not chart_json:
            chart_json = self.get_chart_tree_json()
        res = {}
        res[chart_json['id']] = {k: chart_json[k] for k in chart_json.keys() if k != 'child_ids'}
        if chart_json['child_ids']:
            for child in chart_json['child_ids']:
                res.update(self.get_chart_tree_json_to_list(child))
        return res

    def get_chart_tree_dict_new(self, date_from=None, date_to=None):
        self.ensure_one()
        print(self.code, ' * ', self.name, ' : ', self.user_type_id.type)
        res = {'initial': 0.0, 'debit': 0.0, 'credit': 0.0, 'child_ids': {}, 'account_id': self, }
        initial, debit, credit = 0, 0, 0

        # level += 1
        if not all([date_from, date_to]):
            fiscalyear_id = self.env['account.fiscal.year'].find(fields.date.today())
            date_from = fiscalyear_id.date_from
            date_to = fiscalyear_id.date_to

        if self.user_type_id.type == 'view':
            if self.child_ids:
                for child in self.child_ids:
                    res['child_ids'][child.id] = child.get_chart_tree_dict_new(date_from, date_to)
                initial = sum([child['initial'] for child in res['child_ids']])
                debit = sum([child['debit'] for child in res['child_ids']])
                credit = sum([child['credit'] for child in res['child_ids']])

        else:
            initial, debit, credit, balance = self.get_accounting_value(date_from, date_to)

        res['initial'] = initial
        res['debit'] = debit
        res['credit'] = credit

        return res

    @api.multi
    def get_accounting_value(self, date_from=None, date_to=None, domain=[]):
        # print('dsssssssssssss')
        self.ensure_one()
        assert date_to, date_from
        assert self.user_type_id.type != 'view'
        initial = self.get_accounting_initial_value(date_from, domain=domain)
        debit, credit = self.get_accounting_debit_credit_value(date_from, date_to,domain=domain )

        return initial, debit, credit , initial + debit - credit

    @api.multi
    def get_fiscal_year_opening_value(self, date_from, group_by=['account_id'], domain=[]):
        fiscalyear_id = self.env['account.fiscal.year'].find(date_from)
        opening_move_ids = fiscalyear_id.opening_move_ids
        t1_initial_balance = 0
        if opening_move_ids:
            t1_domain = domain + [('account_id', '=', self.id), ('move_id', 'in', opening_move_ids.ids)]
            t1_initial_balance_dict = self.env['account.move.line'].read_group(domain=t1_domain, fields=['balance'],
                                                                               groupby=group_by, lazy=False)
            if t1_initial_balance_dict:
                assert len(t1_initial_balance_dict) == 1
                t1_initial_balance = t1_initial_balance_dict[0]['balance']
        else:
            previous_fiscayear_id = fiscalyear_id.find(fiscalyear_id.date_from - relativedelta(days=-1))
            previous_fy_opening_balance = self.get_opening_value(previous_fiscayear_id)
            previous_fy_debit, previous_fy_credit = self.get_accounting_debit_credit_value(previous_fiscayear_id.date_from, previous_fiscayear_id.date_to)

            t1_initial_balance = previous_fy_opening_balance + previous_fy_debit - previous_fy_credit

        return t1_initial_balance

    @api.multi
    def get_accounting_initial_value(self, date_from=None, group_by=['account_id'], domain=[]):
        self.ensure_one()
        assert date_from
        fiscalyear_id = self.env['account.fiscal.year'].find(date_from)
        opening_move_ids = fiscalyear_id.opening_move_ids


        # report à nouveau au début de l'année N
        t1_initial_balance = self.get_fiscal_year_opening_value(date_from, domain=domain)

        t2_debit, t2_credit = 0, 0
        if date_from != fiscalyear_id.date_from:
            t2_debit, t2_credit = self.get_accounting_debit_credit_value(fiscalyear_id.date_from, date_from+ relativedelta(days=-1), domain=domain)

        return t1_initial_balance + t2_debit - t2_credit

    @api.multi
    def get_accounting_debit_credit_value(self, date_from=None, date_to=None, group_by=['account_id'], domain=[]):
        self.ensure_one()
        assert date_from, date_from
        debit, credit = 0, 0
        fiscalyear_id= self.env['account.fiscal.year'].find(date_from)
        fiscalyear_id_to = self.env['account.fiscal.year'].find(date_to)
        assert fiscalyear_id == fiscalyear_id_to


        domain = domain + [('account_id', '=', self.id), ('date', '>=', date_from), ('date', '<=', date_to)]
        if fiscalyear_id.opening_move_ids:
            domain += [('move_id', 'not in', fiscalyear_id.opening_move_ids.ids)]

        debit_credit_dict = self.env['account.move.line'].read_group(domain=domain, fields=['debit', 'credit'], groupby=group_by, lazy=False)

        if debit_credit_dict:
            assert len(debit_credit_dict) == 1
            debit, credit = debit_credit_dict[0]['debit'], debit_credit_dict[0]['credit']

        return debit, credit



class AccountMove(models.Model):

    _inherit = 'account.move'

    @api.multi
    def _check_partner(self):
        """We check if the account must have a partner_id"""
        for move in self:
            move_ids = move.line_ids.filtered(lambda x: x.account_id.partner_required and not x.partner_id)
            if move_ids:
                code = ', '.join(move_ids.mapped('account_id').mapped('code'))
                raise UserError(_("""Please enter a partner name for the following accounts: %s""") % (code))


    @api.multi
    def post(self, invoice=False):
        self._check_partner()
        res = super(AccountMove,self).post(invoice)


# class AccountMoveLine(models.Model):
#     _inherit = 'account.move.line'
#
#     @api.model
#     def get_aml_dataframe(self, domain=[]):
#         query ="""
#             Select
#                 aml.id as id,
#                 aa.code as code_cpt,
#                 aa.name as nom_cpt,
#                 am.name as pc_name,
#                 am.ref as ref_ecrt,
#                 aml.name as decription,
#                 aj.code as code_journal,
#                 aj.name as nom_journal,
#                 aml.date,
#                 aml.debit,
#                 aml.credit,
#                 aml.balance,
#                 afc.name as reconcile_id
#
#             From account_move_line as aml
#                 left join account_account as aa on aml.account_id = aa.id
#                 left join account_journal as aj on aml.journal_id = aj.id
#                 left join account_move as am on aml.move_id = am.id
#                 left join res_partner as rp on aml.partner_id = rp.id
#                 left join product_product as pp on aml.product_id = pp.id
#                 left join account_full_reconcile as afc on aml.full_reconcile_id = afc.id
#
#             """
#
#         mapping = {
#             'account_id': "account_id",
#             'account_id': "account_id",
#             'account_id': "account_id",
#             'account_id': "account_id",
#         }
#
#         tables, where_clause, where_params = self.env['account.move.line']._query_get(domain=domain)
#         tables = tables.replace('"', '') if tables else "account_move_line"
#         wheres = [""]
#         if where_clause.strip():
#             wheres.append(where_clause.strip())
#         filters = " AND ".join(wheres)
#         request = "SELECT account_move as id, " + ', '.join(mapping.values()) + \
#                   " FROM " + tables + \
#                   " WHERE account_id IN %s " \
#                   + filters + \
#                   " GROUP BY account_id"
#         params = (tuple(accounts._ids),) + tuple(where_params)
#         self.env.cr.execute(request, params)
#         return True
#
