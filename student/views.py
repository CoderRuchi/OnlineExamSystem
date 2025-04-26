from datetime import timedelta
import os
from django.contrib.auth import login, logout
import json
import random
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.utils.timezone import now
from django.utils import timezone
from faculty.models import Course, Student, Question,ExamSpecification,Result
from django.utils.timezone import now, make_aware
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
def student_login(request):
    if request.method == "POST":
        username = request.POST.get('name')
        password = request.POST.get('password')

        print(f"Login attempt - Username: {username}, Password: {password}")

        # First try normal authentication
        user = authenticate(request, username=username, password=password)
        print(f"Authenticate returned: {user}")

        if user is None:
            # Authentication failed - check if it's because the user exists but password is not properly hashed
            try:
                student_user = User.objects.get(username=username)
                print(f"User exists: {student_user}")

                if hasattr(student_user, 'student'):
                    # Check if the student model has the same password (plaintext comparison)
                    student = student_user.student
                    if student.password == password:
                        print("Password matches in Student model but not in User model - fixing...")
                        # Fix the User password to match the Student password
                        student_user.set_password(password)
                        student_user.save()
                        print("User password updated to match Student password")

                        # Now authenticate with the updated password
                        user = authenticate(request, username=username, password=password)
                        if not student.attendance_status:
                            messages.error(request, "You are marked absent and cannot take the exam.")
                            return redirect("student:student_login")
                        if user:
                            auth_login(request, user)
                            request.session['last_activity'] = str(timezone.now())
                            return redirect("student:welcome")
                        else:
                            messages.error(request, "Authentication error after password update. Please try again.")
                    else:
                        messages.error(request, "Invalid password. Please try again.")
                else:
                    messages.error(request, "Not a student account.")
            except User.DoesNotExist:
                messages.error(request, "Account not found.")
            return redirect("student:student_login")

        # Check for active sessions
        active_sessions = Session.objects.filter(
            expire_date__gte=timezone.now()
        )

        for session in active_sessions:
            session_data = session.get_decoded()
            if str(user.pk) == session_data.get('_auth_user_id', ''):
                messages.error(request, "You are already logged in elsewhere.")
                return render(request, 'student/student_login.html', {'login_blocked': True})

        # Login successful
        auth_login(request, user)
        request.session['last_activity'] = str(timezone.now())

        # Handle exam logic
        student = user.student
        if student.exam_start_time and not student.has_attempted_exam:
            active_exam = ExamSpecification.objects.filter(
                course_code__in=student.registered_courses.values_list('code', flat=True),
                is_active=True
            ).first()
            if active_exam:
                return redirect("student:start_exam", exam_id=active_exam.id)

        return redirect("student:welcome")

    # If already logged in, redirect to welcome
    if request.user.is_authenticated and hasattr(request.user, 'student'):
        return redirect("student:welcome")

    return render(request, 'student/student_login.html')

@csrf_exempt
def session_status(request):
    response_data = {
        'active': False,
        'valid': False,
        'message': ''
    }

    if request.user.is_authenticated and hasattr(request.user, 'student'):
        try:
            # Verify current session exists
            session = Session.objects.get(
                session_key=request.session.session_key,
                expire_date__gte=timezone.now()
            )

            # Additional verification of session data
            session_data = session.get_decoded()
            if str(request.user.pk) == session_data.get('_auth_user_id', ''):
                response_data['active'] = True
                response_data['valid'] = True
            else:
                response_data['message'] = "Session user mismatch"
        except Session.DoesNotExist:
            response_data['message'] = "Session expired"

    return JsonResponse(response_data)

@csrf_exempt
def check_session(request):
    if not request.user.is_authenticated or not hasattr(request.user, 'student'):
        return JsonResponse({'valid': False})

    # Check if current session is still valid
    try:
        current_session = Session.objects.get(
            session_key=request.session.session_key,
            expire_date__gte=timezone.now()
        )
        return JsonResponse({'valid': True})
    except Session.DoesNotExist:
        return JsonResponse({'valid': False})

def logout_message(request):
    return render(request, 'student/logout_message.html', {
        'message': 'You have been logged out by faculty. Please login again to resume your exam.'
    })

