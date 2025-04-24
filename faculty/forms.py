from django import forms
from django.contrib.auth.models import User
class CSVUploadForm(forms.Form):
    file = forms.FileField()

class CSVUploadStudentForm(forms.Form):
    file = forms.FileField()

class FacultyRegisterForm(forms.ModelForm):
    password1 = forms.CharField(label='Password',widget=forms.PasswordInput)
    password2 = forms.CharField(label='Confirm Password',widget=forms.PasswordInput)

    class Meta:
        model = User 
        fields = ('username','email')

    def check_password(self):
        if self.cleaned_data['password'] != self.cleaned_data['password2']:
            raise forms.ValidationError("Passwords didn't match")
        return self.cleaned_data['password2']

from django import forms
from .models import Question

class QuestionEditForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = [
            'sr_no',
            'course_code',
            'question_text',
            'option1',
            'option2',
            'option3',
            'option4',
            'correct_answer',
            'mark',
            'unit_no',
            'latex_equation'
        ]
        widgets = {
            'question_text': forms.Textarea(attrs={'rows': 3}),
            'option1': forms.Textarea(attrs={'rows': 2}),
            'option2': forms.Textarea(attrs={'rows': 2}),
            'option3': forms.Textarea(attrs={'rows': 2}),
            'option4': forms.Textarea(attrs={'rows': 2}),
        }