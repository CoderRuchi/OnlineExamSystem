from django.urls import path
from . import views
from faculty import views as faculty_views
app_name = 'student'
urlpatterns = [
    path('student_login/', views.student_login, name='student_login'),
    path('welcome/',views.welcome,name='welcome'),
    path("start-exam/<int:exam_id>/", views.start_exam, name="start_exam"),
    path("submit-exam/", views.submit_exam, name="submit_exam"),
    path("exam-result/<int:exam_id>/", views.exam_result, name="exam_result"),
    path("final-submit/<int:exam_id>/", views.final_submit, name="final_submit"),
    path("save-time/", views.save_remaining_time, name="save_remaining_time"),
    path('save-answers/', views.save_answer, name='save_answer'),
    path('get-saved-answers/', views.get_saved_answers, name='get_saved_answers'),
    path('save-current-question-index/', views.save_current_question_index, name='save_current_question_index'),
    path('get-current-question-index/', views.get_current_question_index, name='get_current_question_index'),
    path('check_session/', views.check_session, name='check_session'),
    path('logout-message/', views.logout_message, name='logout_message'),
    path('session_status/', views.session_status, name='session_status'),
    path('force_logout/<str:roll_no>/', faculty_views.force_logout, name='force_logout'),
]
