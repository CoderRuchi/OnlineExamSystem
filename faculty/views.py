import logging
import os
from datetime import timezone
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from faculty.models import Faculty, Question, Course, Student, Result, ExamSpecification
import csv
import random
import json
from django.db.models import Q
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User, Group
from django.contrib.auth import authenticate, login as auth_login
from django.utils.timezone import now
from reportlab.lib.styles import getSampleStyleSheet  # type: ignore
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer  # type: ignore
from reportlab.lib import colors  # type: ignore
from django.db import connection,transaction
from django.contrib import messages
from faculty.forms import CSVUploadStudentForm, CSVUploadForm, FacultyRegisterForm
from django.core.paginator import Paginator
from .forms import FacultyRegisterForm
from reportlab.lib.pagesizes import letter # type: ignore
from reportlab.pdfgen import canvas # type: ignore
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.views.decorators.csrf import csrf_exempt

# Helper function to check if a user is faculty
def is_faculty(user):
    return user.groups.filter(name='Faculty').exists()


def index(request):
    return render(request,'faculty/index.html')
def about(request):
    return render(request,'faculty/about.html')
def contact(request):
    return render(request,'faculty/contact.html')

# Faculty registration view
def faculty_register(request):
    if request.method == "POST":
        form = FacultyRegisterForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            username = form.cleaned_data['username']
            password = form.cleaned_data['password1']

            # Create a Django User
            user = User.objects.create_user(username=username, email=email, password=password)
            user.save()

            # Create a Faculty profile linked to the User
            faculty = Faculty(user=user, email=email, name=username)
            faculty.save()

            # Assign the user to the Faculty group
            faculty_group = Group.objects.get(name='Faculty')
            user.groups.add(faculty_group)

            messages.success(request, "Faculty registration successful!")
            return redirect('faculty_login')
        else:
            print("❌ Form Errors:", form.errors)  # Debugging
    else:
        form = FacultyRegisterForm()

    return render(request, 'faculty/register.html', {'form': form})


# Faculty login view
def faculty_login(request):
    if request.method == "POST":
        username = request.POST.get("name")
        password = request.POST.get("password")
        print(f"📌 Username: {username}, Password: {password}")  # Debugging

        user = authenticate(request, username=username, password=password)
        if user is not None and is_faculty(user):
            auth_login(request, user)
            if not user.groups.exists():
                if hasattr(user, 'faculty'):  # Check if the user has a linked Faculty profile
                    try:
                        group = Group.objects.get(name='Faculty')
                        user.groups.add(group)
                        print(f"User {user.username} added to {group.name} group.")
                    except Group.DoesNotExist:
                        print("Faculty group does not exist.")
                        messages.error(request, "Faculty group does not exist. Please contact the administrator.")
            if user.groups.filter(name="Faculty").exists():
                messages.success(request, "Login successful!")
                return redirect("faculty_dashboard")

        else:
            messages.error(request, "Invalid credentials or not a faculty member.")

    return render(request, "faculty/login.html")


def faculty_logout(request):
    logout(request)
    return render(request,"faculty/logout.html")

# Faculty dashboard view
@login_required
@user_passes_test(is_faculty)
def faculty_dashboard(request):
    active_exams = ExamSpecification.objects.filter(is_active=True)
    active_exam_count = ExamSpecification.objects.filter(is_active=True).count()
    messages.get_messages(request)
    return render(request, "faculty/dashboard.html",{'total_exams':ExamSpecification.objects.all().count(),'total_students':Student.objects.all().count(),'active_exams':active_exams,'active_exam_count':active_exam_count,'faculty_name':request.user.username})

#faculty add student
@login_required
@user_passes_test(is_faculty, login_url='/login/')
def add_student(request):
    if request.method == "POST":
        try:
            # Get form data
            name = request.POST.get("name")
            roll_no = request.POST.get("roll_no")
            branch = request.POST.get("branch")
            course_codes = request.POST.getlist("course_codes")
            password = roll_no  # Using roll_no as default password
            selected_exams = request.POST.getlist("active_exams")  # Get selected active exams

            # Create User account for the student
            user = User.objects.create_user(
                username=roll_no,
                password=password
            )

            # Add user to Students group
            students_group, _ = Group.objects.get_or_create(name='Students')
            user.groups.add(students_group)

            # Create Student object
            student = Student.objects.create(
                user=user,
                name=name,
                roll_no=roll_no,
                password=password,
                branch=branch
            )
            student.is_manually_added=True
            student.save()
            # Add courses to student
            for course_code in course_codes:
                course = Course.objects.get(code=course_code)
                student.registered_courses.add(course)

            # Generate JSON files for selected exams
            for exam_id in selected_exams:
                try:
                    exam = ExamSpecification.objects.get(id=exam_id)
                    # Create a Result record for the student
                    Result.objects.create(
                        student=student,
                        exam=exam,
                        total_marks=exam.total_marks,
                        obtained_marks=0,
                        percentage=0.0,
                        submitted_at=None
                    )
                    
                    # Generate JSON file for this student
                    generate_single_student_json(exam.id, student)
                    
                    messages.success(request, f"Student added and exam JSON generated for {exam.exam_name}!")
                except Exception as e:
                    messages.warning(request, f"Student added but failed to generate exam JSON: {str(e)}")

            if not selected_exams:
                messages.success(request, "Student added successfully!")

            return redirect("add_student")

        except Course.DoesNotExist:
            messages.error(request, "One or more selected courses do not exist!")
        except Exception as e:
            messages.error(request, f"Error adding student: {str(e)}")

    # Get all available courses for the form
    courses = Course.objects.all()
    active_exams = ExamSpecification.objects.filter(is_active=True)
    
    return render(request, "faculty/add_student.html", {
        'courses': courses,
        'branches': Student.BRANCH_CHOICES,
        'active_exams': active_exams  # Pass the queryset directly, not exists()
    })