# Welcome Page
@login_required
def welcome(request):
    student = request.user.student  # Access the linked Student profile
        # Fetch the student's registered courses
    registered_courses = student.registered_courses.all()
    # Fetch the branch (assuming the branch is stored in the Course model)
    # If the student is registered in multiple courses, pick the first one or handle accordingly
    branch = student.branch
          # Fetch scheduled exams for the student's registered courses
    scheduled_exams = ExamSpecification.objects.filter(
        course_code__in=[course.code for course in registered_courses],
        is_active=True    # Only fetch active exams
    )
    context = {
        "student_name": student.name,
        "student_rollno": student.roll_no,
        "branch": branch,
        "scheduled_exams": scheduled_exams,
    }
    return render(request, 'student/welcome.html', context)

# Start Exam
@login_required
def start_exam(request, exam_id):
    student = request.user.student
    if not student:
        messages.error(request, "Student profile not found.")
        return redirect("student:student_login")
     # Check attendance status
    if not student.attendance_status:
        messages.error(request, "You are marked absent and cannot take this exam.")
        return redirect("student:student_login")

    try:
        exam = ExamSpecification.objects.get(id=exam_id)
    except ExamSpecification.DoesNotExist:
        messages.error(request, "Invalid exam ID.")
        return redirect("student:welcome")

    # Calculate total exam duration in seconds ONCE
    exam_duration_seconds = (exam.exam_duration_hours * 3600) + (exam.exam_duration_minutes * 60)
    print(f"Exam duration: {exam_duration_seconds} seconds")

    # If student already completed exam, redirect to results
    if student.has_attempted_exam:
        return redirect("student:exam_result", exam_id=exam_id)

    # Initialize session keys
    exam_session_key = f'exam_{exam_id}_started'
    current_question_key = f'exam_{exam_id}_current_question_index'

    # FIRST-TIME EXAM START LOGIC
    if exam_session_key not in request.session:
        # Initialize session
        request.session[exam_session_key] = True
        request.session[current_question_key] = 0
        request.session.modified = True

        # Initialize exam timing
        if not student.exam_start_time:
            student.exam_start_time = timezone.now()
            student.time_remaining = exam_duration_seconds
            student.has_attempted_exam = False
            student.save()
            print(f"Initialized new exam with {exam_duration_seconds} seconds remaining")

    # Ensure current question index exists
    if current_question_key not in request.session:
        request.session[current_question_key] = 0

    # Handle JSON file operations
    try:
        exam_directory = os.path.join("C:\\", f"exam_{exam_id}_{exam.exam_name.replace(' ', '_')}")
        student_json_file = os.path.join(exam_directory, f"{student.roll_no}.json")

        with open(student_json_file, 'r') as json_file:
            student_data = json.load(json_file)

        questions = student_data.get("Question_Bank", [])
        print(questions)
        if not questions:
            messages.error(request, "No questions found in the question bank.")
            return redirect("student:welcome")

        # Format questions and collect previous answers
        formatted_questions = []
        previous_answers = {}
        for q in questions:
            formatted_questions.append({
                "q_id": q["q_id"],
                "question_text": q["question_text"],
                "latex_equation": q.get("latex_equation", ""),
                "option_1": q["option_1"],
                "option_2": q["option_2"],
                "option_3": q["option_3"],
                "option_4": q["option_4"],
                "marks": q["marks"],
                "image_path": q.get("image_path", None),
                "unit_no": q.get("unit_no", 0) # Displays unit number
            })
            if "student_c_ans" in q and q["student_c_ans"]:
                previous_answers[str(q["q_id"])] = q["student_c_ans"]

        # Ensure time_remaining is properly set (double-check)
        if student.time_remaining is None or student.time_remaining <= 0:
            student.time_remaining = exam_duration_seconds
            student.save()
            print(f"Reset invalid time_remaining to {exam_duration_seconds}")

        remaining_time = student.time_remaining
        print(f"Current remaining time: {remaining_time} seconds")

        return render(request, "student/exam.html", {
            "exam": exam,
            "remaining_time": remaining_time,
            "questions_json": json.dumps(formatted_questions),
            "previous_answers": json.dumps(previous_answers),
            "student_name": student.name
        })

    except Exception as e:
        print(f"Error setting up exam: {str(e)}")
        messages.error(request, "Error setting up exam. Please try again.")
        return redirect("student:welcome")
    
