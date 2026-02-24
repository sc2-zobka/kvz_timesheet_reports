import logging
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, Command
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

MONTHS_SELECTION = [
    ("01", "January"),
    ("02", "February"),
    ("03", "March"),
    ("04", "April"),
    ("05", "May"),
    ("06", "June"),
    ("07", "July"),
    ("08", "August"),
    ("09", "September"),
    ("10", "October"),
    ("11", "November"),
    ("12", "December"),
]


class HrTimesheetReport(models.Model):
    _name = "hr.timesheet.report"
    _description = "Timesheet Report"
    _inherit = "mail.thread"
    _rec_name = "employee_id"

    # Constante para la categoría de aprobación
    CATEGORY_MONTHLY_REPORT_BY_SERVICE_PROVIDER_ID = 17
    CATEGORY_MONTHLY_REPORT_BY_EMPLOYEE_ID = 18
    OPERATION_DEPARTMENT_ID = 5

    active = fields.Boolean(string="Active", default=True)

    # Campos principales del reporte
    employee_id = fields.Many2one(
        "hr.employee", string="Talent", required=True, tracking=True
    )

    avatar_128 = fields.Image(related="employee_id.avatar_128")

    manager_user_id = fields.Many2one(
        "res.users",
        string="Head of Engineering",
        related="employee_id.parent_id.user_id",
        readonly=True,
        store=True,
    )
    timesheet_manager_id = fields.Many2one(
        "res.users",
        string="Project Manager",
        related="employee_id.timesheet_manager_id",
        readonly=True,
        store=True,
    )

    contract_type_id = fields.Many2one(
        "hr.contract.type",
        string="Contract Type",
        related="employee_id.contract_id.contract_type_id",
        store=True,
        readonly=True,
    )

    structure_type_id = fields.Many2one(
        "hr.payroll.structure.type",
        string="Salary Structure Type",
        related="employee_id.contract_id.structure_type_id",
        store=True,
        readonly=True,
    )

    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        related="employee_id.department_id",
        store=True,
        readonly=True,
    )

    month = fields.Selection(selection=MONTHS_SELECTION, string="Month", tracking=True)

    date_start = fields.Date(string="Start Date", tracking=True)
    date_end = fields.Date(string="End Date", tracking=True)

    # Relación uno a muchos con approval.request
    approval_request_ids = fields.One2many(
        "approval.request",
        "timesheet_report_id",
        string="Solicitudes de Aprobación",
        readonly=True,
    )

    request_status = fields.Selection(
        [
            ("new", "To Submit"),
            ("pending", "Submitted"),
            ("approved", "Approved"),
            ("refused", "Refused"),
            ("cancel", "Cancel"),
        ],
        string="Request Status",
        compute="_compute_request_status",
        store=True,
    )

    @api.depends("approval_request_ids.request_status")
    def _compute_request_status(self):
        for record in self:
            statuses = record.approval_request_ids.mapped("request_status")
            if not statuses:
                record.request_status = "new"
            elif "refused" in statuses:
                record.request_status = "refused"
            elif all(s == "approved" for s in statuses):
                record.request_status = "approved"
            elif "pending" in statuses:
                record.request_status = "pending"
            else:
                record.request_status = "new"

    approvers_summary = fields.Char(
        string="Approvers Summary",
        compute="_compute_approvers_summary",
        store=True,
    )

    @api.depends("approval_request_ids.approvers_summary")
    def _compute_approvers_summary(self):
        for record in self:
            summaries = record.approval_request_ids.filtered(
                lambda r: r.approvers_summary
            ).mapped("approvers_summary")
            record.approvers_summary = " | ".join(summaries)

    planned_hours = fields.Float(
        string="Planned Hours",
    )

    effective_hours = fields.Float(
        string="Effective Hours",
    )

    overtime = fields.Float(
        string="Extra Hours",
    )

    management_hours = fields.Float(
        string="Management Hours",
    )

    time_off_hours = fields.Float(
        string="Time Off Hours",
    )

    description = fields.Html()

    @api.model_create_multi
    def create(self, vals_list):
        """Sobrescribe el método create para crear automáticamente solicitudes de aprobación."""
        reports = super().create(vals_list)

        operation_department = self.env["hr.department"].browse(
            self.OPERATION_DEPARTMENT_ID
        )
        operation_manager = operation_department.manager_id
        if not operation_manager or not operation_manager.user_id:
            raise ValidationError(
                f'The department "{operation_department.name}" does not have a manager assigned '
                f"or the manager does not have an associated user. "
                f"Please configure the manager before creating timesheet reports."
            )

        for report, vals in zip(reports, vals_list):
            employee = self.env["hr.employee"].browse(vals.get("employee_id"))
            if not employee.user_id:
                raise ValidationError(
                    f"El empleado {employee.name} no tiene un usuario asociado."
                )

            category_id = (
                self.CATEGORY_MONTHLY_REPORT_BY_SERVICE_PROVIDER_ID
                if employee.contract_id.contract_type_id.id == 3
                else self.CATEGORY_MONTHLY_REPORT_BY_EMPLOYEE_ID
            )

            date_start = vals.get("date_start")
            date_end = vals.get("date_end")

            # Find unique project types from employee's timesheets in the period
            project_types = self.env["vx.project.type"]
            if date_start and date_end:
                timesheet_lines = self.env["account.analytic.line"].search(
                    [
                        ("employee_id", "=", employee.id),
                        ("date", ">=", date_start),
                        ("date", "<=", date_end),
                        ("project_id", "!=", False),
                    ]
                )
                project_types = timesheet_lines.mapped("project_id.type_id").filtered(
                    "id"
                )

            # One approval.request per project type (only that type's user_id as approver)
            for pt in project_types:
                if not pt.user_id:
                    continue
                pt_request = self.env["approval.request"].create(
                    {
                        "name": f"Solicitud de aprobación para {employee.name} - {pt.name}",
                        "request_owner_id": employee.user_id.id,
                        "category_id": category_id,
                        "timesheet_report_id": report.id,
                    }
                )
                existing_user_ids = set(pt_request.approver_ids.mapped("user_id.id"))
                if pt.user_id.id not in existing_user_ids:
                    pt_request.write(
                        {
                            "approver_ids": [
                                Command.create(
                                    {
                                        "user_id": pt.user_id.id,
                                        "status": "new",
                                        "required": False,
                                        "sequence": 10,
                                    }
                                )
                            ]
                        }
                    )

            # Always create a dedicated approval.request for the operation manager (sole approver)
            op_request = self.env["approval.request"].create(
                {
                    "name": f"Solicitud de aprobación para {employee.name} - Gerencia de Operaciones",
                    "request_owner_id": employee.user_id.id,
                    "category_id": category_id,
                    "timesheet_report_id": report.id,
                }
            )
            existing_user_ids = set(op_request.approver_ids.mapped("user_id.id"))
            if operation_manager.user_id.id not in existing_user_ids:
                op_request.write(
                    {
                        "approver_ids": [
                            Command.create(
                                {
                                    "user_id": operation_manager.user_id.id,
                                    "status": "new",
                                    "required": False,
                                    "sequence": 10,
                                }
                            )
                        ]
                    }
                )

        # Show records created in the logs for debugging
        for report in reports:
            for req in report.approval_request_ids:
                _logger.info(
                    'approval.request "%s" (id=%d) for employee "%s" — approvers: %s',
                    req.name,
                    req.id,
                    report.employee_id.name,
                    req.approver_ids.mapped("user_id.name") or "(none)",
                )

        return reports

    # Actualiza el reporte
    def action_update_report(self):
        for record in self:
            if not record.date_start or not record.date_end:
                raise ValidationError(
                    "El período (Fecha de inicio y Fecha de fin) debe estar definido."
                )

            # Obtener TODAS las líneas de timesheet sin filtros
            timesheet_lines = self.env["account.analytic.line"].search(
                [
                    ("employee_id", "=", record.employee_id.id),
                    ("date", ">=", record.date_start),
                    ("date", "<=", record.date_end),
                    ("project_id.stage_id.has_timesheet_reports", "=", True),
                ]
            )

            # Aplicar filtros en memoria con `.filtered()`
            validated_timesheet_lines = timesheet_lines.filtered(
                lambda l: l.validated and not l.project_id.is_internal_project
            )
            internal_project_lines = timesheet_lines.filtered(
                lambda l: l.project_id.is_internal_project
            )

            # Inicializar estructuras de datos para cada sección
            total_hours = {}
            internal_management_hours = {}
            internal_project_hours = {}

            # Procesar Secciones 1 y 2 (solo registros validados)
            for line in validated_timesheet_lines:
                project_id = line.project_id.id

                if line.project_id.type_id and line.project_id.type_id.id == 5:
                    # Sección 2: Internal Management
                    if project_id not in internal_management_hours:
                        internal_management_hours[project_id] = {
                            "type": line.project_id.type_id.name or "N/A",
                            "project": line.project_id.name or "N/A",
                            "effective_hours": 0.0,
                        }
                    internal_management_hours[project_id]["effective_hours"] += (
                        line.unit_amount
                    )

                else:
                    # Sección 1: Proyectos normales
                    if project_id not in total_hours:
                        total_hours[project_id] = {
                            "type": line.project_id.type_id.name or "N/A",
                            "project": line.project_id.name or "N/A",
                            "planned_hours": 0.0,
                            "effective_hours": 0.0,
                            "overtime": 0.0,
                        }

                    if line.is_overtime:
                        total_hours[project_id]["overtime"] += line.unit_amount
                    else:
                        total_hours[project_id]["effective_hours"] += line.unit_amount

            # Procesar Sección 3 (Proyectos internos, sin filtrar por `validated`)
            for line in internal_project_lines:
                task_id = line.task_id.id
                if task_id not in internal_project_hours:
                    internal_project_hours[task_id] = {
                        "task": line.task_id.name or "N/A",
                        "effective_hours": 0.0,
                    }
                internal_project_hours[task_id]["effective_hours"] += line.unit_amount

            # Agregar las Planned Hours desde project.task (asignadas al empleado)
            # Nota: en Odoo, la asignación en tareas es por usuarios (user_ids), no por employee_id.
            if not record.employee_id.user_id:
                raise ValidationError(
                    f"El empleado {record.employee_id.name} no tiene usuario asociado (user_id) para filtrar tareas asignadas."
                )

            tasks = self.env["project.task"].search(
                [
                    ("user_ids", "in", record.employee_id.user_id.id),
                    ("project_id", "!=", False),
                    ("date_deadline", ">=", record.date_start),
                    ("date_deadline", "<=", record.date_end),
                ]
            )

            for task in tasks:
                project_id = task.project_id.id
                if project_id in total_hours:
                    total_hours[project_id]["planned_hours"] += (
                        task.allocated_hours or 0.0
                    )

            # Redondear valores a 2 decimales
            for project_id, data in total_hours.items():
                data["planned_hours"] = round(data["planned_hours"], 2)
                data["effective_hours"] = round(data["effective_hours"], 2)
                data["overtime"] = round(data["overtime"], 2)

            for project_id, data in internal_management_hours.items():
                data["effective_hours"] = round(data["effective_hours"], 2)

            for task_id, data in internal_project_hours.items():
                data["effective_hours"] = round(data["effective_hours"], 2)

            # Calcular los totales generales para la sección 1
            totals = {
                "planned_hours": round(
                    sum(hours["planned_hours"] for hours in total_hours.values()), 2
                ),
                "effective_hours": round(
                    sum(hours["effective_hours"] for hours in total_hours.values()), 2
                ),
                "overtime": round(
                    sum(hours["overtime"] for hours in total_hours.values()), 2
                ),
                "management_hours": round(
                    sum(
                        hours["effective_hours"]
                        for hours in internal_management_hours.values()
                    ),
                    2,
                ),
                "time_off_hours": round(
                    sum(
                        hours["effective_hours"]
                        for hours in internal_project_hours.values()
                    ),
                    2,
                ),
            }

            # Guardar los totales en los campos correspondientes
            record.planned_hours = totals["planned_hours"]
            record.effective_hours = totals["effective_hours"]
            record.overtime = totals["overtime"]
            record.management_hours = sum(
                hours["effective_hours"] for hours in internal_management_hours.values()
            )
            record.time_off_hours = sum(
                hours["effective_hours"] for hours in internal_project_hours.values()
            )

            # Crear el contexto para el template
            header = {
                "employee": record.employee_id.name,
                "contract_type": record.contract_type_id.name or "N/A",
                "structure_type": record.structure_type_id.name or "N/A",
                "date_start": record.date_start.strftime("%Y-%m-%d"),
                "date_end": record.date_end.strftime("%Y-%m-%d"),
            }

            # Renderizar el template usando ir.qweb
            html = self.env[
                "ir.qweb"
            ]._render(
                "timesheet_reports.hr_timesheet_report_update_default_description",
                {
                    "header": header,
                    "totals": totals,
                    "total_lines": total_hours.values(),
                    "internal_management_lines": internal_management_hours.values(),
                    "internal_project_lines": internal_project_hours.values(),  # Tareas de la sección 3
                },
            )
            record.description = html

    # Envia el reporte
    def action_send_report(self):
        """Copia la descripción del reporte al campo 'reason' de cada approval_request
        y confirma las solicitudes de aprobación."""
        for record in self:
            if not record.approval_request_ids:
                raise ValidationError(
                    "No existe una solicitud de aprobación asociada a este reporte."
                )
            if not record.description:
                raise ValidationError("La descripción del reporte está vacía.")

            record.approval_request_ids.write({"reason": record.description})
            for approval_request in record.approval_request_ids:
                approval_request.action_confirm()

            # Publicar un mensaje de confirmación en el historial
            record.message_post(
                body="La descripción del reporte se ha enviado correctamente "
                "y la solicitud de aprobación se ha confirmado."
            )

    def create_employee_timesheet_reports(self):
        """Crea un Timesheets Report para cada empleado con contrato activo, usuario asociado y filtros específicos."""
        # Obtener la fecha actual y calcular las fechas del periodo actual
        today = date.today()
        current_period_start = today.replace(day=21) - relativedelta(months=1)
        current_period_end = today.replace(day=20)
        last_period_start = current_period_start.replace(day=21) - relativedelta(
            months=1
        )
        last_period_end = current_period_start.replace(day=20)

        # Filtrar empleados con contrato activo, usuario asociado, tipo de contrato específico y departamento padre específico
        active_employees_with_user = self.env["hr.employee"].search(
            [
                ("contract_id.state", "=", "open"),  # Contratos activos
                ("user_id", "!=", False),  # Con usuario asociado
                ("contract_id.contract_type_id.id", "!=", 3),  # Tipo de contrato
                ("department_id.parent_id.id", "=", 5),  # Departamento padre específico
            ]
        )

        if not active_employees_with_user:
            raise ValidationError(
                "No se encontraron empleados que cumplan con los criterios especificados."
            )

        # Archivar reportes de hace dos meses
        reports_to_archive = self.search(
            [("date_start", "=", last_period_start), ("date_end", "=", last_period_end)]
        )
        reports_to_archive.write({"active": False})

        # Crear nuevos reportes para el mes pasado
        reports_created = []
        for employee in active_employees_with_user:
            # Verificar si ya existe un reporte para este empleado y periodo
            existing_report = self.search(
                [
                    ("employee_id", "=", employee.id),
                    ("date_start", "=", current_period_start),
                    ("date_end", "=", current_period_end),
                ]
            )
            if existing_report:
                continue

            # Crear el reporte
            vals = {
                "employee_id": employee.id,
                "month": current_period_start.strftime("%m"),
                "date_start": current_period_start,
                "date_end": current_period_end,
            }
            report = self.create(vals)
            reports_created.append(report)

        return reports_created

    def create_service_provider_timesheet_reports(self):
        """Crea un Timesheets Report para cada empleado con contrato activo, usuario asociado y filtros específicos."""
        # Obtener la fecha actual y calcular las fechas del periodo actual
        today = date.today()
        first_day_current_month = today.replace(day=1)
        current_period_start = first_day_current_month - relativedelta(months=1)
        current_period_end = current_period_start + relativedelta(day=31)
        last_period_start = current_period_start - relativedelta(months=1)
        last_period_end = last_period_start + relativedelta(day=31)

        # Filtrar empleados con contrato activo, usuario asociado, tipo de contrato específico y departamento padre específico
        active_employees_with_user = self.env["hr.employee"].search(
            [
                ("contract_id.state", "=", "open"),  # Contratos activos
                ("user_id", "!=", False),  # Con usuario asociado
                ("contract_id.contract_type_id.id", "=", 3),  # Tipo de contrato
                "|",
                "|",
                "|",  # OR de 4 condiciones
                ("department_id.id", "=", 5),
                ("department_id.parent_id.id", "=", 5),
                ("department_id.id", "=", 26),
                ("department_id.parent_id.id", "=", 26),
            ]
        )

        if not active_employees_with_user:
            raise ValidationError(
                "No se encontraron empleados que cumplan con los criterios especificados."
            )

        # Archivar reportes de hace dos meses
        reports_to_archive = self.search(
            [("date_start", "=", last_period_start), ("date_end", "=", last_period_end)]
        )
        reports_to_archive.write({"active": False})

        # Crear nuevos reportes para el mes pasado
        reports_created = []
        for employee in active_employees_with_user:
            # Verificar si ya existe un reporte para este empleado y periodo
            existing_report = self.search(
                [
                    ("employee_id", "=", employee.id),
                    ("date_start", "=", current_period_start),
                    ("date_end", "=", current_period_end),
                ]
            )
            if existing_report:
                continue

            # Crear el reporte
            vals = {
                "employee_id": employee.id,
                "month": current_period_start.strftime("%m"),
                "date_start": current_period_start,
                "date_end": current_period_end,
            }
            report = self.create(vals)
            reports_created.append(report)

        return reports_created

    def create_service_provider_timesheet_reports_for_period(
        self, start_date_str, end_date_str
    ):
        """Crea un HrTimesheetReport para cada empleado con contrato activo, usuario asociado y filtros específicos en un período dado."""

        # Convertir las fechas de string a formato date
        try:
            current_period_start = datetime.strptime(start_date_str, "%d/%m/%Y").date()
            current_period_end = datetime.strptime(end_date_str, "%d/%m/%Y").date()
        except ValueError:
            raise ValidationError("Las fechas deben estar en el formato DD/MM/YYYY.")

        if current_period_start >= current_period_end:
            raise ValidationError(
                "La fecha de inicio debe ser anterior a la fecha de fin."
            )

        # Calcular el primer día del mes dos meses antes para archivar reportes
        last_period_start = current_period_start - relativedelta(months=1)
        last_period_end = last_period_start + relativedelta(day=31)

        # Filtrar empleados con contrato activo, usuario asociado, tipo de contrato específico y departamento padre específico
        active_employees_with_user = self.env["hr.employee"].search(
            [
                ("contract_id.state", "=", "open"),  # Contratos activos
                ("user_id", "!=", False),  # Con usuario asociado
                ("contract_id.contract_type_id.id", "=", 3),  # Tipo de contrato
                ("department_id.parent_id.id", "=", 5),  # Departamento padre específico
            ]
        )

        if not active_employees_with_user:
            raise ValidationError(
                "No se encontraron empleados que cumplan con los criterios especificados."
            )

        # Archivar reportes de hace dos meses
        reports_to_archive = self.search(
            [("date_start", "=", last_period_start), ("date_end", "=", last_period_end)]
        )
        reports_to_archive.write({"active": False})

        # Crear nuevos reportes para el período dado
        reports_created = []
        for employee in active_employees_with_user:
            # Verificar si ya existe un reporte para este empleado y periodo
            existing_report = self.search(
                [
                    ("employee_id", "=", employee.id),
                    ("date_start", "=", current_period_start),
                    ("date_end", "=", current_period_end),
                ]
            )
            if existing_report:
                continue

            # Crear el reporte
            vals = {
                "employee_id": employee.id,
                "month": current_period_start.strftime("%m"),
                "date_start": current_period_start,
                "date_end": current_period_end,
            }
            report = self.create(vals)
            reports_created.append(report)

        return reports_created