def generate_single_student_json(exam_id, student):
    """Generate JSON exam file for a single student ensuring no duplicate questions within their exam"""
    try:
        exam = ExamSpecification.objects.get(id=exam_id)
    except ExamSpecification.DoesNotExist:
        raise ValueError(f"Exam with ID {exam_id} does not exist.")

    # Define the directory where JSON files will be stored
    exam_directory = os.path.join("C:\\", f"exam_{exam_id}_{exam.exam_name.replace(' ', '_')}")
    course = Course.objects.filter(code=exam.course_code).first()

    # Create the directory if it doesn't exist
    os.makedirs(exam_directory, exist_ok=True)

    # Fetch all questions for the exam, grouped by unit
    all_questions = Question.objects.filter(course_code=exam.course_code).values(
        "id", "question_text", "option1", "option2", "option3", "option4", 
        "correct_answer", "mark", "unit_no", "latex_equation", "image_path"
    )

    if not all_questions:
        raise ValueError(f"No questions found for course code: {exam.course_code}")

    # Group questions by unit and mark
    questions_by_unit_and_mark = {}
    for question in all_questions:
        unit_no = question["unit_no"]
        mark = question["mark"]
        if unit_no not in questions_by_unit_and_mark:
            questions_by_unit_and_mark[unit_no] = {}
        if mark not in questions_by_unit_and_mark[unit_no]:
            questions_by_unit_and_mark[unit_no][mark] = []
        questions_by_unit_and_mark[unit_no][mark].append(question)

    # Prepare student data
    student_data = {
        "Exam_Details": {
            "course_code": exam.course_code,
            "course_name": exam.exam_name,
            "roll_no": student.roll_no,
            "student_name": student.name,
            "year": course.year if course else "",
            "branch": student.branch,
            "max_question": exam.total_questions,
            "exam_type": exam.exam_type,
            "exam_directory": exam_directory
        },
        "Question_Bank": []
    }

    # Get the question distribution from the exam specification
    question_distribution = exam.question_sheet
    selected_questions = []
    total_selected_marks = 0
    used_question_ids = set()  # Track questions used FOR THIS STUDENT ONLY

    for unit in question_distribution:
        unit_num = unit['unit']
        if unit_num not in questions_by_unit_and_mark:
            raise ValueError(f"No questions found for unit {unit_num}")

        for mark in unit['questions']:
            if mark not in questions_by_unit_and_mark[unit_num]:
                raise ValueError(f"No questions found for Unit {unit_num} with {mark} marks")

            # Get all questions for this unit and mark
            available_questions = questions_by_unit_and_mark[unit_num][mark]
            
            # Filter out questions already used for this student
            available_questions = [q for q in available_questions if q['id'] not in used_question_ids]
            
            if not available_questions:
                raise ValueError(f"No unique questions left for Unit {unit_num} with {mark} marks for this student")

            selected = random.choice(available_questions)    
            selected_questions.append(selected)
            used_question_ids.add(selected['id'])
            total_selected_marks += mark

    if total_selected_marks != exam.total_marks:
        raise ValueError(f"Selected questions total {total_selected_marks} marks but expected {exam.total_marks}")

    random.shuffle(selected_questions)

    # Add the randomized questions to the JSON data
    for i, question in enumerate(selected_questions, start=1):
        question_data = {
            "q_no": i,
            "q_id": question["id"],
            "unit_no": question["unit_no"],
            "question_text": question["question_text"],
            "latex_equation": question.get("latex_equation", ""),
            "option_1": question["option1"],
            "option_2": question["option2"],
            "option_3": question["option3"],
            "option_4": question["option4"],
            "correct_answer": question["correct_answer"],
            "student_c_ans": "",
            "marks": question["mark"],
            "image_path": f"/media/{question['image_path']}" if question.get('image_path') else None
        }
        student_data["Question_Bank"].append(question_data)

    # Write the JSON data to a file
    student_json_file = os.path.join(exam_directory, f"{student.roll_no}.json")
    with open(student_json_file, 'w') as json_file:
        json.dump(student_data, json_file, indent=4)
    return student_json_file

# Add course view
@login_required
@user_passes_test(is_faculty)
def add_course(request):
    faculty = request.user.faculty
    courses = Course.objects.filter(faculty=faculty)

    if request.method == 'POST':
        course_name = request.POST.get('name')
        course_code = request.POST.get('code')
        year = request.POST.get('year')

        Course.objects.create(
            name=course_name,
            code=course_code,
            year=year,
            faculty=faculty
        )

        messages.success(request, "Course added successfully!")
        return redirect('add_course')

    return render(request, 'faculty/add_course.html',{'courses':courses})

# Update course view
@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def update_course(request,course_id):
    course = get_object_or_404(Course,id = course_id)
    if request.method == "POST":
        course.name = request.POST.get("name")
        course.code = request.POST.get("code")
        course.save()
        messages.success(request,"Course Updated")
    return redirect("add_course")

