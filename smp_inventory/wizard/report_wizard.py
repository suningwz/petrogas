# -*- coding: utf-8 -*-
# © 2019 DisruptSol
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, api, fields, tools, _


class ReportWizard(models.TransientModel):
    _name = 'report.wizard'
    _description = "Table d'enregistrement des rapport téléchargeable"

    name = fields.Char(string='File Name')
    data = fields.Binary(string='Download Report')

