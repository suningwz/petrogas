# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase

class TestSmpReporting(TransactionCase):

    def setUp(self, *args, **kwargs):
        super(TestSmpReporting, self).setUp(*args, **kwargs)

        aa_pool = self.env['account.account']
        fiscalyear_id = self.env['account.fiscal.year'].find()
        period_id = fiscalyear_id.period_ids.filtered(lambda r: r.code == '02/2020')
        date_from = fiscalyear_id.date_from
        date_to = fiscalyear_id.date_to
        account_chart = aa_pool.get_accounting_chart()

        val = {
            'fiscalyear_id': fiscalyear_id.id,
            'date_from': date_from,
            'date_to': date_to,
            'summary': True,
            'report_type': 'partner',
            'target_move': 'posted',
            'partner_type': 'all',
            'journal_ids': self.env['account.journal'].search([('company_id', '=', self.env.user.company_id.id)]).ids
        }

        self.test_wiz = self.env['accoutin.report.wizard'].create(val)

    def test_function_dataframe(self):
        aml_grouped_dict, group_by = self.test_wiz._get_aml_grouped_node_object()
        df = self.test_wiz.get_dataframe(aml_grouped_dict, group_by)
        self.assertTrue(df)