@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def delete_course(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    course.delete()
    messages.success(request, "Course deleted successfully!")
    return redirect("add_course")

@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def truncate_courses(request):
    if request.method == "POST":
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("TRUNCATE TABLE faculty_course;")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        messages.success(request, "All courses have been deleted successfully!")
    return redirect("add_course")

def calculate_questions_per_unit(total_questions, marks_per_unit, total_marks):
    questions_per_unit = {}
    remaining_questions = total_questions

    # Calculate proportional questions for each unit
    for i, unit_marks in enumerate(marks_per_unit):
        unit_key = str(i + 1)  # Use consistent keys (e.g., "1", "2", etc.)
        unit_questions = round((unit_marks / total_marks) * total_questions)
        questions_per_unit[unit_key] = unit_questions
        remaining_questions -= unit_questions

    # Adjust for rounding errors
    if remaining_questions != 0:
        # Add remaining questions to the last unit
        last_unit_key = str(len(marks_per_unit))
        questions_per_unit[last_unit_key] += remaining_questions

    return questions_per_unit

@login_required
@user_passes_test(is_faculty)
def add_exam_specifications(request):
    faculty = request.user.faculty
    specifications = ExamSpecification.objects.filter(faculty=faculty)
    courses = Course.objects.all()

    if request.method == "POST":
        exam_name = request.POST.get("exam_name")
        exam_type = request.POST.get("exam_type")
        num_units = int(request.POST.get("num_units"))
        course_code = request.POST.get('course_code','').strip()
        total_marks = int(request.POST.get("total_marks", 0))  # Add total marks
        total_questions = int(request.POST.get("total_questions", 0))  # Add total questions
        marks_per_unit_str = request.POST.get("marks_per_unit", "")  # Get marks per unit as a string
        max_mark = int(request.POST.get("max_mark", 1))  # Add max mark
        duration_hours = request.POST.get("duration_hours")
        duration_minutes=request.POST.get("duration_minutes")

        try:
            course = Course.objects.get(code=course_code)

         # Convert the question sheet string to JSON
            question_sheet_str = request.POST.get('question_sheet', '')
            question_sheet = []

                # Parse the pipe-separated string into JSON format
            for unit_str in question_sheet_str.split('|'):
                if not unit_str:
                    continue
                unit_part = unit_str.split(':')
                unit_num = int(unit_part[0].replace('Unit-', ''))
                questions = [int(mark) for mark in unit_part[1].split(',') if mark.strip()]

                question_sheet.append({
                    'unit': unit_num,
                    'questions': questions,
                    'totalMarks': sum(questions)
                })

            print("exam name",exam_name)
            print("exam type",exam_type)
            print("num_units",num_units)
            print("course_code",course_code)
            print("total_marks",total_marks)
            print("total_questions",total_questions)
            print("marks_per_unit_str",marks_per_unit_str)

            # Parse marks_per_unit from the comma-separated string
            try:
                marks_per_unit = [int(mark.strip()) for mark in marks_per_unit_str.split(",")]
            except ValueError:
                messages.error(request, "Invalid marks per unit format. Please enter comma-separated values.")
                return render(request, "faculty/add_exam_specifications.html", {'specifications': specifications})

        # Validate the number of units
            if len(marks_per_unit) != num_units:
                messages.error(request, "Number of units does not match the provided unit marks.")
                return render(request, "faculty/add_exam_specifications.html", {'specifications': specifications})

        # Create the exam specification
            exam = ExamSpecification.objects.create(
                exam_name=exam_name,
                exam_type=exam_type,
                num_units=num_units,
                question_sheet=question_sheet,
                faculty=faculty,
                course_code=course_code,
                total_marks=total_marks,
                total_questions=total_questions,
                marks_per_unit=marks_per_unit,
                max_mark=max_mark,
                exam_duration_hours=duration_hours,
                exam_duration_minutes=duration_minutes,
            )


            # NEW: Create Result objects for all students registered in this course
            students = Student.objects.filter(registered_courses=course)
            
            for student in students:
                Result.objects.create(
                    student=student,
                    exam=exam,
                    total_marks=exam.total_marks,
                    obtained_marks=0,
                    percentage=0.0,
                    submitted_at=None  # Will be set when student submits
                )

            messages.success(request, "Exam details saved successfully!")
            return redirect("preview_exam", exam_id=exam.id)

        except Exception as e:
            messages.error(request, f'Error saving specifications: {str(e)}')
    return render(request, "faculty/add_exam_specifications.html", {'specifications': specifications,'courses':courses})
    
@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def update_specifications(request,spec_id):
    if request.method == "POST":
        spec_id = request.POST.get("spec_id")
        specification = get_object_or_404(ExamSpecification, id=spec_id)

        specification.exam_name = request.POST.get("exam_name")
        specification.exam_type = request.POST.get("exam_type")
        specification.num_units = request.POST.get("num_units")
        specification.total_marks = request.POST.get("total_marks")

        # Update exam duration fields
        specification.exam_duration_hours = int(request.POST.get("duration_hours", 1))
        specification.exam_duration_minutes = int(request.POST.get("duration_minutes", 0))

        specification.save()
        messages.success(request, "Specifications Updated Successfully")
    return redirect("add_exam_specifications")

@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def delete_exam_specification(request,spec_id):
    specification = get_object_or_404(ExamSpecification, id=spec_id)
    specification.delete()
    messages.success(request,'Specifications deleted succesfully')
    return redirect('add_exam_specifications')

@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def truncate_specifications(request):
    if request.method == "POST":
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("TRUNCATE TABLE faculty_examspecification;")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        messages.success(request, "All specifications have been deleted successfully!")
    return redirect("add_exam_specifications")

@login_required
@user_passes_test(is_faculty)
def upload_students(request):
    print("📌 upload_students function was called!")  # Debugging
    courses = Course.objects.all().order_by('name')
    branches = Student.BRANCH_CHOICES

    if request.method == "POST":
        form = CSVUploadStudentForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['file']
            default_password = request.POST.get('default_password','').strip()
            course_code = request.POST.get('course_code','').strip()
            print(f"📌 request.FILES: {request.FILES}")  # Debugging

            if not csv_file.name.endswith(".csv"):
                messages.error(request, "Please upload a valid CSV file.")
                return redirect("upload_students")
            if not course_code:
                messages.error(request,"Please select a course")
            try:
                #Get the course objects once
                course = Course.objects.get(code=course_code)
                decoded_file = csv_file.read().decode("utf-8").splitlines()
                print(f"📌 Decoded File Contents: {decoded_file}")  # Debugging
                reader = csv.reader(decoded_file)
                next(reader)  # Skip header row
                # Get or create the "Students" group
                students_group, created = Group.objects.get_or_create(name='Students')
                for row in reader:
                    roll_no = row[0].strip()
                    name = row[1].strip()
                    branch = row[2].strip()  # Get branch from CSV
                    password = default_password if default_password else roll_no

                    user, created = User.objects.get_or_create(
                        username=roll_no,
                        defaults={'password': password}
                    )

                    if not created:
                        if not user.check_password(password):
                            user.set_password(password)
                            user.save()

                    user.groups.add(students_group)

                    # Create or update the Student record
                    student, created = Student.objects.get_or_create(
                        user=user,
                        roll_no=roll_no,
                        defaults={
                            "name": name,
                            "password": password  # This is just for display
                        },
                        branch =branch
                    )

                    # Register courses
                    student.registered_courses.add(course)  
                    student.save()
                    
                messages.success(request, "✅ Students uploaded successfully!")
                return redirect("upload_students")
            except Exception as e:
                print(f"❌ Error: {e}")  # Print error for debugging
                messages.error(request, f"Error uploading file: {e}")
                return redirect('upload_students')

    else:
        form = CSVUploadStudentForm()


    return render(request, "faculty/upload_students.html", {"form": form,"courses":courses,"branches":branches})

@login_required
@user_passes_test(is_faculty)
def view_students(request):
    # Get search query if exists
    search_query = request.GET.get('search', '')
    # Get all students ordered by branch then roll number
    students = Student.objects.all().order_by('branch', 'roll_no')

    # Apply search filter if query exists
    if search_query:
        students = students.filter(
            Q(roll_no__icontains=search_query) |
            Q(name__icontains=search_query) |
            Q(branch__icontains=search_query)  # Changed from registered_courses__branch to branch
        ).distinct()

    context = {
        'students': students,
        'search_query': search_query,
    }
    return render(request, 'faculty/view_students.html', context)

from django.views.decorators.http import require_POST
@require_POST
def save_attendance(request):
    try:
        attendance_data = json.loads(request.POST.get('attendance_data'))

        for item in attendance_data:
            student = Student.objects.get(id=item['student_id'])
            student.attendance_status = item['status'] == 'present'
            student.save()

        return JsonResponse({'success': True, 'message': 'Attendance saved successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required
@user_passes_test(is_faculty)
def update_attendance(request):
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        status = request.POST.get('status') == 'true'

        try:
            student = Student.objects.get(id=student_id)
            student.attendance_status = status
            student.save()
            return JsonResponse({'success': True})
        except Student.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Student not found'})

    return JsonResponse({'success': False, 'error': 'Invalid request'})

@csrf_exempt
@login_required
@user_passes_test(is_faculty)
def update_student_password(request):
    if request.method == "POST":
        try:
            student_id = request.POST.get('student_id')
            new_password = request.POST.get('new_password')

            student = Student.objects.get(id=student_id)
            user = student.user

            # Update password in User model
            user.set_password(new_password)
            user.save()

            # Update display password in Student model
            student.password = new_password
            student.save()

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    return JsonResponse({'success': False, 'message': 'Invalid request method'})


@csrf_exempt
@login_required
@user_passes_test(is_faculty)
def reset_student_password(request):
    if request.method == "POST":
        try:
            student_id = request.POST.get('student_id')
            student = Student.objects.get(id=student_id)

            # Reset password to roll number
            user = student.user
            user.set_password(student.roll_no)
            user.save()

            # Update student record
            student.password = student.roll_no
            student.save()

            return JsonResponse({
                'success': True,
                'message': 'Password reset to roll number'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            })
    return JsonResponse({
        'success': False,
        'message': 'Invalid request method'
    })

@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def truncate_students(request):
    if request.method == "POST":
        delete_option = request.POST.get('delete_option')

        try:
            if delete_option == 'all':
                # Delete all students and their associated users
                students_group = Group.objects.get(name='Students')
                student_users = User.objects.filter(groups=students_group)

                # Get count before deletion
                count = student_users.count()

                # Delete students and their users
                with transaction.atomic():
                    Student.objects.all().delete()
                    student_users.delete()

                messages.success(request, f"✅ All {count} students have been deleted successfully!")
            else:
                # Delete students from selected course and branch
                course_id = request.POST.get('course_id')
                branch_value = request.POST.get('branch_id')
                print(f"Received course_id: {course_id}, branch_value: {branch_value}")  # Debug

                if not course_id:
                    messages.error(request, "Please select a course")
                    return redirect("upload_students")
                if not branch_value:
                    messages.error(request, "Please select a branch")
                    return redirect("upload_students")

                course = Course.objects.get(id=course_id)
                 # Debug: Print all students with this branch
                all_students_with_branch = Student.objects.filter(branch=branch_value)
                print(all_students_with_branch)
                # Get students registered for this course and branch
                students = Student.objects.filter(
                    registered_courses__id=course_id,  # Use __id for M2M relationship
                    branch=branch_value
                ).distinct()  # Add distinct() to avoid duplicates
                
                user_ids = students.values_list('user_id', flat=True)
                count = students.count()  # Count after filtering

                if count == 0:
                    branch_name = dict(Student.BRANCH_CHOICES).get(branch_value, branch_value)
                    messages.warning(request, f"⚠️ No students found registered for {course.name} in {branch_name} branch!")
                    return redirect("upload_students")

                # Delete students and their users
                with transaction.atomic():
                    students.delete()
                    User.objects.filter(id__in=user_ids).delete()

                branch_name = dict(Student.BRANCH_CHOICES).get(branch_value, branch_value)
                messages.success(request, f"✅ {count} students registered for {course.name} in {branch_name} branch have been deleted successfully!")

        except Course.DoesNotExist:
            messages.error(request, "Selected course does not exist")
        except Group.DoesNotExist:
            messages.error(request, "Students group does not exist")
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            logger = logging.getLogger(__name__)
            logger.error(f"Error deleting students: {str(e)}")

    return redirect("upload_students")

@login_required
@user_passes_test(is_faculty)
def upload_questions(request):
    faculty = request.user.faculty
    courses = Course.objects.all().order_by('name')
    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['file']
            error_messages = []

            if not csv_file.name.endswith('.csv'):
                messages.error(request, '❌ Please upload a valid CSV file.')
                return redirect('upload_questions')

            try:
                # Handle file encoding
                try:
                    decoded_file = csv_file.read().decode('utf-8').splitlines()
                except UnicodeDecodeError:
                    csv_file.seek(0)
                    decoded_file = csv_file.read().decode('latin-1').splitlines()

                reader = csv.reader(decoded_file)
                next(reader, None)  # Skip header row
                for row_num, row in enumerate(reader, start=2):
                    try:
                        # Check for at least 11 columns
                        if len(row) < 11:
                            raise ValueError("Insufficient no. of columns in CSV. Please check your file.")

                        # Unpack first 11 columns
                        sr_no, code, name, question_text, option1, option2, option3, option4, correct_answer, user_c_answer, mark = [
                            col.strip() for col in row[:11]
                        ]

                        # Set unit_no (default to '1' if not present)
                        if len(row) > 11:
                            unit_no = row[11].strip()
                        else:
                            unit_no = '1'  # Default value

                        # Set image_path (optional)
                        image_path = None
                        if len(row) > 12:
                            image_name = row[12].strip()
                            if image_name:
                                image_path = f"media/questions/{image_name}"

                        # Auto-create course if missing
                        course, created = Course.objects.get_or_create(
                            code=code,
                            name=name,
                            faculty=faculty,
                            defaults={'description': 'Auto-created during upload'}
                        )

                        # Create the question
                        Question.objects.create(
                            sr_no=int(sr_no),
                            course_code=code,
                            course_name=name,
                            question_text=question_text,
                            option1=option1,
                            option2=option2,
                            option3=option3,
                            option4=option4,
                            correct_answer=correct_answer,
                            user_c_answer=user_c_answer,
                            mark=int(mark),
                            unit_no=int(unit_no),
                            image_path=image_path
                        )

                    except Exception as e:
                        error_messages.append(f"Error in row {row_num}: {str(e)}")
                        continue

                if error_messages:
                    request.session['upload_errors'] = error_messages
                    messages.error(request, "❌ Some questions failed to upload")
                else:
                    messages.success(request, "✅ All questions uploaded successfully!")

                return redirect('upload_questions')

            except Exception as e:
                messages.error(request, f"❌ File processing error: {str(e)}")
                return redirect('upload_questions')

    # Get errors from session if they exist
    upload_errors = request.session.pop('upload_errors', None)

    return render(request, 'faculty/upload_questions.html', {
        'form': CSVUploadForm(),
        'upload_errors': upload_errors,
        'courses':courses
    })

import logging
@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def truncate_questions(request):
    if request.method == "POST":
        delete_option = request.POST.get('delete_option')

        try:
            if delete_option == 'all':
                # Delete all questions
                with transaction.atomic():
                    count = Question.objects.count()
                    Question.objects.all().delete()
                
                messages.success(request, f"✅ All {count} questions have been deleted successfully!")
            else:
                # Delete questions from selected course
                course_id = request.POST.get('course_id')
                print(course_id)
                if not course_id:
                    messages.error(request, "Please select a course")
                    return redirect("upload_questions")

                course = Course.objects.get(id=course_id)
                print(course)
                # Get questions for this course
                questions = Question.objects.filter(course_code=course.code)
                count = questions.count()

                if count == 0:
                    messages.warning(request, f"⚠️ No questions found for {course.name}")
                    return redirect("upload_questions")

                # Delete questions
                with transaction.atomic():
                    questions.delete()

                messages.success(request, f"✅ {count} questions for {course.name} have been deleted successfully!")

        except Course.DoesNotExist:
            messages.error(request, "Selected course does not exist")
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            logger = logging.getLogger(__name__)
            logger.error(f"Error deleting questions: {str(e)}")

    return redirect("upload_questions")

@login_required
@user_passes_test(is_faculty)
def manage_questions(request):
    # Handle question deletion
    if request.method == 'POST' and 'delete_question' in request.POST:
        question_id = request.POST.get('delete_question')
        try:
            question = Question.objects.get(id=question_id)
            question.delete()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Question deleted successfully!'})
            messages.success(request, "Question deleted successfully!")
        except Question.DoesNotExist:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': 'Question not found'}, status=404)
            messages.error(request, "Question not found")
        return redirect('manage_questions')

    # Handle question editing
    if request.method == 'POST' and 'question_id' in request.POST:
        question_id = request.POST.get('question_id')
        try:
            question = Question.objects.get(id=question_id)
            question.course_code = request.POST.get('course_code')
            question.question_text = request.POST.get('question_text')
            question.option1 = request.POST.get('option1')
            question.option2 = request.POST.get('option2')
            question.option3 = request.POST.get('option3')
            question.option4 = request.POST.get('option4')
            question.correct_answer = request.POST.get('correct_answer')
            question.unit_no = request.POST.get('unit_no')
            question.mark = request.POST.get('mark')
            question.save()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Question updated successfully!'})
            messages.success(request, "Question updated successfully!")
        except Question.DoesNotExist:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': 'Question not found'}, status=404)
            messages.error(request, "Question not found")
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': str(e)}, status=400)
            messages.error(request, f"Error updating question: {str(e)}")
        return redirect('manage_questions')

    # Get filter parameters from request
    course_code = request.GET.get('course_code', '')
    unit_no = request.GET.get('unit_no', '')
    search_query = request.GET.get('search', '')

    # Start with all questions
    questions = Question.objects.all()

    # Apply filters
    if course_code:
        questions = questions.filter(course_code=course_code)
    if unit_no:
        questions = questions.filter(unit_no=unit_no)
    if search_query:
        questions = questions.filter(
            Q(question_text__icontains=search_query) |
            Q(option1__icontains=search_query) |
            Q(option2__icontains=search_query) |
            Q(option3__icontains=search_query) |
            Q(option4__icontains=search_query)
        ).distinct()

    # Get distinct courses for filter dropdown
    courses = Course.objects.values_list('code', flat=True).distinct().order_by('code')

    # Get distinct units for filter dropdown
    units = Question.objects.values_list('unit_no', flat=True).distinct().order_by('unit_no')

    # Pagination
    paginator = Paginator(questions, 100)  # Show 10 questions per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'questions': page_obj,
        'courses': courses,
        'units': units,
        'course_code': course_code,
        'unit_no': unit_no,
        'search_query': search_query,
    }
    return render(request, 'faculty/manage_questions.html', context)
# Preview exam view
# @login_required
# @user_passes_test(is_faculty, login_url='/faculty_login/')
# def truncate_questions(request):
#     if request.method =="POST":
#         with connection.cursor() as cursor:
#             cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
#             cursor.execute("TRUNCATE TABLE faculty_question;")
#             cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
#             messages.success(request,"✅ All questions have been deleted successfully!")
#     return redirect("upload_questions")

# Preview exam view
@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')

def preview_exam(request, exam_id):
    exam = get_object_or_404(ExamSpecification, id=exam_id)
    course = get_object_or_404(Course, code=exam.course_code)
    
    # Get only students registered for this specific course
    students = Student.objects.filter(registered_courses=course).order_by('roll_no')
    
    # Calculate total questions from question_sheet
    total_questions = 0
    if exam.question_sheet:
        for unit in exam.question_sheet:
            if 'questions' in unit:
                total_questions += len(unit['questions'])

    # Check if students exist for this course
    if not students.exists():
        messages.warning(request, f"No students are registered for {course.name} ({course.code})")

    context = {
        "exam": exam,
        "students": students,
        "course": course,
        "total_questions": total_questions,
        "question_sheet": exam.question_sheet
    }

    return render(request, "faculty/preview_exam.html", context)
# View results view
@login_required
@user_passes_test(is_faculty)
def take_exam(request):
    if not is_faculty(request.user):
        raise PermissionDenied
    
    faculty = request.user.faculty
    exams = ExamSpecification.objects.filter(faculty=faculty).order_by('-id')
    active_exams = exams.filter(is_active=True)  # Get active exams separately

    if request.method == "POST":
        exam_id = request.POST.get("exam_id")
        if exam_id:
            try:
                exam = ExamSpecification.objects.get(id=exam_id, faculty=faculty)
                course = Course.objects.filter(code=exam.course_code).first()
                
                if not course:
                    messages.error(request, "No course found for this exam!")
                    return redirect("take_exam")
                
                students = Student.objects.filter(registered_courses=course)
                exam_directory = os.path.join("C:\\", f"exam_{exam_id}_{exam.exam_name.replace(' ', '_')}")
                
                if not os.path.exists(exam_directory):
                    try:
                        os.makedirs(exam_directory)
                    except OSError as e:
                        messages.error(request, f"Could not create exam directory: {str(e)}")
                        return redirect("take_exam")
                
                success_count = 0
                error_count = 0
                
                for student in students:
                    try:
                        generate_single_student_json(exam.id, student)
                        success_count += 1
                    except Exception as e:
                        error_count += 1
                        messages.error(request, f"Error generating file for student {student.roll_no}: {str(e)}")
                
                if error_count > 0:
                    messages.warning(request, f"Successfully generated files for {success_count} students, but failed for {error_count} students")
                    return redirect("take_exam")
                
                exam.is_active = True
                exam.start_time = now()
                exam.save()
                
                for student in students:
                    Result.objects.get_or_create(
                        student=student,
                        exam=exam,
                        defaults={
                            'total_marks': exam.total_marks,
                            'obtained_marks': 0,
                            'percentage': 0.0,
                            'submitted_at': None
                        }
                    )
                
                messages.success(request, f"Exam '{exam.exam_name}' has started successfully!")
                return redirect("take_exam")
                
            except ExamSpecification.DoesNotExist:
                messages.error(request, "Exam not found or you don't have permission!")
            except Exception as e:
                messages.error(request, f"Error starting exam: {str(e)}")
        else:
            messages.error(request, "Please select a valid exam.")
    
    return render(request, "faculty/take_exam.html", {
        "exams": exams,
        "active_exams": active_exams  # Pass active exams separately
    })

from django.core.exceptions import ObjectDoesNotExist

def generate_student_json_files(exam_id, students):
    # Define the directory where JSON files will be stored - handle spaces in path
    try:
        exam = ExamSpecification.objects.get(id=exam_id)
    except ExamSpecification.DoesNotExist:
        raise ValueError(f"Exam with ID {exam_id} does not exist.")

    # Define the directory where JSON files will be stored
    exam_directory = os.path.join("C:\\", f"exam_{exam_id}_{exam.exam_name.replace(' ', '_')}")
    course = Course.objects.filter(code=exam.course_code).first()

    # Create the directory if it doesn't exist
    os.makedirs(exam_directory, exist_ok=True)

    # Fetch all questions for the exam, grouped by unit
    all_questions = Question.objects.filter(course_code=exam.course_code).values(
        "id", "question_text", "option1", "option2", "option3", "option4", "correct_answer", "mark", "unit_no", "latex_equation","image_path"
    )

    if not all_questions:
        raise ValueError(f"No questions found for course code: {exam.course_code}")

    # Group questions by unit
    questions_by_unit_and_mark = {}
    for question in all_questions:
        unit_no = question["unit_no"]
        mark = question["mark"]
        if unit_no not in questions_by_unit_and_mark:
            questions_by_unit_and_mark[unit_no] = {}
        if mark not in questions_by_unit_and_mark[unit_no]:
            questions_by_unit_and_mark[unit_no][mark] = []
        questions_by_unit_and_mark[unit_no][mark].append(question)


    print("Questions grouped by unit:", questions_by_unit_and_mark)

    # Get the exam specifications
    try:
        exam_spec = ExamSpecification.objects.get(course_code=exam.course_code, exam_name=exam.exam_name)
    except ObjectDoesNotExist:
        raise ValueError(f"No exam specifications found for course code: {exam.course_code} and exam name: {exam.exam_name}")

    print("Exam specifications - question_sheet:", exam_spec.question_sheet)

    # Generate JSON file for each student
    for student in students:
        student_data = {
            "Exam_Details": {
                "course_code": exam.course_code,
                "course_name": exam.exam_name,
                "roll_no": student.roll_no,
                "student_name": student.name,
                "year": course.year,
                "branch": student.branch,
                "max_question": exam_spec.total_questions,
                "exam_type": exam.exam_type,
                "exam_directory": exam_directory  # Store the exam directory path
            },
            "Question_Bank": []
        }
       # Step 1: Select questions based on the exam specification's question sheet
        selected_questions = []
        total_selected_marks = 0
        used_question_ids = set()# Track which question IDs have been used for this student

        # Get the question distribution from the exam specification
        question_distribution = exam_spec.question_sheet  # This should be the JSON field from your model

        for unit in question_distribution:
            unit_num = unit['unit']
            if unit_num not in questions_by_unit_and_mark:
                raise ValueError(f"No questions found for unit {unit_num}")

            for mark in unit['questions']:
                if mark not in questions_by_unit_and_mark[unit_num]:
                    raise ValueError(f"No questions found for Unit {unit_num} with {mark} marks")

                # Get all questions for this unit and mark that haven't been used yet
                available_questions = [
                    q for q in questions_by_unit_and_mark[unit_num][mark] 
                    if q['id'] not in used_question_ids
                ]
                if not available_questions:
                    raise ValueError(f"No unique questions left for Unit {unit_num} with {mark} marks")

                selected = random.choice(available_questions)    
                selected_questions.append(selected)
                used_question_ids.add(selected['id'])
                total_selected_marks += mark


        if total_selected_marks != exam_spec.total_marks:
            raise ValueError(f"Selected questions total {total_selected_marks} marks but expected {exam_spec.total_marks}")
        #print(selected_questions)
        random.shuffle(selected_questions)

        # Add the randomized questions to the JSON data
        for i, question in enumerate(selected_questions, start=1):
            question_data = {
                "q_no": i,
                "q_id": question["id"],
                "unit_no": question["unit_no"],
                "question_text": question["question_text"],
                "latex_equation": question.get("latex_equation", ""),  # Add LaTeX equation field
                "option_1": question["option1"],
                "option_2": question["option2"],
                "option_3": question["option3"],
                "option_4": question["option4"],
                "correct_answer": question["correct_answer"],
                "student_c_ans": "",
                "marks": question["mark"],
                "image_path": f"/media/{question['image_path']}" if question.get('image_path') else None
            }
            student_data["Question_Bank"].append(question_data)

        # Write the JSON data to a file
        student_json_file = os.path.join(exam_directory, f"{student.roll_no}.json")
        with open(student_json_file, 'w') as json_file:
            json.dump(student_data, json_file, indent=4)

    return exam_directory

# View results view
@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def end_exam(request):
    if request.method == "POST":
        exam_name = request.POST.get("exam_name")
        if exam_name:
            exam = ExamSpecification.objects.filter(exam_name=exam_name).update(is_active=False, end_time=now())
            if exam:
                messages.success(request, f"Exam '{exam_name}' has ended!")
            else:
                messages.error(request, "Exam not found!")
        else:
            messages.error(request, "Please enter a valid exam name.")
    return redirect('faculty_dashboard')

from reportlab.lib.pagesizes import letter # type: ignore
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle # type: ignore
from reportlab.lib import colors # type: ignore
from reportlab.lib.styles import getSampleStyleSheet # type: ignore
from django.shortcuts import render
from django.db.models import Q, Avg
from io import BytesIO
import pandas as pd
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
# Add course view

@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def view_results(request):
    # Fetch all exams
    exams = ExamSpecification.objects.all().order_by('id')
    exam_results = {}
    
    # Get search query from request
    search_query = request.GET.get('search', '').strip()
    
    for exam in exams:
        # Get the course for this exam
        try:
            course = Course.objects.get(code=exam.course_code)
            # Get all students enrolled in this course
            enrolled_students = course.students.all()
            
            # Apply search filter if provided
            if search_query:
                enrolled_students = enrolled_students.filter(
                    Q(name__icontains=search_query) |
                    Q(roll_no__icontains=search_query)
                )
            
            total_students = enrolled_students.count()
        except Course.DoesNotExist:
            enrolled_students = Student.objects.none()
            total_students = 0
        
        # Initialize counts
        attended_count = 0
        pending_count = 0
        not_attended_count = 0
        
        # Determine status for each student
        results_with_status = []
        
        for student in enrolled_students:
            # Check if student has a result record for this exam
            try:
                result = Result.objects.get(exam=exam, student=student)
                
                if student.has_attempted_exam:
                    # Student has attended and submitted
                    status = 'attended'
                    attended_count += 1
                elif student.exam_start_time:
                    # Student has started but not submitted
                    status = 'pending'
                    pending_count += 1
                else:
                    # Student hasn't started the exam
                    status = 'not_attended'
                    not_attended_count += 1
                    
                results_with_status.append({
                    'student': student,
                    'total_marks': result.total_marks,
                    'obtained_marks': result.obtained_marks if status == 'attended' else 0,
                    'percentage': result.percentage if status == 'attended' else 0.0,
                    'status': status
                })
                
            except Result.DoesNotExist:
                # Student hasn't attended at all (no result record)
                status = 'not_attended'
                not_attended_count += 1
                
                results_with_status.append({
                    'student': student,
                    'total_marks': exam.total_marks,
                    'obtained_marks': 0,
                    'percentage': 0.0,
                    'status': status
                })
        
        exam_results[exam] = {
            'results': sorted(results_with_status, key=lambda x: x['student'].roll_no),
            'total_students': total_students,
            'attended_count': attended_count,
            'pending_count': pending_count,
            'not_attended_count': not_attended_count,
            'course_name': course.name if course else exam.course_code,
            'course_code': exam.course_code,
            'branch': course.branch if hasattr(course, 'branch') else "N/A",
            'year': course.year if course else "N/A"
        }

    # Handle download requests
    if request.GET.get("download"):
        exam_id = request.GET.get("exam_id")
        if not exam_id:
            return HttpResponse("Exam ID not provided.", status=400)
        
        try:
            exam = ExamSpecification.objects.get(id=exam_id)
            course = Course.objects.get(code=exam.course_code)
            results = Result.objects.filter(exam=exam).order_by('student__roll_no')
            
            if not results.exists():
                return HttpResponse("No results found for this exam.", status=404)
            if request.GET.get("download") == "excel":
                # Prepare data for Excel
                data = {
                    'Sr.No': [],
                    'Roll No': [],
                    'Name': [],
                    'Total Marks': [],
                    'Obtained Marks': [],
                }
                
                for idx, result in enumerate(results, start=1):
                    data['Sr.No'].append(idx)
                    data['Roll No'].append(result.student.roll_no)
                    data['Name'].append(result.student.name)
                    data['Total Marks'].append(result.total_marks)
                    data['Obtained Marks'].append(result.obtained_marks)
                
                # Create DataFrame - MOVED OUTSIDE THE LOOP
                df = pd.DataFrame(data)
                output = BytesIO()
                writer = pd.ExcelWriter(output, engine='xlsxwriter')
                
                # Write to Excel
                df.to_excel(writer, sheet_name='Results', index=False, startrow=4)  # Start at row 4
                
                # Get workbook and worksheet objects
                workbook = writer.book
                worksheet = writer.sheets['Results']
                
                # Get the first result for header info (if exists)
                first_result = results.first()
                
                # Header information (Branch, Course Name, Course Code, Exam Name)
                header_info = [
                    ["Programme:", first_result.student.branch if first_result else "N/A"], 
                    ["Course Name:", course.name],
                    ["Course Code:", course.code], 
                    ["Exam Name:", exam.exam_name]
                ]
                
                # Format for header information
                info_format = workbook.add_format({
                    'bold': True,
                    'align': 'left',
                    'valign': 'vcenter',
                    'font_size': 11,
                })
                
                # Format for header labels (left column)
                label_format = workbook.add_format({
                    'bold': True,
                    'align': 'right',
                    'valign': 'vcenter',
                    'font_size': 11,
                })
                
                # Write header information in 2x2 grid
                for row_num, row_data in enumerate(header_info):
                    for col_num, value in enumerate(row_data):
                        # Use label format for even columns (0, 2), info format for odd columns (1, 3)
                        fmt = label_format if col_num % 2 == 0 else info_format
                        worksheet.write(row_num, col_num, value, fmt)
                
                # Format for column headers
                header_format = workbook.add_format({
                    'bold': True,
                    'text_wrap': True,
                    'valign': 'top',
                    'align': 'center'
                })
                
                # Apply header format to column headers (row 4)
                for col_num, value in enumerate(df.columns.values):
                    worksheet.write(4, col_num, value, header_format)
                
                # Format for data rows
                data_format = workbook.add_format({
                    'align': 'center',
                    'valign': 'vcenter',
                })
                
                # Apply data format to all data cells
                worksheet.set_column(0, len(df.columns)-1, None, data_format)
                
                # Auto-adjust columns' width
                for i, col in enumerate(df.columns):
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.set_column(i, i, max_len)
                
                # Freeze the header row
                worksheet.freeze_panes(5, 0)  # Freeze row 5 (first data row)
                
                writer.close()
                output.seek(0)
                
                response = HttpResponse(
                    output.getvalue(),
                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
                response['Content-Disposition'] = f'attachment; filename="{course.code}_{exam.exam_name}_results.xlsx"'
                return response
            
            # PDF Download
            elif request.GET.get("download") == "pdf":
                response = HttpResponse(content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="{course.code}_{exam.exam_name}_results.pdf"'

                # Create PDF document
                pdf = SimpleDocTemplate(response, pagesize=letter)
                elements = []

                # Styles
                styles = getSampleStyleSheet()
                title = Paragraph(f"<b><font size=16>Exam Results Report: {exam.exam_name} (Course: {exam.course_code})</font></b>", styles['Title'])
                elements.append(title)
                elements.append(Spacer(1, 12))  # Add space below title

                # Header Information Table (4 rows)
                header_data = [
                    ["Programme:", student.branch if student else "N/A"],
                    ["Course Name:", course.name],
                    ["Course Code:", course.code],
                    ["Exam Name:", exam.exam_name]
                ]
                
                header_table = Table(header_data, colWidths=[120, '*'])  # '*' takes remaining width
                header_table.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 11),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('LEFTPADDING', (0, 0), (-1, -1), 3),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                elements.append(header_table)
                elements.append(Spacer(1, 24))  # Add space before results table

                # Results Table
                results_data = [
                    ["Sr.No", "Roll No", "Name", "Total Marks", "Obtained Marks"]
                ]
                
                for idx, result in enumerate(results, start=1):
                    results_data.append([
                        str(idx),
                        result.student.roll_no,
                        result.student.name.upper(),  # Uppercase names as in example
                        str(exam.total_marks),  # Using exam's total marks
                        str(result.obtained_marks),
                    ])

                # Create the table with adjusted column widths
                table = Table(results_data)
                style = TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Center align all text
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),  # Bold header
                    ('FONTSIZE', (0, 0), (-1, 0), 12),  # Header font size
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),  # Padding for header
                    ('FONTSIZE', (0, 1), (-1, -1), 10),  # Body font size
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)  # Table grid lines
                ])
                table.setStyle(style)
                elements.append(table)

                pdf.build(elements)
                return response


        except ExamSpecification.DoesNotExist:
            return HttpResponse("Exam not found.", status=404)
        except Course.DoesNotExist:
            return HttpResponse("Course not found.", status=404)

    return render(request, 'faculty/view_results.html', {'exam_results': exam_results})

