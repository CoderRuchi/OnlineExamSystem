# student/models.py
from django.db import models

class StudentPermissions(models.Model):
    class Meta:
        permissions = [
            ("can_view_student_dashboard", "Can view student dashboard"),
            ("can_start_exma", "Can start exam"),
            ("can_submit_exam","Can submit exam"),
        ]
