# -*- coding: utf-8 -*-

import time
from odoo import api, models, _
from odoo.exceptions import UserError

COL_FORMAT = {'account_id': {'width': 10}}


class ReportCouponPrinting(models.AbstractModel):
    _name = 'report.bons_valeurs.coupon_template'

    @api.model
    def _get_report_values(self, docids, data=None):
        # if not data.get('form') or not self.env.context.get('active_model'):
        #     raise UserError(_("Form content is missing, this report cannot be printed."))

        self.model = 'coupon.value'
        docs = self.env['coupon.value'].browse(docids)

        saut = 4
        groupe_list = [docs[i:i+saut] for i in range(0, len(docs), saut)]

        res =  {
            'doc_ids': docids,
            'coupon_per_page': groupe_list,
            'page_number': len(groupe_list),
            'doc_model': self.model,
            'docs': docs,
            'time': time,
        }
        return res