from django.views.decorators.http import require_GET

@require_GET
def get_pending_students(request):
    exam_id = request.GET.get('exam_id')
    if not exam_id:
        return JsonResponse({'error': 'Exam ID required'}, status=400)
    
    try:
        exam = ExamSpecification.objects.get(id=exam_id)
        # Get all students registered for this exam's course
        all_students = Student.objects.filter(registered_courses=exam.course_code)
        # Get students who have already attempted
        attempted_roll_nos = Result.objects.filter(exam=exam).values_list('student__roll_no', flat=True)
        # Get pending students
        pending_students = all_students.exclude(roll_no__in=attempted_roll_nos)
        
        return JsonResponse({
            'pending_students': [
                {'roll_no': s.roll_no, 'name': s.name}
                for s in pending_students
            ]
        })
    except ExamSpecification.DoesNotExist:
        return JsonResponse({'error': 'Exam not found'}, status=404)
    
@require_GET
@user_passes_test(is_faculty, login_url='/faculty_login/')
def get_exam_stats(request):
    exam_id = request.GET.get('exam_id')
    if not exam_id:
        return JsonResponse({'error': 'Exam ID required'}, status=400)
    
    try:
        exam = ExamSpecification.objects.get(id=exam_id)
        total_students = Student.objects.filter(registered_courses=exam.course_code).count()
        results = Result.objects.filter(exam=exam)
        attempted_count = results.count()
        pending_count = total_students - attempted_count
        
        # Calculate average score
        avg_score = results.aggregate(avg=Avg('percentage'))['avg'] or 0
        
        # Get any new results (last 5 minutes)
        from django.utils import timezone
        from datetime import timedelta
        new_results = results.filter(
            submitted_at__gte=timezone.now() - timedelta(minutes=5)
        ).order_by('-submitted_at')
        
        return JsonResponse({
            'attempted_count': attempted_count,
            'pending_count': pending_count,
            'avg_score': avg_score,
            'new_results': [
                {
                    'roll_no': r.student.roll_no,
                    'name': r.student.name,
                    'total_marks': r.total_marks,
                    'obtained_marks': r.obtained_marks,
                    'percentage': float(r.percentage)
                }
                for r in new_results
            ]
        })
    except ExamSpecification.DoesNotExist:
        return JsonResponse({'error': 'Exam not found'}, status=404)
