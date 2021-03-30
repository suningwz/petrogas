# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestSMPSale(TransactionCase):

    def setUp(self):
        super(TestSMPSale, self).setUp()

        order_dict = {
            'partner_id': 123,
            'regime_id': 123,
            'location_id': 123,
        }

        order_dict = {
            'product_id': 123,
            'regime_id': 123,
            'location_id': 123,
        }

        self.test_book = self.env['sale.order'].create({'name': 'Book 1'})

    #     self.uom_gram = self.env.ref('uom.product_uom_gram')
    #     self.uom_kgm = self.env.ref('uom.product_uom_kgm')
    #     self.uom_ton = self.env.ref('uom.product_uom_ton')
    #     self.uom_unit = self.env.ref('uom.product_uom_unit')
    #     self.uom_dozen = self.env.ref('uom.product_uom_dozen')
    #     self.categ_unit_id = self.ref('uom.product_uom_categ_unit')
    #
    def test_pricelist_get_product(self):
        print("test_pricelist_get_product")
