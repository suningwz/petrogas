# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _, exceptions, tools
from datetime import date, timedelta
from odoo.exceptions import UserError, ValidationError
from odoo.addons import decimal_precision as dp
from odoo.tools import float_compare, pycompat, float_is_zero
import calendar as cal
from collections import Counter
import timeit
import xlsxwriter as xls
import io, base64
import pandas as pd
from _collections import defaultdict

import logging
_logger = logging.getLogger(__name__)


class ProductCostHistory(models.Model):
    """ Keep track of the ``product.template`` standard prices as they are changed. """
    _name = 'product.cost.history'
    # _rec_name = 'datetime'
    _order = 'date desc'
    _description = 'Product Cost List History'

    def _get_default_company_id(self):
        return self._context.get('force_company', self.env.user.company_id.id)

    date = fields.Date('Date')
    product_id = fields.Many2one('product.product', 'Product', ondelete='cascade', required=True)
    location_id = fields.Many2one('stock.location', 'Location', ondelete='cascade', required=True)
    cost_unit = fields.Float('Cost Unit', digits=dp.get_precision('Product Price'))
    cost = fields.Float('Cost', digits=dp.get_precision('Product Price'))
    quantity = fields.Float('Quantity', digits=dp.get_precision('Unit Of Measure'))
    company_id = fields.Many2one('res.company', string='Company', default=_get_default_company_id, required=True)

    _sql_constraints = [('unique_couple', 'UNIQUE(date, product_id, location_id, company_id)', 'The couple date, product, location must be unique')]

    @api.constrains('date')
    def check_date(self):
        if not self.date.day == cal.monthrange(self.date.year, self.date.month)[1]:
            raise UserError(_("The stock revaluation is set for a monthly revaluation"""))
        return True

    @api.model
    def get_previous_history(self,product_id, location_id, date):
        domain = [('product_id', '=', product_id),
                  ('location_id', '=', location_id),
                  ('date', '=', date - timedelta(days=1)),
                  ]
        hist_id = self.search(domain, order='date DESC')
        if not hist_id:
            val = {
                'product_id': product_id,
                'location_id': location_id,
                'date': date - timedelta(days=1),
                'cost_unit': 0.0,
                'cost': 0.0,
                'quantity': 0.0,
                }
            return self.create([val])
        return hist_id[0]

    @api.model
    def set_cost_history(self, product_id, location_id, date, quantity, cost_unit):
        domain = [('product_id', '=', product_id),
                  ('location_id', '=', location_id),
                  ('date', '=', date),
                  ]
        hist_id = self.search(domain, order='date DESC')
        if not hist_id:
            val = {
                'product_id': product_id,
                'location_id': location_id,
                'date': date,
                'cost_unit': cost_unit,
                'cost': cost_unit * quantity,
                'quantity': quantity,
                }
            hist_id = self.create([val])
        else:
            hist_id = hist_id[0]
            hist_id.cost_unit = cost_unit
            hist_id.cost = cost_unit * quantity
            hist_id.quantity = quantity
        return hist_id
    # def stock_recompute