# Add course view
@login_required
@user_passes_test(is_faculty, login_url='/faculty_login/')
def view_student(request):
    """Detailed view of student exam statuses"""
    # Initialize variables
    students = Student.objects.all().order_by('branch', 'roll_no')
    courses = Course.objects.all()
    
    # Get filter parameters
    search_query = request.GET.get('search', '').strip()
    department_filter = request.GET.get('department', '').strip()
    course_filter = request.GET.get('course', '').strip()
    status_filter = request.GET.get('status', '').strip()

    # Apply filters
    if search_query:
        students = students.filter(
            Q(name__icontains=search_query) | 
            Q(roll_no__icontains=search_query) |
            Q(branch__icontains=search_query)
        )
    
    if department_filter:
        students = students.filter(branch=department_filter)
    
    if course_filter:
        students = students.filter(registered_courses__code=course_filter).distinct()
    
    if status_filter:
        if status_filter == "attended":
            students = students.filter(has_attempted_exam=True)
        elif status_filter == "not-attended":
            students = students.filter(has_attempted_exam=False)
        elif status_filter == "in-progress":
            students = students.filter(exam_start_time__isnull=False, has_attempted_exam=False)

    # Calculate time remaining for each student
    for student in students:
        if student.exam_start_time and not student.has_attempted_exam:
            time_elapsed = timezone.now() - student.exam_start_time
            student.time_remaining = max(0, 3600 - time_elapsed.total_seconds())  # Assuming 1 hour exam
        else:
            student.time_remaining = 0

    context = {
        'students': students,
        'courses': courses,
        'branches': Student.BRANCH_CHOICES,
        'search_query': search_query,
        'department_filter': department_filter,
        'course_filter': course_filter,
        'status_filter': status_filter,
    }
    return render(request, 'faculty/view_dashboard_student.html', context)

