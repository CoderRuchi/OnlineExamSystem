# Generated by Django 5.0.2 on 2025-04-23 05:16

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='StudentPermissions',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
            options={
                'permissions': [('can_view_student_dashboard', 'Can view student dashboard'), ('can_start_exma', 'Can start exam'), ('can_submit_exam', 'Can submit exam')],
            },
        ),
    ]
