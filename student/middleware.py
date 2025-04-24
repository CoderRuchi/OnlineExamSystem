from django.contrib.sessions.models import Session
from django.utils import timezone
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import logout

class SingleSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and hasattr(request.user, 'student'):
            current_session_key = request.session.session_key
            
            # Get all active sessions for the user
            user_sessions = Session.objects.filter(
                expire_date__gte=timezone.now(),
                session_data__contains=str(request.user.pk)
            ).exclude(session_key=current_session_key)

            # If other sessions exist, terminate all sessions including current one
            if user_sessions.exists():
                # Delete all sessions for this user
                user_sessions.delete()
                
                # Clear current session
                request.session.flush()
                logout(request)
                
                # Redirect to login with message
                messages.error(request, "Multiple login detected. Please login again.")
                return redirect('student:student_login')

        response = self.get_response(request)
        return response

# Comment out or remove the other middleware classes