from django.db.models import Count, Sum,Avg,Q
@login_required
def exam_data(request):
    # Get all exams with basic statistics
    exams = ExamSpecification.objects.annotate(
        total_students=Count('result__student', distinct=True)
    ).order_by('-start_time')

    # Separate active and completed exams
    active_exams = exams.filter(is_active=True)
    completed_exams = exams.filter(is_active=False)

    # Calculate pass/fail counts for completed exams
    for exam in completed_exams:
        exam.pass_count = Result.objects.filter(
            exam=exam,
            percentage__gte=40
        ).count()
        exam.fail_count = Result.objects.filter(
            exam=exam,
            percentage__lt=40
        ).count()
        exam.avg_score = Result.objects.filter(
            exam=exam
        ).aggregate(Avg('percentage'))['percentage__avg'] or 0

    context = {
        'active_exams': active_exams,
        'completed_exams': completed_exams,
    }
    return render(request, 'faculty/exam_data.html', context)


from django.contrib.sessions.models import Session
from django.views.decorators.http import require_POST
@require_POST
@csrf_exempt
def force_logout(request, roll_no):
    try:
        student = Student.objects.get(roll_no=roll_no)
        user = student.user

        # Get all active sessions
        sessions = Session.objects.filter(expire_date__gte=timezone.now())

        # Filter sessions belonging to this user
        user_sessions = []
        for session in sessions:
            session_data = session.get_decoded()
            if '_auth_user_id' in session_data and str(session_data['_auth_user_id']) == str(user.id):
                user_sessions.append(session.session_key)

        # Delete all sessions for this user
        if user_sessions:
            Session.objects.filter(session_key__in=user_sessions).delete()

        # Reset exam state if student was in exam
        if student.exam_start_time and not student.has_attempted_exam:
            student.exam_start_time = None
            student.save()

        return JsonResponse({
            'success': True,
            'message': f'Student {roll_no} has been logged out from all sessions.'
        })

    except Student.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': f'Student with roll number {roll_no} not found.'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

