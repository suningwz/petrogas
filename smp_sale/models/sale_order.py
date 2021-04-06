# -*- coding: utf-8 -*-
from datetime import date,timedelta
from odoo import models, fields, api, exceptions, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero, float_compare
from odoo.addons import decimal_precision as dp


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    regime_id = fields.Many2one('regime.douanier', string='Régime')
    location_id = fields.Many2one('stock.location', string='Location', domain=[('usage', '=', 'internal')])
    product_domain = fields.Char('Prduct Domain')
    sale_currency_id = fields.Many2one('res.currency', string='Devise', readonly=False)
    currency_rate = fields.Float('Currency rate', digits=(12, 6), default=1.0, readonly=False )
    currency_rate_visible = fields.Boolean('Currency rate visible')

    @api.onchange("currency_id")
    def _get_currency_rate_visible(self):
        if self.sale_currency_id:
            self.currency_rate_visible = False
            if self.sale_currency_id != self.env.user.company_id.currency_id:
                self.currency_rate_visible = True
    
    @api.onchange("currency_id")
    def _get_currency_rate(self):
        if self.currency_id:
            if self.currency_id != self.env.user.company_id.currency_id:
                from_currency = self.currency_id
                to_currency = self.env.user.company_id.currency_id
                company = self.env.user.company_id
                date = self.date_order
                currency_rate = self.env['res.currency']._get_conversion_rate(from_currency, to_currency, company, date)
                currency_rate = from_currency.rate
                self.currency_rate = currency_rate
            else:
                self.currency_rate = 1

    @api.onchange('partner_id')
    def onchange_partner_id(self):
        """
        Update the following fields when the partner is changed:
        - Pricelist
        - Payment terms
        - Invoice address
        - Delivery address
        """
        if not self.partner_id:
            self.update({
                'partner_invoice_id': False,
                'partner_shipping_id': False,
                'payment_term_id': False,
                'fiscal_position_id': False,
            })
            return

        addr = self.partner_id.address_get(['delivery', 'invoice'])
        values = {
            'pricelist_id': self.partner_id.property_product_pricelist and self.partner_id.property_product_pricelist.id or False,
            'regime_id': self.partner_id.default_regime_id and self.partner_id.default_regime_id.id or False,
            'location_id': self.partner_id.default_location_id and self.partner_id.default_location_id.id or False,
            'payment_term_id': self.partner_id.property_payment_term_id and self.partner_id.property_payment_term_id.id or False,
            'partner_invoice_id': addr['invoice'],
            'partner_shipping_id': addr['delivery'],
            'user_id': self.partner_id.user_id.id or self.partner_id.commercial_partner_id.user_id.id or self.env.uid
        }
        if self.env['ir.config_parameter'].sudo().get_param('sale.use_sale_note') and self.env.user.company_id.sale_note:
            values['note'] = self.with_context(lang=self.partner_id.lang).env.user.company_id.sale_note

        if self.partner_id.team_id:
            values['team_id'] = self.partner_id.team_id.id
        self.update(values)
        # self.write(values)

    @api.multi
    @api.onchange('pricelist_id', 'regime_id', 'location_id', 'date_order')
    def get_product(self):
        self.ensure_one()
        if self.pricelist_id:
            product_domain = self.pricelist_id.get_products(self.date_order)

            if all([self.pricelist_id, self.regime_id, self.location_id, self.date_order]):

                # TODO: Recupérer les article en vigueur dans la liste de prix
                if not product_domain:
                    raise exceptions.except_orm("Attention",
                                                """Aucun article n'a été trouvé dans la liste de prix du client""")

                # TODO: Récupérer product dans la matrice de prix
                price_sale_products = self.env['product.sale.price'].get_products(self.date_order, self.location_id,
                                                                                  self.regime_id)
                if not price_sale_products:
                    # message = """Aucun article n'a été trouvé dans la matrice des prix de vente
                    # ayant le régime %s , le dépôt %s et valide à la date %s""" % (self.regime_id.code,self.location_id.name,self.date_order)
                    # warning_mess = {'title': 'Aucun article trouvé !!!', 'message': message}
                    # return {'warning': warning_mess}
                    raise exceptions.except_orm("Attention","""Aucun article n'a été trouvé dans la matrice des prix de vente
                     ayant le régime %s , le dépôt %s et valide à la date %s""" % (self.regime_id.code,self.location_id.name,self.date_order))

                # TODO: Croiser les deux listes on garde que les élements qui sont dans la liste de prix et de la matrice
                product_domain = product_domain & price_sale_products
                if not product_domain:
                    if not product_domain:
                        raise exceptions.except_orm("Attention","""Les articles se trouvant dans la matrice de prix ne sont 
                        pas autorisé à la vente pour ce client""")



            # product_domain_no_structure = self.env[].search([('sale_ok','=',True), ('apply_price_structure','=','False')])
            product_domain_no_structure = self.pricelist_id.get_products(self.date_order)
            product_domain_no_structure = product_domain_no_structure.filtered(lambda x: x.product_tmpl_id.apply_price_structure == False )
            if product_domain_no_structure:
                product_domain = product_domain | product_domain_no_structure
            # TODO: Mettre à le context
            self.product_domain = product_domain.ids
            self = self.with_context(product_domain=tuple(product_domain.ids))

    @api.multi
    @api.onchange('date_order')
    def get_date_confirmation(self):
        self.ensure_one()
        if self.date_order:
            self.date_confirmation = self.date_order

    @api.multi
    def check_dma(self):
        self.ensure_one()
        dma = False
        debit_limit = self.partner_id.debit_limit
        credit = self.partner_id.credit
        sale_order_ids = self.search_read([('partner_id', '=', self.partner_id.id), ('state', '=', 'sale'),
                                           ('invoice_status', '=', 'to invoice')], ['amount_total'])
        sale_order_amount = self.amount_total + sum([ f['amount_total'] for f in sale_order_ids])
        if debit_limit - credit - sale_order_amount < 0 and self.payment_term_id != self.env.ref('account.account_payment_term_immediate'):
            dma = True
        return dma

    def invoice_due(self):
        self.ensure_one()
        invoice = False
        due_date = self._context.get('date') or fields.Date.context_today(self)
        invoice_count = self.env['account.invoice'].search_count([('partner_id', '=', self.partner_id.id),
                                                                  ('state', '=', 'open'),
                                                                  ('date_due', '<=', due_date)])
        if invoice_count != 0:
            invoice = True
        return invoice

    def payment_term(self):
        self.ensure_one()
        if self.payment_term_id.line_ids and self.payment_term_id.line_ids[0].days == 0:
            return False
        return True

    def user_location(self):
        self.ensure_one()
        print('check user location')

    def check_bc(self):
        res = {' Contrôle de DMA': "Le client a dépassé sa limite de crédit." if self.check_dma() else "Touts est correct.",
               'Contrôle des factures échues': "Le client possède des factures échues non payées. Veuillez régler les factures concernées." if self.invoice_due() else "Touts est correct."
               }
        return res

    def verify_group(self):
        """
        Check if the user has the access rigths to bypass the checkings to validate a sale order
        :return: Boolean
        """
        user = self.env.user
        group = self.env['res.groups'].search([('id', '=', self.env.ref('smp_sale.bc_validation_control').id)])
        print("Group BC: ", group.users)
        if user in group.users:
            return True
        return False

    def action_confirm(self):
        check_bc = self.check_bc()

        # Si False
        verify_group = self.verify_group()
        if not verify_group:
            # test_check = all([v for k,v in check_bc.items()])
            test = [v for k, v in check_bc.items()]
            if any([self.check_dma(), self.invoice_due()]):
                message = """ *** SALE ORDER VALIDATION CHECKING **** \n\n """
                for k, v in check_bc.items():
                    message += """ %s : %s \n""" % (k, v)
                raise UserError(message)
        res = super(SaleOrder, self).action_confirm()

        order_line_ids = self.order_line.filtered(lambda line: line.invoice_status == 'to_invoice')

        for picking in self.picking_ids.filtered(lambda x: x.state not in ('done','cancel')
                                                           and not x.to_be_confirmed_manually() ):

            if self.picking_policy == 'one' and all([move.product_uom_qty == move.reserved_availability for move in picking.move_lines]):
                for move in picking.move_lines.filtered(lambda m: m.state not in ['done', 'cancel']):
                    for move_line in move.move_line_ids:
                        move_line.qty_done = move_line.product_uom_qty
                # picking.action_done()
            elif self.picking_policy == 'direct':
                for move in picking.move_lines.filtered(lambda m: m.state not in ['done', 'cancel']):
                    for move_line in move.move_line_ids:
                        move_line.qty_done = move_line.product_uom_qty
                # picking.action_done()

        if self.order_line.filtered(lambda line: line.invoice_status != 'to_invoice'):
            invoice_ids = self.action_invoice_create(False, False)
            if invoice_ids:
                invoice_ids = self.env['account.invoice'].browse(invoice_ids)
                for invoice in invoice_ids:
                    invoice.sudo().action_invoice_open()
        # raise UserError('Arret processus')

        # if self.order_line.filtered(lambda line: line.invoice_status == 'no'):
        #     raise UserError("Certaine ne sont facturable que lorsque les Bons de Livraison les concernants seront effectivement livrés.")

        # for picking in self.picking_ids.filtered(lambda x: x.stock_move.product_id.):
        #     print('Confirmer les Bons de Livraisons')
        # for invoice in invoice_ids:
        #     print('Confirmer les factures')
        return res

    @api.multi
    def action_invoice_create(self, grouped=False, final=False):
        """
        Create the invoice associated to the SO.
        :param grouped: if True, invoices are grouped by SO id. If False, invoices are grouped by
                        (partner_invoice_id, currency)
        :param final: if True, refunds will be generated if necessary
        :returns: list of created invoices
        """
        inv_obj = self.env['account.invoice']
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        invoices = {}
        references = {}
        invoices_origin = {}
        invoices_name = {}

        # Keep track of the sequences of the lines
        # To keep lines under their section
        inv_line_sequence = 0
        for order in self:
            """ La clé de répartition est le bon de commande si groupé sinon c'est le partenaire et la devise"""
            # group_key = order.id if grouped else (order.partner_invoice_id.id, order.currency_id.id)
            if order.regime_id:
                group_key = order.id if grouped else (order.partner_invoice_id.id, order.currency_id.id, order.regime_id.id)
            else:
                group_key = order.id if grouped else (order.partner_invoice_id.id, order.currency_id.id)

            # We only want to create sections that have at least one invoiceable line
            pending_section = None

            # Create lines in batch to avoid performance problems
            line_vals_list = []
            # sequence is the natural order of order_lines
            for line in order.order_line:
            # for line in order.order_line:
                if line.display_type == 'line_section':
                    pending_section = line
                    continue
                if float_is_zero(line.qty_to_invoice, precision_digits=precision):
                    continue

                """ Si pas de facture selon la clé de répartition on crée la facture"""
                if group_key not in invoices:
                    inv_data = order._prepare_invoice()
                    invoice = inv_obj.create(inv_data)
                    if order.regime_id:
                        invoice.regime_id = order.regime_id
                    if order.payment_term_id:
                        invoice.payment_term_id = order.payment_term_id
                    references[invoice] = order
                    invoices[group_key] = invoice
                    invoices_origin[group_key] = [invoice.origin]
                    invoices_name[group_key] = [invoice.name]
                elif group_key in invoices:
                    if order.name not in invoices_origin[group_key]:
                        invoices_origin[group_key].append(order.name)
                    if order.client_order_ref and order.client_order_ref not in invoices_name[group_key]:
                        invoices_name[group_key].append(order.client_order_ref)

                """Création des lignes de facture"""
                if line.qty_to_invoice > 0 or (line.qty_to_invoice < 0 and final):
                    if pending_section:
                        section_invoice = pending_section.invoice_line_create_vals(
                            invoices[group_key].id,
                            pending_section.qty_to_invoice
                        )
                        inv_line_sequence += 1
                        section_invoice[0]['sequence'] = inv_line_sequence
                        line_vals_list.extend(section_invoice)
                        pending_section = None


                    picking_identification = True
                    if picking_identification:
                        stock_move_ids = line.move_ids.filtered(lambda r: r.state == 'done' and not r.scrapped and line.product_id == r.product_id)
                        picking_name = []
                        for move in stock_move_ids:
                            if move.picking_id.name not in picking_name:
                                picking_name.append(move.picking_id.name)
                        picking_name = ','.join(picking_name)


                    """ Facturation sur la base des quantité commandé"""
                    if line.product_id.invoice_policy == 'order':
                        if not line.qty_to_confirm:
                            stock_move_ids = line.move_ids.filtered(lambda r: r.state in('waiting', 'confirmed', 'assigned') and not r.scrapped and line.product_id == r.product_id)
                        else:
                            stock_move_ids = line.move_ids.filtered(
                                lambda r: r.state == 'done' and not r.scrapped and line.product_id == r.product_id)

                    """ Facturation sur la base des quantités livrés"""
                    if line.product_id.invoice_policy == 'delivery':
                        if line.qty_to_confirm:
                            stock_move_ids = line.move_ids.filtered(lambda r: r.state == 'done' and not r.scrapped and line.product_id == r.product_id)
                        else:
                            stock_move_ids = line.move_ids.filtered(lambda r: r.state in('waiting', 'confirmed', 'assigned') and not r.scrapped and line.product_id == r.product_id)



                    inv_line_sequence += 1
                    inv_line = line.invoice_line_create_vals(
                        invoices[group_key].id, line.qty_to_invoice
                    )
                    inv_line[0]['sequence'] = inv_line_sequence
                    if line.order_id.regime_id:
                        inv_line[0]['regime_id'] = line.order_id.regime_id.id
                    line_vals_list.extend(inv_line)

            if references.get(invoices.get(group_key)):
                if order not in references[invoices[group_key]]:
                    references[invoices[group_key]] |= order

            self.env['account.invoice.line'].create(line_vals_list)

        for group_key in invoices:
            invoices[group_key].write({'name': ', '.join(invoices_name[group_key]),
                                       'origin': ', '.join(invoices_origin[group_key])})
            sale_orders = references[invoices[group_key]]
            if len(sale_orders) == 1:
                invoices[group_key].reference = sale_orders.reference

        # if not invoices:
        #     raise UserError(_('There is no invoiceable line. If a product has a Delivered quantities invoicing policy, please make sure that a quantity has been delivered.'))

        for invoice in invoices.values():
            invoice.compute_taxes()
            if not invoice.invoice_line_ids:
                raise UserError(_('There is no invoiceable line. If a product has a Delivered quantities invoicing policy, please make sure that a quantity has been delivered.'))
            # If invoice is negative, do a refund invoice instead
            if invoice.amount_total < 0:
                invoice.type = 'out_refund'
                for line in invoice.invoice_line_ids:
                    line.quantity = -line.quantity
            # Use additional field helper function (for account extensions)
            for line in invoice.invoice_line_ids:
                line._set_additional_fields(invoice)
            # Necessary to force computation of taxes. In account_invoice, they are triggered
            # by onchanges, which are not triggered when doing a create.
            invoice.compute_taxes()
            # Idem for partner
            so_payment_term_id = invoice.payment_term_id.id
            fp_invoice = invoice.fiscal_position_id
            invoice._onchange_partner_id()
            invoice.fiscal_position_id = fp_invoice
            # To keep the payment terms set on the SO
            invoice.payment_term_id = so_payment_term_id
            invoice.message_post_with_view('mail.message_origin_link',
                values={'self': invoice, 'origin': references[invoice]},
                subtype_id=self.env.ref('mail.mt_note').id)
        return [inv.id for inv in invoices.values()]


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    qty_to_confirm = fields.Boolean('BL à confirmer', default=False)



    @api.depends('qty_invoiced', 'qty_delivered', 'product_uom_qty', 'order_id.state')
    def _get_to_invoice_qty(self):
        """
        Compute the quantity to invoice. If the invoice policy is order, the quantity to invoice is
        calculated from the ordered quantity. Otherwise, the quantity delivered is used.
        """
        for line in self:
            if line.order_id.state in ['sale', 'done']:
                if line.product_id.invoice_policy == 'order':
                    if line.qty_to_confirm:
                        line.qty_to_invoice = line.qty_delivered - line.qty_invoiced
                    else:
                        line.qty_to_invoice = line.product_uom_qty - line.qty_invoiced
                else:
                    line.qty_to_invoice = line.qty_delivered - line.qty_invoiced
            else:
                line.qty_to_invoice = 0

    @api.model
    def get_product_domain(self):
        print(' sale order 1 product domain: ', self.order_id.product_domain)
        print('Context sale order 1: ', self.order_id.env.context)
        print('Context sale order line 1: ', self.env.context)
        # product_domain = self.env.context.get('product_domain', False)
        product_domain = self.order_id.product_domain
        if product_domain:
            product_domain = tuple(int(x) for x in product_domain[1:-1].split(','))
            self = self.with_context(product_domain=product_domain)
            return {'domain': {'product_id': [('id', 'in', product_domain)]}}

    @api.onchange('product_id')
    def product_id_change(self):
        domain = super(SaleOrderLine, self).product_id_change()
        if not self.product_id:
            return self.get_product_domain()

        vals = {}
        # TODO : Rajouter unité pour chaque valeur de prix dans la matrice de prix
        domain = {'product_uom': [('category_id', '=', self.product_id.uom_id.category_id.id)]}
        result = {'domain': domain}

        if not self.product_uom or (self.product_id.uom_id.id != self.product_uom.id):
            vals['product_uom'] = self.product_id.uom_id
            vals['product_uom_qty'] = self.product_uom_qty or 1.0

        product = self.product_id.with_context(
                lang=self.order_id.partner_id.lang,
                partner=self.order_id.partner_id,
                quantity=vals.get('product_uom_qty') or self.product_uom_qty,
                date=self.order_id.date_order,
                pricelist=self.order_id.pricelist_id.id,
                uom=self.product_uom.id,
                regime=self.order_id.regime_id.id,
                location=self.order_id.location_id.id,
                transport_type=self.order_id.transport_type and self.order_id.transport_type.id or False,
            )

        name = self.get_sale_order_line_multiline_description_sale(product)

        vals.update(name=name)

        self._compute_tax_id()

        # if self.order_id.pricelist_id and self.order_id.partner_id:
        if all([self.order_id.pricelist_id, self.order_id.partner_id, not self.order_id.regime_id,
               not self.order_id.location_id]):
            price = self._get_display_price(product)
            # price = 0.25

            vals['price_unit'] = self.env['account.tax']._fix_tax_included_price_company(price,
                                                                                         product.taxes_id,
                                                                                         self.tax_id,
                                                                                         self.company_id)

        if self.order_id.currency_id != self.order_id.pricelist_id.currency_id:
            vals['price_unit'] = self.price_unit * self.currency_rate                                                               
        self.update(vals)

        title = False
        message = False
        warning = {}
        if product.sale_line_warn != 'no-message':
            title = _("Warning for %s") % product.name
            message = product.sale_line_warn_msg
            warning['title'] = title
            warning['message'] = message
            result = {'warning': warning}
            if product.sale_line_warn == 'block':
                self.product_id = False

        if product.apply_price_structure:
            sale_price_id = self.env['product.sale.price'].get_specific_records(self.order_id.date_order,
                                                                              self.product_id,
                                                                              self.order_id.location_id,
                                                                              self.order_id.regime_id)
            if sale_price_id and sale_price_id.quantity_to_confirm:
                self.qty_to_confirm = sale_price_id.quantity_to_confirm

        return result

    @api.onchange('product_uom', 'product_uom_qty')
    def product_uom_change(self):
        self = self.with_context(regime_id= self.order_id.regime_id.id,
                                 location_id= self.order_id.location_id.id,
                                 transport_type=self.order_id.transport_type and self.order_id.transport_type.id or False,)
        res = super(SaleOrderLine, self).product_uom_change()

        # if not self.product_uom or not self.product_id:
        #     self.price_unit = 0.0
        #     return
        # if self.order_id.pricelist_id and self.order_id.partner_id:
        #     product = self.product_id.with_context(
        #         lang=self.order_id.partner_id.lang,
        #         partner=self.order_id.partner_id,
        #         quantity=self.product_uom_qty,
        #         date=self.order_id.date_order,
        #         pricelist=self.order_id.pricelist_id.id,
        #         uom=self.product_uom.id,
        #         fiscal_position=self.env.context.get('fiscal_position')
        #     )
            # self.price_unit = self.env['account.tax']._fix_tax_included_price_company(
            #     self._get_display_price(product), product.taxes_id, self.tax_id, self.company_id)

    @api.multi
    def _get_display_price(self, product):
        # base_price, final_price = super(SaleOrderLine, self)._get_display_price(product)

        if self.order_id.location_id:
            product = product.with_context(location_id=self.order_id.location_id.id)
        if self.order_id.regime_id:
            product = product.with_context(regime_id=self.order_id.regime_id.id)

        if self.order_id.pricelist_id.discount_policy == 'with_discount':
            price = product.with_context(pricelist=self.order_id.pricelist_id.id).price
            # return product.with_context(pricelist=self.order_id.pricelist_id.id).price
            return price
        product_context = dict(self.env.context, partner_id=self.order_id.partner_id.id, date=self.order_id.date_order, uom=self.product_uom.id)

        final_price, rule_id = self.order_id.pricelist_id.with_context(product_context).get_product_price_rule(self.product_id, self.product_uom_qty or 1.0, self.order_id.partner_id)
        base_price, currency = self.with_context(product_context)._get_real_price_currency(product, rule_id,
                                               self.product_uom_qty, self.product_uom, self.order_id.pricelist_id.id)
        if currency != self.order_id.pricelist_id.currency_id:
            base_price = currency._convert(
                base_price, self.order_id.pricelist_id.currency_id,
                self.order_id.company_id or self.env.user.company_id, self.order_id.date_order or fields.Date.today())
        # negative discounts (= surcharge) are included in the display price
        return max(base_price, final_price)

    @api.multi
    def get_product_sale_price(self):
        self.ensure_one()
        sale_price_id = False

        if self.product_id.type == 'product' and self.product_id.apply_price_structure \
                and self.order_id.regime_id and self.order_id.location_id:

            sale_price_id = self.env['product.sale.price'].get_specific_records(self.order_id.date_order,
                                                                              self.product_id,
                                                                              self.order_id.location_id,
                                                                              self.order_id.regime_id)

        return sale_price_id

    @api.multi
    def invoice_line_create_vals(self, invoice_id, qty):

        domain = []

        self.mapped('move_ids').filtered(lambda x: x.state in domain
                                                   and not x.invoice_line_id
                                                   and not x.location_dest_id.scrap_location
                                                   and x.location_dest_id.usage == 'customer'
                                         ).mapped('picking_id').write({'invoice_ids': [(4, invoice_id)]})
        return super(SaleOrderLine, self).invoice_line_create_vals(invoice_id, qty)

    @api.multi
    def _prepare_invoice_line(self, qty):
        vals = super(SaleOrderLine, self)._prepare_invoice_line(qty)

        domain = []

        move_ids = self.mapped('move_ids').filtered(
            lambda x: x.state in domain and
            not x.invoice_line_id and
            not x.scrapped and (
                x.location_dest_id.usage == 'customer' or
                (x.location_id.usage == 'customer' and
                 x.to_refund)
            )).ids
        vals['move_line_ids'] = [(6, 0, move_ids)]
        return vals

    # @api.multi
    # def _get_real_price_currency(self, product, rule_id, qty, uom, pricelist_id):
    #     """Retrieve the price before applying the pricelist
    #         :param obj product: object of current product record
    #         :parem float qty: total quentity of product
    #         :param tuple price_and_rule: tuple(price, suitable_rule) coming from pricelist computation
    #         :param obj uom: unit of measure of current order line
    #         :param integer pricelist_id: pricelist id of sales order"""
    #     PricelistItem = self.env['product.pricelist.item']
    #     field_name = 'lst_price'
    #     # currency_id = None
    #     currency_id = self.order_id.currency_id
    #     pricelist_currency_id = self.pricelist_id.currency_id
    #     product_currency = None
    #     if rule_id:
    #         pricelist_item = PricelistItem.browse(rule_id)
    #         if pricelist_item.pricelist_id.discount_policy == 'without_discount':
    #             while pricelist_item.base == 'pricelist' and pricelist_item.base_pricelist_id and pricelist_item.base_pricelist_id.discount_policy == 'without_discount':
    #                 price, rule_id = pricelist_item.base_pricelist_id.with_context(uom=uom.id).get_product_price_rule(product, qty, self.order_id.partner_id)
    #                 pricelist_item = PricelistItem.browse(rule_id)

    #         if pricelist_item.base == 'standard_price':
    #             field_name = 'standard_price'
    #         if pricelist_item.base == 'pricelist' and pricelist_item.base_pricelist_id:
    #             field_name = 'price'
    #             product = product.with_context(pricelist=pricelist_item.base_pricelist_id.id)
    #             product_currency = pricelist_item.base_pricelist_id.currency_id
    #         pricelist_currency_id = pricelist_item.pricelist_id.currency_id

    #     product_currency = product_currency or(product.company_id and product.company_id.currency_id) or self.env.user.company_id.currency_id
    #     if currency_id == pricelist_currency_id:
    #         cur_factor = 1.0
    #     else:
    #         cur_factor = self.order_id.currency_rate

    #     product_uom = self.env.context.get('uom') or product.uom_id.id
    #     if uom and uom.id != product_uom:
    #         # the unit price is in a different uom
    #         uom_factor = uom._compute_price(1.0, product.uom_id)
    #     else:
    #         uom_factor = 1.0

        

    #     return product[field_name] * uom_factor * cur_factor, currency_id
