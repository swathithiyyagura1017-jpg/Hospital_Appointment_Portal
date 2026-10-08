from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone


class DepartmentChoices(models.TextChoices):
    CARDIOLOGY = 'Cardiology', 'Cardiology'
    PEDIATRICS = 'Pediatrics', 'Pediatrics'
    ORTHOPEDICS = 'Orthopedics', 'Orthopedics'
    NEUROLOGY = 'Neurology', 'Neurology'


class AppointmentStatusChoices(models.TextChoices):
    PENDING = 'Pending', 'Pending'
    CONFIRMED = 'Confirmed', 'Confirmed'
    COMPLETED = 'Completed', 'Completed'
    CANCELLED = 'Cancelled', 'Cancelled'


TIME_SLOTS = [
    ('09:00-09:30', '09:00 AM - 09:30 AM'),
    ('09:30-10:00', '09:30 AM - 10:00 AM'),
    ('10:00-10:30', '10:00 AM - 10:30 AM'),
    ('10:30-11:00', '10:30 AM - 11:00 AM'),
    ('11:00-11:30', '11:00 AM - 11:30 AM'),
    ('11:30-12:00', '11:30 AM - 12:00 PM'),
    ('14:00-14:30', '02:00 PM - 02:30 PM'),
    ('14:30-15:00', '02:30 PM - 03:00 PM'),
    ('15:00-15:30', '03:00 PM - 03:30 PM'),
    ('15:30-16:00', '03:30 PM - 04:00 PM'),
    ('16:00-16:30', '04:00 PM - 04:30 PM'),
    ('16:30-17:00', '04:30 PM - 05:00 PM'),
]


class Doctor(models.Model):
    name = models.CharField(max_length=150)
    department = models.CharField(
        max_length=50,
        choices=DepartmentChoices.choices
    )
    specialization = models.CharField(max_length=150)
    consultation_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=50.00,
        help_text="Consultation fee in USD / standard currency"
    )
    available_days = models.CharField(
        max_length=200,
        default="Monday, Tuesday, Wednesday, Thursday, Friday",
        help_text="Comma-separated available days"
    )
    active_status = models.BooleanField(
        default=True,
        help_text="Active status indicates if doctor is taking appointments"
    )
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True)
    bio = models.TextField(blank=True)
    experience_years = models.PositiveIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"Dr. {self.name} ({self.department} - {self.specialization})"

    @property
    def available_days_list(self):
        return [day.strip() for day in self.available_days.split(',') if day.strip()]


class Patient(models.Model):
    GENDER_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='patient_profile'
    )
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='Male')
    blood_group = models.CharField(max_length=5, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Appointment(models.Model):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name='appointments'
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name='appointments'
    )
    date = models.DateField()
    time_slot = models.CharField(max_length=20, choices=TIME_SLOTS)
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=AppointmentStatusChoices.choices,
        default=AppointmentStatusChoices.PENDING
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'time_slot']
        constraints = [
            models.UniqueConstraint(
                fields=['doctor', 'date', 'time_slot'],
                condition=~models.Q(status=AppointmentStatusChoices.CANCELLED),
                name='unique_doctor_active_timeslot'
            )
        ]

    def clean(self):
        super().clean()
        # Validate appointment date is not in the past
        if self.date and self.date < timezone.localdate():
            raise ValidationError({'date': "Appointment date cannot be in the past."})

        # Validate doctor is active
        if self.doctor_id and not self.doctor.active_status:
            raise ValidationError({'doctor': f"Dr. {self.doctor.name} is currently inactive and cannot accept appointments."})

        # Validate unique slot for doctor on date (ignoring cancelled)
        if self.doctor_id and self.date and self.time_slot:
            overlapping = Appointment.objects.filter(
                doctor=self.doctor,
                date=self.date,
                time_slot=self.time_slot
            ).exclude(status=AppointmentStatusChoices.CANCELLED)

            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)

            if overlapping.exists():
                raise ValidationError({
                    'time_slot': f"This time slot ({self.get_time_slot_display()}) with Dr. {self.doctor.name} on {self.date} is already booked."
                })

    def __str__(self):
        return f"Appointment #{self.pk or 'New'}: {self.patient.name} with Dr. {self.doctor.name} on {self.date} ({self.time_slot}) [{self.status}]"


class MedicalReport(models.Model):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name='medical_reports'
    )
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='medical_report'
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name='medical_reports'
    )
    diagnosis = models.TextField()
    prescription = models.TextField(blank=True)
    doctor_notes = models.TextField(blank=True)
    report_date = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-report_date', '-created_at']

    def __str__(self):
        return f"Medical Report for {self.patient.name} by Dr. {self.doctor.name} on {self.report_date}"