from django.shortcuts import render
from django.utils import timezone

def faculty_bad_request(request, exception):
    context = {
        'error_code': '400',
        'error_message': 'Bad Request',
        'error_details': 'The server could not process your request.',
        'technical_details': {
            'timestamp': timezone.now(),
            'common_causes': [
                'Invalid form submission data',
                'Malformed file upload',
                'Invalid course or exam parameters',
                'Missing required fields in submission'
            ],
            'solutions': [
                'Verify all required fields are filled correctly',
                'Check file format and size requirements',
                'Ensure date formats are correct (YYYY-MM-DD)',
                'Validate CSV file structure before upload'
            ]
        }
    }
    return render(request, 'faculty/errors/400.html', context, status=400)

def faculty_permission_denied(request, exception):
    context = {
        'error_code': '403',
        'error_message': 'Access Forbidden',
        'error_details': 'You do not have sufficient permissions.',
        'technical_details': {
            'timestamp': timezone.now(),
            'common_causes': [
                'Session expired',
                'Invalid faculty credentials',
                'Attempting to access restricted area',
                'CSRF token verification failed'
            ],
            'solutions': [
                'Log in again with valid faculty credentials',
                'Contact system administrator for permission issues',
                'Verify your account has correct faculty privileges',
                'Do not use multiple tabs for sensitive operations'
            ]
        }
    }
    return render(request, 'faculty/errors/403.html', context, status=403)

