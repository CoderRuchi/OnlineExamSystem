from django.db import models
from django.contrib.auth.models import User
import json
from django.contrib.auth.hashers import make_password
from django.utils.timezone import now


class Faculty(models.Model):
    user = models.OneToOneField(User,on_delete=models.CASCADE,null=True,blank=True)
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True,default="Unknown", null=True, blank=True)
    email = models.EmailField(unique=True,default="Unknown")
    password = models.CharField(max_length=255,default="Unknown")  # Store hashed passwords (use Django's make_password)
    def save(self, *args, **kwargs):
        self.password = make_password(self.password)  # Hash password before saving
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Course(models.Model):
    YEAR_CHOICES = [
        ("1st Year", "1st Year"),
        ("2nd Year", "2nd Year"),
        ("3rd Year", "3rd Year"),
    ]
    id = models.AutoField(primary_key=True)
    faculty = models.ForeignKey(Faculty, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, null=False, blank=False)
    code = models.CharField(max_length=50,null=False, blank=False,default='123451')
    year = models.CharField(max_length=10, choices=YEAR_CHOICES, null=False, blank=False,default='first')

    def __str__(self):
        return f"{self.name} ({self.code})"
    

class ExamSpecification(models.Model):
    EXAM_TYPES = [
        ('periodic', 'Periodic Test (30 Marks)'),
        ('final', 'Final Exam (70 Marks)'),
    ]
    faculty = models.ForeignKey(Faculty, on_delete=models.CASCADE,default=1)
    is_active = models.BooleanField(default=False)  # Track if the exam is active
    exam_name = models.CharField(max_length=255)
    course_code = models.CharField(max_length=50, unique=True,default='123451')  # Store course code
    exam_type = models.CharField(max_length=10, choices=EXAM_TYPES)
    num_units = models.IntegerField()
    question_sheet = models.JSONField()  # Store question count as a JSON dictionary
    total_questions = models.IntegerField(default=0)
    total_marks = models.IntegerField(default=30)  # Faculty-specified total marks
    start_time = models.DateTimeField(null=True, blank=True)  # Exam start time
    end_time = models.DateTimeField(null=True, blank=True)  # Exam end time
    marks_per_unit = models.JSONField(default=list)  # Store marks per unit as a JSON dictionary
    max_mark = models.IntegerField(default=1)  # Maximum marks for a question
    exam_duration_hours = models.IntegerField(default=1)  # New field
    exam_duration_minutes = models.IntegerField(default=0) # New field
    question_per_unit = models.JSONField(default=dict)

    def __str__(self):
        return f"{self.exam_name} ({self.get_exam_type_display()}) - {self.total_marks} Marks"

        
class Question(models.Model):
    sr_no = models.IntegerField(null=True,blank=True)
    course_code=models.CharField(max_length=255,null=True,blank=True)
    course_name=models.CharField(max_length=255,null=True,blank=True)
    question_text = models.TextField()
    latex_equation = models.TextField(null=True, blank=True)  # New field for LaTeX equations
    option1 = models.CharField(max_length=255,default="Option A")
    option2 = models.CharField(max_length=255,default="Option B")
    option3 = models.CharField(max_length=255,default="Option C")
    option4 = models.CharField(max_length=255,default="Option D")
    correct_answer = models.CharField(max_length=255,default="Option 1")
    user_c_answer = models.CharField(max_length=255,blank=True,null=True)
    mark = models.IntegerField(default=1)
    unit_no = models.IntegerField()
    image_path = models.CharField(default=None,max_length=255, null=True, blank=True)
    
    def __str__(self):
        return self.question_text


class Student(models.Model):
    BRANCH_CHOICES = [
        ("Computer Technology", "Computer Technology"),
        ("Information Technology", "Information Technology"),
        ("Electronics", "Electronics"),
        ("Mechanical", "Mechanical"),
        ("Civil", "Civil"),
    ]
    branch = models.CharField(max_length=50, choices=BRANCH_CHOICES, null=False, blank=False,default='IF')
    user = models.OneToOneField(User,on_delete=models.CASCADE,null=True,blank=True)
    roll_no = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    password = models.CharField(max_length=20)  # Same as roll_no
    attendance_status = models.BooleanField(default=True)  # True for present, False for absent
    registered_courses = models.ManyToManyField(Course, related_name="students")   #student has multiple courses registered
    has_attempted_exam = models.BooleanField(default=False)
    time_remaining = models.IntegerField(default=0)  # No default value
  # Stores remaining time in seconds
    exam_start_time = models.DateTimeField(null=True, blank=True)  # Exam start time
    is_manually_added = models.BooleanField(default=False)  # New field to track manual addition
    def __str__(self):
        return f"{self.roll_no} - {self.name}"
    
class Result(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    exam = models.ForeignKey(ExamSpecification, on_delete=models.CASCADE,default=1)  # Link to the exam
    total_marks = models.IntegerField(default=0)
    obtained_marks = models.IntegerField(default=0)
    percentage = models.FloatField(default=0.0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.name} - {self.obtained_marks}/{self.total_marks}"