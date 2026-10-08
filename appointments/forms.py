from django import forms
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Doctor, Patient, Appointment, MedicalReport, TIME_SLOTS, DepartmentChoices, AppointmentStatusChoices


class AppointmentBookingForm(forms.ModelForm):
    # Patient fields for unauthenticated or first-time patients
    patient_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Full Name'
        })
    )
    patient_email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'name@example.com'
        })
    )
    patient_phone = forms.CharField(
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+1 (555) 000-0000'
        })
    )
    patient_gender = forms.ChoiceField(
        choices=Patient.GENDER_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    patient_dob = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    class Meta:
        model = Appointment
        fields = ['doctor', 'date', 'time_slot', 'reason']
        widgets = {
            'doctor': forms.Select(attrs={'class': 'form-select', 'id': 'id_doctor'}),
            'date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'id': 'id_date'
            }),
            'time_slot': forms.Select(attrs={'class': 'form-select', 'id': 'id_time_slot'}),
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Briefly describe your symptoms or reason for visit...'
            }),
        }

    def __init__(self, *args, **kwargs):
        patient_instance = kwargs.pop('patient_instance', None)
        super().__init__(*args, **kwargs)

        # Only list active doctors
        self.fields['doctor'].queryset = Doctor.objects.filter(active_status=True).order_by('department', 'name')

        # Set minimum date attribute to today
        today_str = timezone.localdate().isoformat()
        self.fields['date'].widget.attrs['min'] = today_str

        # If patient profile is already available, prefill and make fields optional
        if patient_instance:
            self.patient_instance = patient_instance
            self.fields['patient_name'].initial = patient_instance.name
            self.fields['patient_email'].initial = patient_instance.email
            self.fields['patient_phone'].initial = patient_instance.phone
            self.fields['patient_gender'].initial = patient_instance.gender
            if patient_instance.date_of_birth:
                self.fields['patient_dob'].initial = patient_instance.date_of_birth
            self.fields['patient_name'].required = False
            self.fields['patient_email'].required = False
            self.fields['patient_phone'].required = False
        else:
            self.patient_instance = None

    def clean_date(self):
        date = self.cleaned_data.get('date')
        if date and date < timezone.localdate():
            raise forms.ValidationError("Appointment date cannot be in the past.")
        return date

    def clean(self):
        cleaned_data = super().clean()
        doctor = cleaned_data.get('doctor')
        date = cleaned_data.get('date')
        time_slot = cleaned_data.get('time_slot')

        # Fallback to patient_instance for authenticated patients
        if self.patient_instance:
            if not cleaned_data.get('patient_name'):
                cleaned_data['patient_name'] = self.patient_instance.name
            if not cleaned_data.get('patient_email'):
                cleaned_data['patient_email'] = self.patient_instance.email
            if not cleaned_data.get('patient_phone'):
                cleaned_data['patient_phone'] = self.patient_instance.phone

        if doctor and not doctor.active_status:
            raise forms.ValidationError(f"Dr. {doctor.name} is currently inactive and cannot accept appointments.")

        if time_slot and time_slot not in dict(TIME_SLOTS):
            raise forms.ValidationError("Invalid time slot selected. Please select a valid slot.")

        if doctor and date and time_slot:
            # Check for double booking
            existing = Appointment.objects.filter(
                doctor=doctor,
                date=date,
                time_slot=time_slot
            ).exclude(status=AppointmentStatusChoices.CANCELLED)

            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)

            if existing.exists():
                raise forms.ValidationError(
                    f"Dr. {doctor.name} already has an appointment booked for {date} at {dict(TIME_SLOTS).get(time_slot, time_slot)}. Please select another slot."
                )

        return cleaned_data


class DoctorFilterForm(forms.Form):
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search doctor name or specialization...'
        })
    )
    department = forms.ChoiceField(
        choices=[('', 'All Departments')] + list(DepartmentChoices.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class AppointmentStatusForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select form-select-sm'})
        }


class MedicalReportForm(forms.ModelForm):
    class Meta:
        model = MedicalReport
        fields = ['diagnosis', 'prescription', 'doctor_notes']
        widgets = {
            'diagnosis': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Clinical diagnosis...'
            }),
            'prescription': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Prescribed medications, dosage, and frequency...'
            }),
            'doctor_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Follow-up advice, dietary instructions, or next visit timeline...'
            }),
        }


class PatientRegistrationForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address'})
    )
    phone = forms.CharField(
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'})
    )
    gender = forms.ChoiceField(
        choices=Patient.GENDER_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    blood_group = forms.CharField(
        max_length=5,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. O+, A+'})
    )
    address = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Residential Address'})
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password (min 6 characters)'})
    )
    confirm_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'})
    )

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Username already taken. Please choose another.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password')
        p2 = cleaned_data.get('confirm_password')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        if p1 and len(p1) < 6:
            raise forms.ValidationError("Password must be at least 6 characters long.")
        return cleaned_data
