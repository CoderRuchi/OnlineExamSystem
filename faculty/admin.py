from django.contrib import admin
from .models import Faculty,Course,ExamSpecification,Student,Question
# Register your models here.
admin.site.register(Faculty)
admin.site.register(Course)
admin.site.register(ExamSpecification)
admin.site.register(Student)
admin.site.register(Question)

admin.site.site_header = 'Online Examination Portal'
admin.site.index_title = 'Managing Student Exams'