def faculty_page_not_found(request, exception):
    context = {
        'error_code': '404',
        'error_message': 'Page Not Found',
        'error_details': 'The requested resource does not exist.',
        'technical_details': {
            'timestamp': timezone.now(),
            'common_causes': [
                'Deleted or moved resource',
                'Invalid exam or course ID',
                'Expired link',
                'Mistyped URL'
            ],
            'solutions': [
                'Verify the resource ID is correct',
                'Check if the exam/course still exists',
                'Navigate through the dashboard instead of direct URLs',
                'Contact technical support if the issue persists'
            ]
        }
    }
    return render(request, 'faculty/errors/404.html', context, status=404)

def faculty_server_error(request):
    context = {
        'error_code': '500',
        'error_message': 'Internal Server Error',
        'error_details': 'An unexpected error occurred on the server.',
        'technical_details': {
            'timestamp': timezone.now(),
            'common_causes': [
                'Database connection issues',
                'File system errors',
                'Memory allocation problems',
                'Unexpected server configuration'
            ],
            'solutions': [
                'Try the operation again after a few minutes',
                'Clear browser cache and cookies',
                'Check server logs for detailed error information',
                'Contact system administrator if the issue persists'
            ]
        }
    }
    return render(request, 'faculty/errors/500.html', context, status=500)
