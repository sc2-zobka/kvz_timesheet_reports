from odoo import models, fields, api


class ApprovalRequest(models.Model):
    _inherit = 'approval.request'

    # Relación uno a uno con hr.timesheet.report
    timesheet_report_id = fields.Many2one(
        'hr.timesheet.report',
        string="Reporte de Parte de Horas",
        ondelete="set null"
    )

    approvers_summary = fields.Char(
        string='Approvers Summary',
        compute='_compute_approvers_summary',
        store=True
    )

    @api.depends('approver_ids.user_id', 'approver_ids.status')
    def _compute_approvers_summary(self):
        for record in self:
            if record.approver_ids:
                summary_list = [
                    f"{approver.user_id.name or 'Sin usuario'} ({dict(approver._fields['status'].selection).get(approver.status) or 'Sin estado'})"
                    for approver in record.approver_ids
                ]
                record.approvers_summary = ', '.join(summary_list)
            else:
                record.approvers_summary = ''    