class ProductCostRevaluation(models.TransientModel):
    """ Keep track of the ``product.template`` standard prices as they are changed. """
    _name = 'product.cost.revaluation'
    _description = 'Product Cost Revaluation'

    period_id = fields.Many2one('account.period', string="Account Period", domain=[('state','=','open')])
    date_from = fields.Date('Date from', default=fields.Date.today(), required=True)
    date_to = fields.Date('Date to', default=fields.Date.today(), required=True)
    # product_id = fields.Many2one('product.product', 'Product', ondelete='cascade', required=True)
    # location_id = fields.Many2one('stock.location', 'Location', ondelete='cascade', required=True)


    @api.onchange('period_id')
    def onchange_period(self):
        if self.period_id:
            self.update({
                'date_from': self.period_id.date_from,
                'date_to': self.period_id.date_to,
            })
            # return True

    def get_location_to_value(self):
        location_ids = self.env['stock.location'].search([]).filtered(lambda x: x._should_be_valued())
        if not location_ids:
            raise UserError(_('No location set for valuation !!!'))
        return location_ids

    def get_product_to_value(self):
        categ = self.env['product.category'].search([('property_cost_method', '=', 'average')])
        product_ids = self.env['product.product'].search([('categ_id', 'in', categ.ids)])
        if not product_ids:
            raise UserError(_('No product  set for cost average valuation !!!'))
        return product_ids

    def get_couple_product_location(self):
        product = self.get_product_to_value()
        location = self.get_location_to_value()
        Smove = self.env['stock.move']

        domain = [('product_id','in',product.ids),
                  '|', ('location_id', 'in', location.ids),
                  ('location_dest_id', 'in', location.ids),
                  ('date', '>=', self.date_from),
                  ('date', '<=', self.date_to)
                  ]

        domain_out = [('product_id','in',product.ids),
                      ('location_id', 'in', location.ids),
                      ('date', '>=', self.date_from),
                      ('date', '<=', self.date_to),('state', '=', 'done')
                      ]

        domain_in = [('product_id','in',product.ids),
                     ('location_dest_id', 'in', location.ids),
                     ('date', '>=', self.date_from),
                     ('date', '<=', self.date_to),('state', '=', 'done')
                     ]

        couple_out = Smove.read_group(domain_out, ['product_id', 'location_id'], ['product_id', 'location_id'],lazy=False)
        couple_in = Smove.read_group(domain_in, ['product_id', 'location_dest_id'], ['product_id', 'location_dest_id'],lazy=False)

        res =[]
        res += [(couple['product_id'], couple['location_id']) for couple in couple_out ] + [(couple['product_id'], couple['location_dest_id']) for couple in couple_in ]
        return set(res)

    def get_stock_move(self, product_id, location_id, sens=None):
        product = product_id
        location = location_id
        Smove = self.env['stock.move']

        if sens == None:
            domain = [('product_id','=',product),
                      '|', ('location_id', '=', location),
                      ('location_dest_id', '=', location),
                      ('date_expected', '>=', self.date_from),
                      ('date_expected', '<=', self.date_to),
                      ('state', '=', 'done')
                      ]
        elif sens=='in':
            domain = [('product_id', '=', product),
                         ('location_dest_id', '=', location),
                         ('date_expected', '>=', self.date_from),
                         ('date_expected', '<=', self.date_to),
                         ('state', '=', 'done')
                         ]
        elif sens == 'out':
            domain = [('product_id', '=', product),
                          ('location_id', '=', location),
                          ('date_expected', '>=', self.date_from),
                          ('date_expected', '<=', self.date_to),
                          ('state', '=', 'done')
                          ]

        else:
            raise UserError(_("The direction of the operation is unknow !!!"))

        # returned_move_ids = self.env['stock.move'].search([('origin_returned_move_id', '!=', None)])
        # returned_move_ids = self.env['stock.move'].search([('origin_returned_move_id', '!=', None)])
        # move_ids = Smove.search(domain) - returned_move_ids
        move_ids = Smove.search(domain)


        return move_ids

    def get_out_couple_by_operation(self, product_id, location_id):
        domain_out = [('product_id', '=', product_id),
                      ('location_id', '=', location_id),
                      ('date', '>=', self.date_from),
                      ('date', '<=', self.date_to),
                      ('origin_returned_move_id', '=', None),
                      ('state', '=', 'done')
                      ]
        couples = self.env['stock.move'].read_group(domain_out, ['product_id', 'location_id', 'picking_type_id'], ['product_id', 'location_id', 'picking_type_id'], lazy=False)
        return set([(c['product_id'], c['location_id'], c['picking_type_id']) for c in couples])

    def get_in_couple_by_operation(self,  product_id, location_id):
        domain_out =  [('product_id', '=', product_id),
                      ('location_id', '=', location_id),
                      ('date', '>=', self.date_from),
                      ('date', '<=', self.date_to),
                      ('origin_returned_move_id', '=', None),
                       ('state', '=', 'done')
                      ]
        couples = self.env['stock.move'].read_group(domain_out, ['product_id', 'location_dest_id', 'picking_type_id'], ['product_id', 'location_dest_id', 'picking_type_id'],  lazy=False)
        return set([(c['product_id'], c['location_dest_id'], c['picking_type_id']) for c in couples])

    def _get_tree(self):

        class Node:

            def __init__(self, sequence, couple):
                self.sequence = sequence
                self.product_id = couple[0][0]
                self.product_name = couple[0][1]
                # self.product_name = n.product_id == 0 and '' or n.product_name
                self.location_id = couple[1][0]
                self.location_name = couple[1][1]
                self.child = list()
                self.parent = list()
                self.route = list()
                self.level = None

            def add_child(self, v):
                if v not in self.child:
                    self.child.append(v)
                    self.child.sort()

            def add_parent(self, v):
                if v not in self.parent:
                    self.parent.append(v)
                    self.parent.sort()

        class Tree:
            nodes = {}
            order_compute = {}
            boucle = []
            edges = []

            def add_nodes(self, node):
                if isinstance(node, Node) and node.sequence not in self.nodes:
                    self.nodes[node.sequence] = node
                    return True
                else:
                    return False

            def add_edge(self, u, v, operation):
                if u in self.nodes and v in self.nodes:
                    self.nodes[u].add_child(v)
                    self.nodes[v].add_parent(u)
                    self.edges.append([u, v, operation[0],operation[1]])
                    return True
                else:
                    return False

            def tracert(self, u, parent=list()):
                _all_p = []
                #  si U a des parent, pour chaque enfant de ces parent
                if self.nodes[u].parent:
                    for parent_node in self.nodes[u].parent:
                        p = parent[:] + [self.nodes[parent_node].sequence]

                        if p[-1] not in p[:-1] and self.nodes[p[-1]].parent:
                            p = self.tracert(p[-1], p)

                        _all_p.append(p)
                        del p
                return _all_p

            def depack(self, trajet, i=list()):
                if all(isinstance(x, list) for x in trajet):
                    for x in trajet:
                        if all(isinstance(j, list) for j in x):
                            self.depack(x, i)
                        elif len(x) != 0:
                            i.append(x)
                    return i

            def set_trajet(self):
                for key in self.nodes:
                    if key != 0:
                        self.nodes[key].route = self.depack(self.tracert(key, [key]), [])

                        nb_route = len(self.nodes[key].route)
                        max_level = nb_route > 0 and max([len(x) for x in self.nodes[key].route]) - 1 or 0

                        self.nodes[key].level = max_level

                        if max_level in self.order_compute:
                            self.order_compute[max_level] = self.order_compute[max_level] + [key]
                        else:
                            self.order_compute[max_level] = [key]


                        # print( '*' * 30)
                        # print( key, ' : ', nb_route, ' - ', max_level, ' ---> ', self.nodes[key].route)
                        # print( 'order : ', self.order_compute)

                self.find_loop()

            def find_loop(self):
                for key in self.nodes:
                    routes = self.nodes[key].route
                    for r in routes:
                        occ = Counter(r).most_common(1)[0]
                        if occ[1] > 1:
                            self.boucle.append(r)

        tree = Tree()

        node_sequence = 0
        couple_product_location = self.get_couple_product_location()

        for couple in couple_product_location:
            node_sequence += 1
            node = Node(node_sequence, couple)
            tree.add_nodes(node)

        for sequence, node in tree.nodes.items():
            for couple in self.get_out_couple_by_operation(node.product_id, node.location_id):
                node_dest = next(item for item in couple_product_location if item[0][0] == node.product_id and item[1][0]== node.location_id)
                tree.add_edge(node, node_dest, couple[2])

            for couple in self.get_in_couple_by_operation(node.product_id, node.location_id):
                node_src = next(item for item in couple_product_location if item[0][0] == node.product_id and item[1][0]== node.location_id)
                tree.add_edge(node_src, node, couple[2])

        tree.set_trajet()
        return tree

    def compute_cmp(self):
        _logger.info('Stock Product Average Cost starting')
        start = timeit.timeit()
        tree = self._get_tree()
        stock_move_ids = self.env['stock.move']
        for level, key_nodes in tree.order_compute.items():
            for key in key_nodes:
                node_to_compute = tree.nodes[key]
                _logger.info('Product: %s  and Location: %s' % (node_to_compute.product_name, node_to_compute.location_name))

                ################################ Données initiale ###################################
                previous_cost_history = self.env['product.cost.history'].get_previous_history(node_to_compute.product_id, node_to_compute.location_id, self.date_from)
                product_qty_init = previous_cost_history.quantity
                product_value_init = previous_cost_history.cost

                ################################ Données Entrant modifiant le cout ###################################

                sm_in_ids = self.get_stock_move(node_to_compute.product_id, node_to_compute.location_id, 'in')
                returned_in_move_ids = sm_in_ids.get_returned_move()
                stock_move_ids += sm_in_ids
                sm_in_ids -= returned_in_move_ids['returned_move_ids']
                sm_in_ids -= returned_in_move_ids['return_move_ids']

                product_qty_in = sum(sm_in_ids.mapped('product_qty')) + product_qty_init
                product_value_in= sum(sm_in_ids.mapped('value') + sm_in_ids.mapped('landed_cost_value')) + product_value_init
                rounding = self.env.user.company_id.currency_id.rounding
                if float_is_zero(product_qty_in, precision_rounding=rounding):
                    price_unit = 0
                elif float_is_zero(product_value_in / product_qty_in, precision_rounding=rounding):
                    price_unit = 0
                else:
                    price_unit = product_value_in / product_qty_in

                ###################################### Mise à jour des sorties ############################################

                sm_out_ids = self.get_stock_move(node_to_compute.product_id, node_to_compute.location_id, 'out')
                returned_out_move_ids = sm_out_ids.get_returned_move()
                stock_move_ids += sm_out_ids
                sm_out_ids -= returned_out_move_ids['returned_move_ids']
                sm_out_ids -= returned_out_move_ids['return_move_ids']

                for sm_out_id in sm_out_ids:
                    sm_out_id.write({'price_unit': price_unit, 'value': price_unit*sm_out_id.product_qty})


                ###################################### Mise à jour des retours ############################################

                """sm out - Mise à jour des mouvements qui sont des retours"""
                # returned_out_move_ids['return_move_ids'].write({'price_unit': price_unit, 'value': price_unit*sm_out_id.product_qty})

                """sm out - Mise à jour des mouvements qui ont été retourné"""
                for sm_out_id in returned_out_move_ids['returned_move_ids']:
                    sm_out_id.write({'price_unit': price_unit, 'value': price_unit*sm_out_id.product_qty})
                    sm_out_id._update_stock_move_value()
                    # sm_out_id.update_account_entry_move()

                ###################################### Mise à jour historique des coût  ############################################

                end_qty = product_qty_in - sum(sm_out_ids.mapped('product_qty'))

                self.env['product.cost.history'].set_cost_history(node_to_compute.product_id, node_to_compute.location_id,
                                                                  self.date_to, end_qty, price_unit)

                _logger.info('cmp: %s  qty_end: %s' % (price_unit, end_qty))

                sm_out_ids._update_stock_move_value()
                sm_out_ids.update_account_entry_move()

        _logger.info('%s second to finalize the product cost average revaluation' % (timeit.timeit() - start))

        return stock_move_ids.get_excel_report()





