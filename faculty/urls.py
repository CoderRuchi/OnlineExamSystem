from django.urls import path
from . import views

urlpatterns = [
    path('',views.index,name='index'),
    path('about/',views.about,name='about'),
    path('contact/',views.contact,name='contact'),
    # Faculty authentication
    path('register/',views.faculty_register,name='faculty_register'),
    path('faculty_login/', views.faculty_login, name='faculty_login'),
    path('logout/', views.faculty_logout, name='faculty_logout'),
    # Dashboard
    path('dashboard/', views.faculty_dashboard, name='faculty_dashboard'),
    path('view_student/',views.view_student,name='view_student'),
    path('add_student',views.add_student,name='add_student'),
    # Course management
    path('add_course/', views.add_course, name='add_course'),
    path("delete-course/<int:course_id>/", views.delete_course, name="delete_course"),
    path("truncate-courses/", views.truncate_courses, name="truncate_courses"),
    path("update_course/<int:course_id>/",views.update_course,name="update_course"),
    #specification management
    path('add_exam_specifications/', views.add_exam_specifications, name='add_exam_specifications'),
    path('delete_exam_specification/<int:spec_id>/',views.delete_exam_specification,name='delete_exam_specification'),
    path('truncate_specifications/',views.truncate_specifications,name='truncate_specifications'),
    path('update_specifications/<int:spec_id>/',views.update_specifications,name='update_specifications'),
    # Student management
    path('upload_students/', views.upload_students, name='upload_students'),
    path('view-students/', views.view_students, name='view_students'),
    path('truncate_students/',views.truncate_students,name='truncate_students'),
    path('update-student-password/', views.update_student_password, name='update_student_password'),
    path('reset-student-password/', views.reset_student_password, name='reset_student_password'),
    path('save-attendance/', views.save_attendance, name='save_attendance'),
    path('update_attendance',views.update_attendance,name='update_attendance'),
    # Question management
    path('upload_questions/', views.upload_questions, name='upload_questions'),
    path('questions/', views.manage_questions, name='manage_questions'),
    path('truncate_questions/',views.truncate_questions,name='truncate_questions'),

    #preview exam
    path('preview_exam/<int:exam_id>/', views.preview_exam, name='preview_exam'),
    #exam management
    path('take-exam/', views.take_exam, name='take_exam'),
    path('end_exam/', views.end_exam, name='end_exam'),
    path('exam_data',views.exam_data,name='exam_data'),
    #result display
    path('view-results/', views.view_results, name='view_results'),
    path('api/get-pending-students/', views.get_pending_students, name='get_pending_students'),
    path('api/get-exam-stats/', views.get_exam_stats, name='get_exam_stats'),
    # force logout
    path('force-logout/<str:roll_no>/', views.force_logout, name='force_logout'),
    ]
