from odoo import api, fields, models
from datetime import datetime, timedelta

class ProjectProjectStage(models.Model):
    _inherit = 'project.project.stage'

    has_timesheet_reports = fields.Boolean('Has timesheet reports')