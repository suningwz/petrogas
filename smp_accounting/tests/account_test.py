# # -*- coding: utf-8 -*-
#
#
# format_table = {
#     'monetary': None,
#     'many2one': None,
#     'char': None,
#     'int': None,
#     'text': None,
#                  }
#
# aa_pool = self.env['account.account']
# fiscalyear_id = self.env['account.fiscal.year'].find()
# frs = aa_pool.search([('code','=','400000')])
# date_from = fiscalyear_id.date_from
# date_to = fiscalyear_id.date_to
# account_chart = aa_pool.get_accounting_chart()
#
# debit, credit = frs.get_accounting_debit_credit_value(fiscalyear_id.date_from, fiscalyear_id.date_to)
# initial = frs.get_accounting_initial_value(date_from)
# balance = initial + debit - credit
#
# accounting_value = frs.get_accounting_value(date_from, date_to)
#
# account_chart.get_chart_tree_dict(date_from, date_to)
#
#
# supplier = self.env['res.partner'].search([('supplier','=',True)])
# supplier = self.env['res.partner'].search([('name','like', 'Addax')])[0]
# frs.get_accounting_value(date_from, date_to, domain=[('partner_id', '=', 538)])
# frs.get_fiscal_year_opening_value(date_from, domain=[('partner_id', '=', 538)])
# frs.get_accounting_initial_value(date_from, domain=[('partner_id', '=', 538)])
# frs.get_accounting_debit_credit_value(date_from, date_to, domain=[('partner_id', '=', 538)])
#
# #************** Wizard Report *******************
# import pandas as pd
# aa_pool = self.env['account.account']
# aml_pool = self.env['account.move.line']
# fiscalyear_id = self.env['account.fiscal.year'].find()
# frs = aa_pool.search([('code','=','400000')])
# date_from = fiscalyear_id.date_from
# date_to = fiscalyear_id.date_to
# aa_pool = self.env['account.account']
# aml_pool = self.env['account.move.line']
# account_chart = aa_pool.get_accounting_chart()
# account_chart_json = account_chart.get_chart_tree_json(date_from, date_to)
#
#
# domain = {
#     'fiscalyear_id' : fiscalyear_id.id,
#     'date_from': date_from,
#     'date_to': date_to,
#     'summary': True,
#     'report_type': 'general',
#     'target_move': 'posted',
#     'partner_type': 'all',
#     'journal_ids': self.env['account.journal'].search([('company_id', '=', self.env.user.company_id.id)]).ids
# }
#
# wiz = self.env['accounting.report.wizard'].create([domain])
# aml_grouped_dict, group_by = wiz.get_aml_grouped_node_object()
# header_table, df = wiz.get_dataframe(aml_grouped_dict,group_by)
#
# pd.DataFrame(df[group_by].drop_duplicates(ignore_index=True))
#
# col_name = [key for key in group_by]
# dfg = df[ col_name + ['debit', 'credit', 'balance']].groupby(by=col_name)
#
#
#
# for couple in aml_grouped_dict:
#     group = [key + ' == "' + str(couple[key][1]) + '"'  for key in group_by]
#     group = ' & '.join(group)
#
#
#
# newdf = df.query('origin == "JFK" & carrier == "B6"')
#
# aa_pool = self.env['account.account']
# aml_pool = self.env['account.move.line']
# header_table = [aml_pool.fields_get()[key]['string'] for key in group_by]
#
# models = [{'key': key ,'model': aml_pool.fields_get()[key]['relation'], 'id': aml_grouped_dict[0][key][0]} for key in group_by]
#
# fields_dict = aml_pool.fields_get()
#
# new_header_table = {}
# for key in header_table.keys():
#     new_header_table[key] = {'name': header_table[key], 'type': fields_dict[key]['type']}
#
#
#
#
# for model in models:
#     model['id'] = self.env[model['model']].search([('id', '=', model['id'])])
#
# couple = aml_grouped_dict[0]
#
# aa_model = list(filter(lambda r: r['key'] == 'account_id', models))[0]
# assert aa_model
# initial= aa_model['id'].get_accounting_initial_value(wiz.date_from, domain=[(key, '=', couple[key]) for key in group_by if 'account_id' not in group_by])
#
# for key in group_by:
#     print(list(filter(lambda r: r['key'] == key, models))[0])
#
#
#
# a = { '1':1, '2':2}
#
# currency_format = workbook.add_format({'num_format': '$#,##0'})
#
# {'boolean': ,
#  'char',
#  'date': date_format,
#  'datetime': date_format,
#  'float': num_format,
#  'integer': num_format,
#  'many2many',
#  'many2one': ,
#  'monetary': num_format,
#  'one2many',
#  'text'}
#
# aa_pool = self.env['account.account']
# account_chart = aa_pool.get_accounting_chart()
# a = account_chart.get_chart_tree_json()
# aa_pool.get_chart_tree_json_to_list(a)
#
#
# # ******************************************************************************************
#
# aa_pool = self.env['account.account']
# aml_pool = self.env['account.move.line']
# fiscalyear_id = self.env['account.fiscal.year'].find()
# date_from = fiscalyear_id.date_from
# date_to = fiscalyear_id.date_to
#
# account_chart = aa_pool.get_accounting_chart()
# account_chart_json = account_chart.get_chart_tree_json(date_from, date_to)
# account_chart_json_list = account_chart.get_chart_tree_json_to_list(account_chart_json)
