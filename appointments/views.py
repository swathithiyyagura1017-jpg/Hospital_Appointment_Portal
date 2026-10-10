import os
import secrets
import logging
from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.http import JsonResponse, Http404
from django.utils import timezone
from django.db.models import Q, Count

logger = logging.getLogger('appointments.auth')

from functools import wraps
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .models import (
    Doctor, Patient, Appointment, MedicalReport,
    DepartmentChoices, AppointmentStatusChoices, TIME_SLOTS
)
from .forms import (
    AppointmentBookingForm, DoctorFilterForm,
    AppointmentStatusForm, MedicalReportForm, PatientRegistrationForm
)


def is_hospital_staff(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def staff_required(view_func):
    """
    Decorator for views that checks that the user is logged in and is a staff member or superuser.
    Redirects unauthenticated users to login, and non-staff authenticated users to patient_dashboard with a warning.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse('patient_login')
            return redirect(f"{login_url}?next={request.path}")
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(request, "Access restricted. Hospital staff privileges are required to view this page.")
            return redirect('patient_dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


# --- Public / Doctor Views ---

def home_view(request):
    """Hospital Portal Landing Page"""
    departments = DepartmentChoices.choices
    doctors_count = Doctor.objects.filter(active_status=True).count()
    dept_stats = []
    for dept_code, dept_name in departments:
        count = Doctor.objects.filter(department=dept_code, active_status=True).count()
        dept_stats.append({
            'code': dept_code,
            'name': dept_name,
            'count': count
        })

    featured_doctors = Doctor.objects.filter(active_status=True).order_by('?')[:4]

    context = {
        'dept_stats': dept_stats,
        'doctors_count': doctors_count,
        'featured_doctors': featured_doctors,
    }
    return render(request, 'appointments/home.html', context)


def doctor_list_view(request):
    """Doctor Directory with Search and Department Filter"""
    doctors = Doctor.objects.filter(active_status=True)
    departments = [d[0] for d in DepartmentChoices.choices]

    search_query = request.GET.get('search', '').strip()
    selected_department = request.GET.get('department', '').strip()

    if search_query:
        doctors = doctors.filter(
            Q(name__icontains=search_query) |
            Q(specialization__icontains=search_query) |
            Q(department__icontains=search_query) |
            Q(bio__icontains=search_query)
        )

    if selected_department and selected_department in departments:
        doctors = doctors.filter(department=selected_department)

    filter_form = DoctorFilterForm(initial={
        'search': search_query,
        'department': selected_department
    })

    context = {
        'doctors': doctors,
        'departments': departments,
        'selected_department': selected_department,
        'search_query': search_query,
        'filter_form': filter_form,
        'total_doctors': doctors.count(),
    }
    return render(request, 'appointments/doctor_list.html', context)


def doctor_detail_view(request, pk):
    """Detailed Doctor profile"""
    doctor = get_object_or_404(Doctor, pk=pk)
    upcoming_slots_count = len(doctor.available_days_list)
    context = {
        'doctor': doctor,
        'upcoming_slots_count': upcoming_slots_count,
    }
    return render(request, 'appointments/doctor_detail.html', context)


# --- Appointment Booking & API ---

def api_get_slots(request):
    """
    JSON API returning slot availability for a given doctor and date.
    Used by JavaScript ES6 frontend dynamically.
    """
    doctor_id = request.GET.get('doctor_id')
    date_str = request.GET.get('date')

    if not doctor_id or not date_str:
        return JsonResponse({'error': 'doctor_id and date are required parameters.'}, status=400)

    try:
        doctor = Doctor.objects.get(pk=doctor_id)
    except Doctor.DoesNotExist:
        return JsonResponse({'error': 'Doctor not found.'}, status=404)

    try:
        app_date = date.fromisoformat(date_str)
    except ValueError:
        return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

    # Check if date is in the past
    is_past = app_date < timezone.localdate()

    # Query already booked slots for this doctor and date (exclude Cancelled)
    booked_slots = set(
        Appointment.objects.filter(
            doctor=doctor,
            date=app_date
        ).exclude(status=AppointmentStatusChoices.CANCELLED)
        .values_list('time_slot', flat=True)
    )

    slots_data = []
    for slot_code, slot_label in TIME_SLOTS:
        is_booked = slot_code in booked_slots
        slots_data.append({
            'code': slot_code,
            'label': slot_label,
            'available': (not is_booked) and (not is_past),
            'is_booked': is_booked,
            'is_past': is_past,
        })

    return JsonResponse({
        'doctor': doctor.name,
        'date': date_str,
        'slots': slots_data,
        'total_slots': len(TIME_SLOTS),
        'available_count': sum(1 for s in slots_data if s['available']),
    })


def book_appointment_view(request):
    """Create / Book an appointment with date and time-slot selection"""
    doctor_id = request.GET.get('doctor_id')
    selected_doctor = None
    if doctor_id:
        selected_doctor = Doctor.objects.filter(pk=doctor_id, active_status=True).first()

    patient_profile = None
    if request.user.is_authenticated and hasattr(request.user, 'patient_profile'):
        patient_profile = request.user.patient_profile

    if request.method == 'POST':
        form = AppointmentBookingForm(request.POST, patient_instance=patient_profile)
        if form.is_valid():
            doctor = form.cleaned_data['doctor']
            app_date = form.cleaned_data['date']
            time_slot = form.cleaned_data['time_slot']
            reason = form.cleaned_data['reason']

            # Resolve or create Patient
            if patient_profile:
                patient = patient_profile
            else:
                p_email = form.cleaned_data['patient_email'].strip().lower()
                p_name = form.cleaned_data['patient_name'].strip()
                p_phone = form.cleaned_data['patient_phone'].strip()
                p_gender = form.cleaned_data.get('patient_gender') or 'Male'
                p_dob = form.cleaned_data.get('patient_dob')

                patient, _ = Patient.objects.get_or_create(
                    email=p_email,
                    defaults={
                        'name': p_name,
                        'phone': p_phone,
                        'gender': p_gender,
                        'date_of_birth': p_dob,
                        'user': request.user if request.user.is_authenticated else None
                    }
                )

            # Prevent double booking race condition via ORM
            existing_booking = Appointment.objects.filter(
                doctor=doctor,
                date=app_date,
                time_slot=time_slot
            ).exclude(status=AppointmentStatusChoices.CANCELLED).first()

            if existing_booking:
                messages.error(
                    request,
                    f"Sorry! The slot {dict(TIME_SLOTS).get(time_slot, time_slot)} with Dr. {doctor.name} on {app_date} was just booked. Please pick another slot."
                )
            else:
                appointment = form.save(commit=False)
                appointment.patient = patient
                appointment.status = AppointmentStatusChoices.PENDING
                appointment.save()

                messages.success(
                    request,
                    f"Appointment request submitted successfully! Reference #{appointment.id}."
                )
                return redirect('appointment_success', pk=appointment.pk)
        else:
            messages.error(request, "Please correct the errors in the form below.")
    else:
        initial_data = {}
        if selected_doctor:
            initial_data['doctor'] = selected_doctor.id
        form = AppointmentBookingForm(initial=initial_data, patient_instance=patient_profile)

    context = {
        'form': form,
        'selected_doctor': selected_doctor,
        'time_slots': TIME_SLOTS,
        'today': timezone.localdate().isoformat(),
    }
    return render(request, 'appointments/book_appointment.html', context)


def appointment_success_view(request, pk):
    """Booking Confirmation Page"""
    appointment = get_object_or_404(Appointment, pk=pk)
    context = {
        'appointment': appointment,
    }
    return render(request, 'appointments/booking_success.html', context)


# --- Patient Portal Views ---

@login_required
def patient_dashboard_view(request):
    """Patient Dashboard showing upcoming & past appointments, and reports"""
    # Get or create patient profile for logged in user
    patient, _ = Patient.objects.get_or_create(
        user=request.user,
        defaults={
            'name': f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username,
            'email': request.user.email or f"{request.user.username}@example.com",
            'phone': 'Not provided'
        }
    )

    today = timezone.localdate()
    appointments = Appointment.objects.filter(patient=patient).select_related('doctor', 'medical_report')

    upcoming_appointments = appointments.filter(
        date__gte=today
    ).exclude(status__in=[AppointmentStatusChoices.COMPLETED, AppointmentStatusChoices.CANCELLED]).order_by('date', 'time_slot')

    past_appointments = appointments.filter(
        Q(date__lt=today) |
        Q(status__in=[AppointmentStatusChoices.COMPLETED, AppointmentStatusChoices.CANCELLED])
    ).order_by('-date', '-time_slot')

    medical_reports = MedicalReport.objects.filter(patient=patient).select_related('doctor', 'appointment')

    context = {
        'patient': patient,
        'upcoming_appointments': upcoming_appointments,
        'past_appointments': past_appointments,
        'medical_reports': medical_reports,
        'total_appointments': appointments.count(),
        'confirmed_count': appointments.filter(status=AppointmentStatusChoices.CONFIRMED).count(),
        'pending_count': appointments.filter(status=AppointmentStatusChoices.PENDING).count(),
        'completed_count': appointments.filter(status=AppointmentStatusChoices.COMPLETED).count(),
    }
    return render(request, 'appointments/patient_dashboard.html', context)


@login_required
def cancel_appointment_view(request, pk):
    """Patient or Staff can cancel an appointment securely via POST"""
    if request.method != 'POST':
        messages.error(request, "Invalid request method for appointment cancellation. POST is required.")
        return redirect('patient_dashboard')

    appointment = get_object_or_404(Appointment, pk=pk)

    # Permission check: must be the patient owner or hospital staff
    is_owner = hasattr(request.user, 'patient_profile') and appointment.patient == request.user.patient_profile
    if not (is_owner or request.user.is_staff):
        messages.error(request, "You are not authorized to cancel this appointment.")
        return redirect('patient_dashboard')

    if appointment.status == AppointmentStatusChoices.COMPLETED:
        messages.error(request, "Completed appointments cannot be cancelled.")
    elif appointment.status == AppointmentStatusChoices.CANCELLED:
        messages.info(request, "This appointment is already cancelled.")
    else:
        appointment.status = AppointmentStatusChoices.CANCELLED
        appointment.save()
        messages.success(request, f"Appointment #{appointment.id} has been successfully cancelled.")

    if request.user.is_staff:
        return redirect('staff_dashboard')
    return redirect('patient_dashboard')


# --- Admin / Staff Workflow Views ---

@staff_required
def staff_dashboard_view(request):
    """
    Hospital Staff / Administrator Portal:
    Manage doctors, appointments, statuses, and consultation reports.
    """
    status_filter = request.GET.get('status', '').strip()
    dept_filter = request.GET.get('department', '').strip()
    date_filter = request.GET.get('date', '').strip()
    search = request.GET.get('search', '').strip()

    appointments = Appointment.objects.select_related('patient', 'doctor').all()

    if status_filter:
        appointments = appointments.filter(status=status_filter)
    if dept_filter:
        appointments = appointments.filter(doctor__department=dept_filter)
    if date_filter:
        appointments = appointments.filter(date=date_filter)
    if search:
        appointments = appointments.filter(
            Q(patient__name__icontains=search) |
            Q(patient__phone__icontains=search) |
            Q(doctor__name__icontains=search) |
            Q(reason__icontains=search)
        )

    # Metric counts
    total_count = Appointment.objects.count()
    today_count = Appointment.objects.filter(date=timezone.localdate()).count()
    pending_count = Appointment.objects.filter(status=AppointmentStatusChoices.PENDING).count()
    confirmed_count = Appointment.objects.filter(status=AppointmentStatusChoices.CONFIRMED).count()
    completed_count = Appointment.objects.filter(status=AppointmentStatusChoices.COMPLETED).count()
    cancelled_count = Appointment.objects.filter(status=AppointmentStatusChoices.CANCELLED).count()

    context = {
        'appointments': appointments,
        'status_choices': AppointmentStatusChoices.choices,
        'departments': [d[0] for d in DepartmentChoices.choices],
        'current_status': status_filter,
        'current_dept': dept_filter,
        'current_date': date_filter,
        'search': search,
        'total_count': total_count,
        'today_count': today_count,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'completed_count': completed_count,
        'cancelled_count': cancelled_count,
    }
    return render(request, 'appointments/staff_dashboard.html', context)


@staff_required
def update_appointment_status_view(request, pk):
    """
    Action for hospital staff/superusers to update an appointment's status.
    Requires POST method with CSRF protection.
    Enforces business logic:
    - Pending: Confirm or Cancel
    - Confirmed: Mark Completed or Cancel
    - Completed: Cannot be modified
    - Cancelled: Cannot be modified
    """
    appointment = get_object_or_404(Appointment, pk=pk)

    if request.method != 'POST':
        messages.error(request, "Invalid request method for status update. POST is required.")
        return redirect('staff_dashboard')

    new_status = request.POST.get('status')
    if not new_status or new_status not in AppointmentStatusChoices.values:
        messages.error(request, f"Invalid status '{new_status}' provided.")
        return redirect('staff_dashboard')

    # Prevent modifications to already completed or cancelled appointments
    if appointment.status == AppointmentStatusChoices.CANCELLED:
        messages.warning(request, f"Appointment #{appointment.id} is already cancelled and cannot be modified.")
        return redirect('staff_dashboard')

    if appointment.status == AppointmentStatusChoices.COMPLETED:
        messages.warning(request, f"Appointment #{appointment.id} is completed and cannot be modified.")
        return redirect('staff_dashboard')

    # Status transition rules
    if appointment.status == AppointmentStatusChoices.PENDING:
        if new_status in [AppointmentStatusChoices.CONFIRMED, AppointmentStatusChoices.CANCELLED]:
            appointment.status = new_status
            appointment.save()
            messages.success(request, f"Appointment #{appointment.id} status updated to {new_status}.")
        else:
            messages.warning(request, f"Pending appointments cannot be transitioned directly to {new_status}.")
        return redirect('staff_dashboard')

    if appointment.status == AppointmentStatusChoices.CONFIRMED:
        if new_status in [AppointmentStatusChoices.COMPLETED, AppointmentStatusChoices.CANCELLED]:
            appointment.status = new_status
            appointment.save()
            messages.success(request, f"Appointment #{appointment.id} status updated to {new_status}.")
        else:
            messages.warning(request, f"Confirmed appointments cannot be transitioned to {new_status}.")
        return redirect('staff_dashboard')

    return redirect('staff_dashboard')


@staff_required
def add_medical_report_view(request, appointment_id):
    """
    Create a medical consultation report for an appointment.
    Workflow:
    Staff Dashboard -> Select Appointment -> Add Report -> Submit -> Redirect to Report Detail
    Validates:
    - Appointment exists
    - Patient and Doctor correctly associated
    - Avoids duplicate reports (redirects safely to existing report)
    - Rejects report creation on cancelled appointments
    """
    appointment = get_object_or_404(Appointment, pk=appointment_id)

    # Rejection of report on cancelled appointment
    if appointment.status == AppointmentStatusChoices.CANCELLED:
        messages.error(request, f"Cannot create a medical report for cancelled appointment #{appointment.id}.")
        return redirect('staff_dashboard')

    # Check if a report already exists for this appointment to prevent duplicates
    existing_report = getattr(appointment, 'medical_report', None)
    if existing_report:
        messages.info(request, f"A medical report already exists for Appointment #{appointment.id}. Viewing existing report.")
        return redirect('medical_report_detail', pk=existing_report.pk)

    if request.method == 'POST':
        form = MedicalReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.appointment = appointment
            report.patient = appointment.patient
            report.doctor = appointment.doctor
            report.save()

            # Automatically transition appointment to Completed if not already
            if appointment.status != AppointmentStatusChoices.COMPLETED:
                appointment.status = AppointmentStatusChoices.COMPLETED
                appointment.save()

            messages.success(request, f"Medical consultation report saved successfully for {appointment.patient.name}.")
            return redirect('medical_report_detail', pk=report.pk)
        else:
            messages.error(request, "Please correct the errors in the medical report form.")
    else:
        form = MedicalReportForm()

    context = {
        'form': form,
        'appointment': appointment,
    }
    return render(request, 'appointments/add_medical_report.html', context)


@login_required
def medical_report_detail_view(request, pk):
    """View full medical report slip - protected for patient owner or hospital staff"""
    report = get_object_or_404(MedicalReport, pk=pk)

    # Auth check: patient owner or hospital staff
    is_owner = hasattr(request.user, 'patient_profile') and report.patient == request.user.patient_profile
    if not (is_owner or request.user.is_staff):
        messages.error(request, "You are not authorized to view this medical report.")
        return redirect('patient_dashboard')

    context = {
        'report': report,
    }
    return render(request, 'appointments/medical_report_detail.html', context)


# --- Authentication Views ---

def patient_register_view(request):
    """Register a new patient account using Django authentication"""
    if request.user.is_authenticated:
        return redirect('patient_dashboard')

    if request.method == 'POST':
        form = PatientRegistrationForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            name = form.cleaned_data['name']
            phone = form.cleaned_data['phone']
            gender = form.cleaned_data['gender']
            dob = form.cleaned_data.get('date_of_birth')
            blood = form.cleaned_data.get('blood_group', '')
            address = form.cleaned_data.get('address', '')

            # Create User using Django auth
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=name.split()[0] if name else '',
                last_name=" ".join(name.split()[1:]) if len(name.split()) > 1 else ''
            )

            # Create or update Patient record linked to User
            patient, created = Patient.objects.get_or_create(
                email=email,
                defaults={
                    'user': user,
                    'name': name,
                    'phone': phone,
                    'gender': gender,
                    'date_of_birth': dob,
                    'blood_group': blood,
                    'address': address,
                }
            )
            if not created:
                patient.user = user
                patient.name = name
                patient.phone = phone
                patient.gender = gender
                if dob:
                    patient.date_of_birth = dob
                if blood:
                    patient.blood_group = blood
                if address:
                    patient.address = address
                patient.save()

            login(request, user, backend='appointments.backends.EmailOrUsernameModelBackend')
            logger.info(
                f"Registered new patient user '{user.username}' (email='{user.email}', "
                f"total_users_in_db={User.objects.count()})"
            )
            messages.success(request, f"Welcome to the portal, {name}! Your patient account has been created.")
            return redirect('patient_dashboard')
    else:
        form = PatientRegistrationForm()

    return render(request, 'appointments/register.html', {'form': form})


def patient_login_view(request):
    """Login view for patients and staff using Django AuthenticationForm with safe diagnostic logging"""
    if request.method == 'POST':
        raw_identifier = request.POST.get('username', '').strip()
        total_users = User.objects.count()
        matched_user = User.objects.filter(
            Q(username__iexact=raw_identifier) | Q(email__iexact=raw_identifier)
        ).first()
        user_found = bool(matched_user)
        is_active = matched_user.is_active if matched_user else False

        logger.info(
            f"Login attempt received: identifier='{raw_identifier}', "
            f"user_found={user_found}, is_active={is_active}, total_users_in_db={total_users}"
        )

        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            logger.info(
                f"Login successful: user_id={user.id}, username='{user.username}', "
                f"is_staff={user.is_staff}, is_superuser={user.is_superuser}"
            )
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            if user.is_staff or user.is_superuser:
                return redirect('staff_dashboard')
            return redirect('patient_dashboard')
        else:
            logger.warning(
                f"Login rejected: identifier='{raw_identifier}', "
                f"user_found={user_found}, "
                f"reason={'password mismatch' if user_found else 'user not found in database'}, "
                f"total_users_in_db={total_users}"
            )
            messages.error(request, "Invalid username or password. Please try again.")
    else:
        form = AuthenticationForm()

    return render(request, 'appointments/login.html', {
        'form': form,
        'next': request.POST.get('next') or request.GET.get('next', '')
    })


def patient_logout_view(request):
    """Secure logout view for authenticated users"""
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, "You have been securely logged out.")
    return redirect('home')


@login_required
def activate_staff_view(request):
    """
    Secure, temporary one-time staff activation endpoint.
    Security rules:
    - Disabled (returns 404) if STAFF_ACTIVATION_KEY is not set or empty in environment.
    - Requires the user to be logged in (@login_required).
    - Submitted username must match request.user.username (prevents activating other accounts).
    - Secret key compared securely using constant-time secrets.compare_digest.
    - Grants is_staff=True, is_superuser=False.
    - Preserves passwords, patient profiles, doctors, and appointments.
    """
    server_key = os.environ.get('STAFF_ACTIVATION_KEY')
    if not server_key or not server_key.strip():
        raise Http404("Staff activation is disabled on this server.")

    if request.method == 'POST':
        submitted_username = request.POST.get('username', '').strip()
        submitted_key = request.POST.get('activation_key', '').strip()

        # Enforce that the submitted username matches the currently authenticated user
        if not submitted_username or submitted_username != request.user.username:
            messages.error(request, "Permission denied: You can only activate staff access for your own authenticated account.")
            return render(request, 'appointments/activate_staff.html')

        # Secure constant-time comparison against the environment secret
        if not secrets.compare_digest(submitted_key, server_key.strip()):
            messages.error(request, "Invalid activation secret key. Access denied.")
            return render(request, 'appointments/activate_staff.html')

        # If user is already staff, inform and route to dashboard
        if request.user.is_staff:
            messages.info(request, "Your account already has staff privileges.")
            return redirect('staff_dashboard')

        # Grant staff privileges without altering passwords, superuser, or other data
        user = request.user
        user.is_staff = True
        user.is_superuser = False
        user.save(update_fields=['is_staff', 'is_superuser'])

        messages.success(
            request,
            f"Staff privileges successfully activated for '{user.username}'! Welcome to the Staff Management Portal."
        )
        return redirect('staff_dashboard')

    return render(request, 'appointments/activate_staff.html')