@csrf_exempt
def save_current_question_index(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            current_index = data.get('current_index')
            exam_id = data.get('exam_id')

            if current_index is None:
                return JsonResponse({'success': False, 'error': 'current_index is required'}, status=400)

            # Use exam-specific key if exam_id is provided
            if exam_id:
                key = f'exam_{exam_id}_current_question_index'
            else:
                key = 'current_question_index'

            # Update the session with the current question index
            request.session[key] = current_index
            request.session.modified = True  # Ensure the session is saved
            print(f"Saved question index {current_index} with key {key}")

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

@csrf_exempt
def get_current_question_index(request):
    if request.method == 'GET':
        try:
            exam_id = request.GET.get('exam_id')

            # Use exam-specific key if exam_id is provided
            if exam_id:
                key = f'exam_{exam_id}_current_question_index'
            else:
                key = 'current_question_index'

            # Fetch the current question index from the session
            current_index = request.session.get(key, 0)
            print(f"Retrieved question index {current_index} with key {key}")

            return JsonResponse({'success': True, 'current_index': current_index})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

import logging
from django.db import transaction, IntegrityError
@login_required
def submit_exam(request):
    if request.method == "POST":
        try:
            # Parse the request data
            data = json.loads(request.body)
            student = request.user.student
            exam_id = data.get("exam_id")
            selected_answers = data.get("answers", {})

            # Validate student
            if not student:
                return JsonResponse({"error": "Unauthorized access"}, status=403)

            # Check if the student has already attempted the exam
            if student.has_attempted_exam:
                return JsonResponse({"error": "Exam already submitted."}, status=400)

            # Get the exam
            try:
                exam = ExamSpecification.objects.get(
                    id=exam_id,
                    is_active=True,
                    course_code__in=student.registered_courses.values_list('code', flat=True)
                )
            except ExamSpecification.DoesNotExist:
                return JsonResponse({"success": False, "error": "Invalid or inactive exam"})

            # Define the path to the student's JSON file
            exam_directory = os.path.join("C:\\", f"exam_{exam_id}_{exam.exam_name.replace(' ', '_')}")
            student_json_file = os.path.join(exam_directory, f"{student.roll_no}.json")

            # Read the current JSON file
            with open(student_json_file, 'r') as json_file:
                student_data = json.load(json_file)

            # Update the answers and calculate gained marks
            gained_marks = 0
            for question in student_data["Question_Bank"]:
                q_id = str(question["q_id"])
                if q_id in selected_answers:
                    question["student_c_ans"] = selected_answers[q_id]
                    # Update student_answer_text based on the selected answer
                    if selected_answers[q_id] == "A":
                        question["student_answer_text"] = question["option_1"]
                    elif selected_answers[q_id] == "B":
                        question["student_answer_text"] = question["option_2"]
                    elif selected_answers[q_id] == "C":
                        question["student_answer_text"] = question["option_3"]
                    elif selected_answers[q_id] == "D":
                        question["student_answer_text"] = question["option_4"]

                    # Calculate gained marks - CORRECTED LOGIC
                    correct_answer = question["correct_answer"]
                    user_answer = selected_answers[q_id]
                    if user_answer:  # Only check if answer was attempted
                        if (user_answer == "A" and correct_answer == question["option_1"]) or \
                           (user_answer == "B" and correct_answer == question["option_2"]) or \
                           (user_answer == "C" and correct_answer == question["option_3"]) or \
                           (user_answer == "D" and correct_answer == question["option_4"]):
                            gained_marks += int(question["marks"])

            # Write the updated JSON back to the file
            with open(student_json_file, 'w') as json_file:
                json.dump(student_data, json_file, indent=4)

            # Update student's exam status
            student.has_attempted_exam = True
            student.save()

            exam_details = student_data["Exam_Details"]
            assigned_questions = student_data["Question_Bank"]

            # Calculate total marks and percentage
            total_marks_exam = exam.total_marks
            percentage = (gained_marks / total_marks_exam) * 100 if total_marks_exam > 0 else 0
            passing_percentage = 40
            status = "Pass" if percentage >= passing_percentage else "Fail"

            # Prepare detailed question data
            question_list = []
            for q in assigned_questions:
                question_mark = int(q["marks"])
                user_answer = q.get("student_c_ans", "")
                
                student_answer_text = "Not Attempted"
                if user_answer:
                    if user_answer == "A":
                        student_answer_text = q["option_1"]
                    elif user_answer == "B":
                        student_answer_text = q["option_2"]
                    elif user_answer == "C":
                        student_answer_text = q["option_3"]
                    elif user_answer == "D":
                        student_answer_text = q["option_4"]

                # Correct answer check - same logic as above
                correct_answer = q["correct_answer"]
                is_correct = False
                if user_answer:  # Only check if answer was attempted
                    is_correct = (user_answer == "A" and correct_answer == q["option_1"]) or \
                                (user_answer == "B" and correct_answer == q["option_2"]) or \
                                (user_answer == "C" and correct_answer == q["option_3"]) or \
                                (user_answer == "D" and correct_answer == q["option_4"])

                question_list.append({
                    "q_id": q["q_id"],
                    "question_text": q["question_text"],
                    "latex_equation": q.get("latex_equation", ""),
                    "option_1": q["option_1"],
                    "option_2": q["option_2"],
                    "option_3": q["option_3"],
                    "option_4": q["option_4"],
                    "correct_answer": q["correct_answer"],
                    "student_answer": user_answer if user_answer else "Not Attempted",
                    "student_answer_text": student_answer_text,
                    "is_correct": is_correct
                })

            # Prepare the complete result data
            result_data = {
                "student_name": exam_details["student_name"],
                "roll_no": exam_details["roll_no"],
                "course_name": exam_details["course_name"],
                "course_code": exam_details["course_code"],
                "branch": exam_details["branch"],
                "year": exam_details["year"],
                "total_questions": exam_details["max_question"],
                "attempted_questions": len([q for q in assigned_questions if q.get("student_c_ans")]),
                "total_marks": total_marks_exam,
                "gained_marks": gained_marks,
                "percentage": round(percentage, 2),
                "status": status,
                "question_list": question_list,
                "result_summary": {
                    "total_marks": total_marks_exam,
                    "obtained_marks": gained_marks,
                    "percentage": round(percentage, 2),
                    "status": status,
                    "passing_percentage": passing_percentage
                }
            }

            # Update existing Result object (don't create new one)
            result = Result.objects.filter(student=student, exam=exam).first()
            if result:
                result.obtained_marks = gained_marks
                result.percentage = percentage
                result.status = status
                result.submitted_at = timezone.now()
                result.save()
            else:
                # Fallback in case result doesn't exist (shouldn't happen)
                result = Result.objects.create(
                    student=student,
                    exam=exam,
                    total_marks=total_marks_exam,
                    obtained_marks=gained_marks,
                    percentage=percentage,
                    status=status
                )

            # Save the result JSON file
            folder_path = "C:/Data/"
            os.makedirs(folder_path, exist_ok=True)
            
            file_path = os.path.join(folder_path, f"{student.roll_no}({exam.exam_name}).json")
            with open(file_path, "w", encoding="utf-8") as json_file:
                json.dump(result_data, json_file, indent=4, ensure_ascii=False)

                 # Return success response
            return JsonResponse({
                "success": True,
                "message": "Exam submitted successfully.",
                "result": result_data,
                "exam_id": exam.id,
                "redirect_url": reverse('student:exam_result', kwargs={'exam_id': exam.id})
            }, status=200)

        except Exception as e:
            return JsonResponse({"error": f"An error occurred: {str(e)}"}, status=500)
    
    return JsonResponse({"error": "Invalid request method"}, status=405)

# Save Remaining Time
@csrf_exempt  # Exempt this view from CSRF verification
def save_remaining_time(request):
    if request.method == "POST":
        try:
            # Parse the request body
            data = json.loads(request.body.decode("utf-8"))
            remaining_time = data.get("time_remaining")
            print("Remaining time ",remaining_time)

            # Validate the remaining_time
            if remaining_time is None:
                return JsonResponse({"error": "time_remaining is required"}, status=400)

            # Ensure remaining_time is an integer
            try:
                remaining_time = int(remaining_time)
            except ValueError:
                return JsonResponse({"error": "time_remaining must be an integer"}, status=400)

            # Access the linked Student profile
            student = request.user.student
            if not student:
                return JsonResponse({"error": "Student profile not found"}, status=404)

            # Update the student's remaining time
            student.time_remaining = remaining_time
            student.save()

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"error": "Invalid request method"}, status=405)

