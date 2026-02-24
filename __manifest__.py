{
    'name': 'Timesheet Reports by Period',
    'version': '1.4',
    'summary': 'Reports of hours by period and requests for approval.',
    'description': """
        Este módulo añade la opción de generar un reporte de horas por periodo y permite solicitar aprobación a travez del un flujo.
    """,
    'license': 'LGPL-3',
    'author': 'Kuvasz Solutions S.A.',
    'category': 'Timesheets',
    'depends': [
        'base',
        'project',
        'hr',
        'hr_contract',
        'hr_timesheet',
        'timesheet_grid',
        'project_overtime',
        'vx_project_template_types',
        'approvals'
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_timesheet_report_by_service_provider_view.xml',
        'views/hr_timesheet_report_by_employee_view.xml',
        'views/hr_timesheet_report_update_default_description.xml',
        'views/menu.xml',
        'views/project_project_stage.xml'

    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
