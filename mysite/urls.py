"""
URL configuration for mysite project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('faculty.urls')),
    path('student/', include('student.urls')),
    # Remove the favicon redirect and let Django's static files handle it
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


# Use faculty error handlers for faculty URLs and student error handlers for student URLs
if not settings.DEBUG:
    handler400 = 'faculty.views.faculty_bad_request'
    handler403 = 'faculty.views.faculty_permission_denied'
    handler404 = 'faculty.views.faculty_page_not_found'
    handler500 = 'faculty.views.faculty_server_error'
