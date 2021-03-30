# -*- coding: utf-8 -*-

import time
from odoo import api, models, _
from odoo.exceptions import UserError

class ReportCredocForm(models.AbstractModel):
    _name = 'report.credoc.report_credoc_form'

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data.get('form') or not self.env.context.get('active_model'):
            raise UserError(_("Form content is missing, this report cannot be printed."))

        self.model = self.env.context.get('active_model')
        docs = self.env[self.model].browse(self.env.context.get('active_ids', []))

        return {
            'doc_ids': docids,
            'doc_model': self.model,
            'data': data['form'],
            'docs': docs,
            'time': time,
            # 'tables': tables,
            # 'col_name': col_name,
            # 'generate_full_account_chart': generate_full_account_chart,
            # 'header_table': header_table,
        }
