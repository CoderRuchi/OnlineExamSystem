from student import views as student
from . import views as faculty
from django.shortcuts import redirect
from django.contrib import messages

class ErrorHandlerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
            
            # Handle login required redirects more gracefully
            if response.status_code == 302 and 'login' in response.url:
                # Skip middleware for admin URLs
                if request.path.startswith('/admin/'):
                    return response
                    
                messages.warning(request, "Please login to access this page.")
                # Check if the request is from student section
                if request.path.startswith('/student/'):
                    return redirect('student:student_login')
                return redirect('faculty_login')
                
            # Handle other error responses
            if response.status_code in [400, 403, 404, 500]:
                # Skip middleware for admin URLs
                if request.path.startswith('/admin/'):
                    return response
                    
                if request.path.startswith('/student/'):
                    if response.status_code == 400:
                        return student.bad_request(request, None)
                    elif response.status_code == 403:
                        return student.permission_denied(request, None)
                    elif response.status_code == 404:
                        return student.page_not_found(request, None)
                    elif response.status_code == 500:
                        return student.server_error(request)
                else:
                    if response.status_code == 400:
                        return faculty.faculty_bad_request(request, None)
                    elif response.status_code == 403:
                        return faculty.faculty_permission_denied(request, None)
                    elif response.status_code == 404:
                        return faculty.faculty_page_not_found(request, None)
                    elif response.status_code == 500:
                        return faculty.faculty_server_error(request)
            
            return response
            
        except Exception as e:
            # Skip middleware for admin URLs
            if request.path.startswith('/admin/'):
                raise e
                
            # Check if the request is from student section
            if request.path.startswith('/student/'):
                return student.server_error(request)
            return faculty.faculty_server_error(request)