# Exam Result
@login_required
def exam_result(request, exam_id):
    student = request.user.student
    if not student:
        return redirect("student:student_login")

    try:
        exam = ExamSpecification.objects.get(id=exam_id)
    except ExamSpecification.DoesNotExist:
        return HttpResponse("Exam not found.", status=404)

    if not student.has_attempted_exam:
        return redirect("student:welcome")

    # Define the path to the student's JSON file
    exam_directory = os.path.join("C:\\", f"exam_{exam_id}_{exam.exam_name.replace(' ', '_')}")
    student_json_file = os.path.join(exam_directory, f"{student.roll_no}.json")

    try:
        with open(student_json_file, 'r') as json_file:
            student_data = json.load(json_file)
    except FileNotFoundError:
        return HttpResponse("Exam data not found for this student.", status=404)
    except json.JSONDecodeError:
        return HttpResponse("Invalid exam data format.", status=400)

    # Get exam details and question bank from the JSON
    exam_details = student_data["Exam_Details"]
    assigned_questions = student_data["Question_Bank"]

    # Fetch total marks from ExamSpecification
    total_marks_exam = exam.total_marks  # Total marks for the exam
    total_marks_student = 0  # Total marks obtained by the student
    gained_marks = 0  # Marks gained by the student
    question_list = []

    for q in assigned_questions:
        question_mark = int(q["marks"])
        total_marks_student += question_mark

        # Get user's answer (if attempted)
        user_answer = q.get("student_c_ans", "")

        # Get the answer text based on user's selection
        user_answer_text = "Not Attempted"
        if user_answer:
            if user_answer == "A":
                user_answer_text = q["option_1"]
            elif user_answer == "B":
                user_answer_text = q["option_2"]
            elif user_answer == "C":
                user_answer_text = q["option_3"]
            elif user_answer == "D":
                user_answer_text = q["option_4"]

        # Calculate marks if answer is correct
        if user_answer:  # Only check if answer was attempted
            correct_answer = q["correct_answer"]
            if user_answer == "A" and correct_answer == q["option_1"] or \
               user_answer == "B" and correct_answer == q["option_2"] or \
               user_answer == "C" and correct_answer == q["option_3"] or \
               user_answer == "D" and correct_answer == q["option_4"]:
                gained_marks += question_mark

        # Append question data
        question_list.append({
            "question_text": q["question_text"],
            "correct_answer": q["correct_answer"],
            "attempted_answer": user_answer_text,
            "marks": question_mark,
            "is_correct": user_answer and user_answer == correct_answer  # Add this field
        })

    # Calculate percentage based on total marks from ExamSpecification
    percentage = (gained_marks / total_marks_exam) * 100 if total_marks_exam > 0 else 0

    # Prepare the exam result data
    exam_data = {
        "student_name": exam_details["student_name"],
        "roll_no": exam_details["roll_no"],
        "exam_type":exam_details["exam_type"],
        "course_name": exam_details["course_name"],
        "course_code": exam_details["course_code"],
        "branch": exam_details["branch"],
        "year": exam_details["year"],
        "total_questions": exam_details["max_question"],
        "attempted_questions": len([q for q in assigned_questions if q.get("student_c_ans")]),
        "total_marks": total_marks_exam,  # Use total marks from ExamSpecification
        "gained_marks": gained_marks,
        "percentage": round(percentage, 2),
        "question_list": question_list
    }

    return render(request, "student/exam_result.html", {"exam_data": exam_data, "exam": exam})

# Final Submit
@login_required
def final_submit(request, exam_id):
    if request.method == "POST":
        password = request.POST.get("password")

        if password == "gpn":
            student = request.user.student
            if not student:
                return redirect("student:student_login")

            try:
                exam = ExamSpecification.objects.get(id=exam_id)
            except ExamSpecification.DoesNotExist:
                return HttpResponse("Exam not found.", status=404)

            # Define the path to the student's JSON file
            exam_directory = os.path.join("C:\\", f"exam_{exam_id}_{exam.exam_name.replace(' ', '_')}")
            student_json_file = os.path.join(exam_directory, f"{student.roll_no}.json")

            try:
                with open(student_json_file, 'r') as json_file:
                    student_data = json.load(json_file)
            except FileNotFoundError:
                return HttpResponse("Exam data not found for this student.", status=404)
            except json.JSONDecodeError:
                return HttpResponse("Invalid exam data format.", status=400)

            logout(request)
            return redirect('index')

    else:
        messages.error(request, "Incorrect password")
        return redirect("student:exam_result", exam_id=exam_id)

    return render(request, "student/exam_result.html")

@csrf_exempt
def save_answer(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            exam_id = data.get('exam_id')
            question_id = data.get('question_id')
            answer = data.get('answer')

            exam = ExamSpecification.objects.get(id=exam_id)
            student = request.user.student

            # Define the path to the student's JSON file
            exam_directory = os.path.join("C:\\", f"exam_{exam_id}_{exam.exam_name.replace(' ', '_')}")
            student_json_file = os.path.join(exam_directory, f"{student.roll_no}.json")

            # Debug: Print the file path
            print(f"Saving answer to: {student_json_file}")

            # Read the current JSON file
            with open(student_json_file, 'r') as json_file:
                student_data = json.load(json_file)

            # Update the answer in the Question_Bank
            for question in student_data["Question_Bank"]:
                if str(question["q_id"]) == str(question_id):
                    question["student_c_ans"] = answer
                    break

            # Write the updated JSON back to the file
            with open(student_json_file, 'w') as json_file:
                json.dump(student_data, json_file, indent=4)

            # Debug: Confirm the answer was saved
            print(f"Saved answer for question {question_id}: {answer}")

            return JsonResponse({'success': True})
        except Exception as e:
            # Debug: Print the error
            print(f"Error saving answer: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@csrf_exempt
def get_saved_answers(request):
    if request.method == 'GET':
        try:
            exam_id = request.GET.get('exam_id')
            student = request.user.student

            # Define the path to the student's JSON file
            exam = ExamSpecification.objects.get(id=exam_id)
            exam_directory = os.path.join("C:\\", f"exam_{exam_id}_{exam.exam_name.replace(' ', '_')}")
            student_json_file = os.path.join(exam_directory, f"{student.roll_no}.json")

            # Read the JSON file
            with open(student_json_file, 'r') as json_file:
                student_data = json.load(json_file)

            # Extract saved answers
            answers = {}
            for question in student_data["Question_Bank"]:
                if "student_c_ans" in question and question["student_c_ans"]:
                    answers[str(question["q_id"])] = question["student_c_ans"]

            return JsonResponse({'success': True, 'answers': answers})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def bad_request(request, exception):
    context = {
        'error_code': '400',
        'error_message': 'Bad Request',
        'error_details': 'The server could not understand your request.'
    }
    return render(request, 'errors/400.html', context, status=400)

def permission_denied(request, exception):
    context = {
        'error_code': '403',
        'error_message': 'Access Forbidden',
        'error_details': 'You do not have permission to access this page.'
    }
    return render(request, 'errors/403.html', context, status=403)

def page_not_found(request, exception):
    context = {
        'error_code': '404',
        'error_message': 'Page Not Found',
        'error_details': 'The requested page could not be found.'
    }
    return render(request, 'errors/404.html', context, status=404)

def server_error(request):
    context = {
        'error_code': '500',
        'error_message': 'Server Error',
        'error_details': 'An internal server error occurred.'
    }
    return render(request, 'errors/500.html', context, status=500)
