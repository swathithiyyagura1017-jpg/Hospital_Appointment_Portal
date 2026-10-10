import io
import os
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.contrib.auth.models import User
from appointments.models import (
    Doctor, Patient, Appointment, MedicalReport,
    DepartmentChoices, AppointmentStatusChoices, TIME_SLOTS
)


class HospitalPortalModelTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.doctor = Doctor.objects.create(
            name="Gregory House",
            department=DepartmentChoices.NEUROLOGY,
            specialization="Diagnostic Medicine & Neurology",
            consultation_fee=150.00,
            available_days="Monday, Wednesday, Friday",
            active_status=True
        )
        self.patient = Patient.objects.create(
            name="Jane Doe",
            email="jane@example.com",
            phone="+1-555-4321",
            gender="Female"
        )

    def test_doctor_creation_and_properties(self):
        self.assertEqual(str(self.doctor), "Dr. Gregory House (Neurology - Diagnostic Medicine & Neurology)")
        self.assertIn("Monday", self.doctor.available_days_list)
        self.assertIn("Wednesday", self.doctor.available_days_list)

    def test_appointment_creation(self):
        appointment = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=self.today + timedelta(days=1),
            time_slot="09:00-09:30",
            reason="Consultation regarding persistent migraines",
            status=AppointmentStatusChoices.PENDING
        )
        self.assertEqual(appointment.status, AppointmentStatusChoices.PENDING)
        self.assertIn("Jane Doe", str(appointment))

    def test_past_date_validation(self):
        appointment = Appointment(
            patient=self.patient,
            doctor=self.doctor,
            date=self.today - timedelta(days=1),
            time_slot="09:00-09:30",
            reason="Past date check"
        )
        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_double_booking_prevention(self):
        booking_date = self.today + timedelta(days=3)
        Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=booking_date,
            time_slot="10:00-10:30",
            reason="Initial checkup",
            status=AppointmentStatusChoices.CONFIRMED
        )

        duplicate_app = Appointment(
            patient=self.patient,
            doctor=self.doctor,
            date=booking_date,
            time_slot="10:00-10:30",
            reason="Duplicate attempt"
        )
        with self.assertRaises(ValidationError):
            duplicate_app.full_clean()

    def test_rebooking_allowed_if_previous_was_cancelled(self):
        booking_date = self.today + timedelta(days=5)
        cancelled_app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=booking_date,
            time_slot="11:00-11:30",
            reason="Cancelled checkup",
            status=AppointmentStatusChoices.CANCELLED
        )

        new_app = Appointment(
            patient=self.patient,
            doctor=self.doctor,
            date=booking_date,
            time_slot="11:00-11:30",
            reason="New valid booking"
        )
        new_app.full_clean()
        new_app.save()
        self.assertEqual(new_app.status, AppointmentStatusChoices.PENDING)

    def test_medical_report_creation(self):
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=self.today + timedelta(days=1),
            time_slot="14:00-14:30",
            reason="Follow-up",
            status=AppointmentStatusChoices.COMPLETED
        )
        report = MedicalReport.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            appointment=app,
            diagnosis="Tension Headache",
            prescription="Rest and hydration",
            doctor_notes="Patient reported improvement."
        )
        self.assertEqual(report.appointment, app)
        self.assertIn("Jane Doe", str(report))


class HospitalPortalViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.today = timezone.localdate()

        # Doctors
        self.doc_cardio = Doctor.objects.create(
            name="Sarah Jenkins",
            department=DepartmentChoices.CARDIOLOGY,
            specialization="Interventional Cardiology",
            consultation_fee=120.00,
            active_status=True
        )
        self.doc_peds = Doctor.objects.create(
            name="David Brooks",
            department=DepartmentChoices.PEDIATRICS,
            specialization="Pediatrics",
            consultation_fee=85.00,
            active_status=True
        )

        # Users
        self.patient_user = User.objects.create_user(
            username="john_patient",
            password="Password123"
        )
        self.patient = Patient.objects.create(
            user=self.patient_user,
            name="John Doe",
            email="john@example.com",
            phone="+1-555-1122",
            gender="Male"
        )

        self.staff_user = User.objects.create_user(
            username="staff_user",
            password="Password123",
            is_staff=True
        )

    def test_home_view(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MediCare")
        self.assertContains(response, "Cardiology")

    def test_doctor_list_view_and_department_filtering(self):
        response = self.client.get(reverse('doctor_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dr. Sarah Jenkins")
        self.assertContains(response, "Dr. David Brooks")

        # Filter by department
        response_dept = self.client.get(reverse('doctor_list') + '?department=Cardiology')
        self.assertEqual(response_dept.status_code, 200)
        self.assertContains(response_dept, "Dr. Sarah Jenkins")
        self.assertNotContains(response_dept, "Dr. David Brooks")

    def test_doctor_detail_view(self):
        response = self.client.get(reverse('doctor_detail', kwargs={'pk': self.doc_cardio.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dr. Sarah Jenkins")
        self.assertContains(response, "$120.00")

    def test_api_get_slots(self):
        booking_date = (self.today + timedelta(days=2)).isoformat()
        # Create an existing booking
        Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=2),
            time_slot="09:00-09:30",
            reason="Checkup",
            status=AppointmentStatusChoices.CONFIRMED
        )

        url = f"{reverse('api_get_slots')}?doctor_id={self.doc_cardio.id}&date={booking_date}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("slots", data)

        # Slot 09:00-09:30 must be marked available: false
        slot_900 = next(s for s in data["slots"] if s["code"] == "09:00-09:30")
        self.assertFalse(slot_900["available"])
        self.assertTrue(slot_900["is_booked"])

        # Slot 09:30-10:00 must be marked available: true
        slot_930 = next(s for s in data["slots"] if s["code"] == "09:30-10:00")
        self.assertTrue(slot_930["available"])
        self.assertFalse(slot_930["is_booked"])

    def test_book_appointment_post_success(self):
        booking_date = self.today + timedelta(days=2)
        post_data = {
            'patient_name': 'New Patient',
            'patient_email': 'new.patient@example.com',
            'patient_phone': '+1-555-9876',
            'patient_gender': 'Female',
            'doctor': self.doc_cardio.id,
            'date': booking_date.isoformat(),
            'time_slot': '10:00-10:30',
            'reason': 'Chest pain evaluation'
        }
        response = self.client.post(reverse('book_appointment'), data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Appointment.objects.filter(reason='Chest pain evaluation').exists())

    def test_book_appointment_prevents_double_booking(self):
        booking_date = self.today + timedelta(days=2)
        # Create first booking
        Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=booking_date,
            time_slot='11:00-11:30',
            reason='First booking',
            status=AppointmentStatusChoices.CONFIRMED
        )

        # Attempt duplicate booking for same doctor, date, and slot
        post_data = {
            'patient_name': 'Another Patient',
            'patient_email': 'another@example.com',
            'patient_phone': '+1-555-0011',
            'patient_gender': 'Male',
            'doctor': self.doc_cardio.id,
            'date': booking_date.isoformat(),
            'time_slot': '11:00-11:30',
            'reason': 'Conflicting slot request'
        }
        response = self.client.post(reverse('book_appointment'), data=post_data)
        # Form error should re-render page with error message
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already has an appointment booked")

    def test_patient_dashboard_requires_login(self):
        # Unauthenticated access redirects to login
        response = self.client.get(reverse('patient_dashboard'))
        self.assertEqual(response.status_code, 302)

        # Authenticated access succeeds
        self.client.login(username="john_patient", password="Password123")
        response = self.client.get(reverse('patient_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "John Doe")

    def test_staff_dashboard_access_control(self):
        # Unauthenticated user cannot access staff dashboard and is redirected to login
        response_unauth = self.client.get(reverse('staff_dashboard'))
        self.assertEqual(response_unauth.status_code, 302)
        self.assertIn(reverse('patient_login'), response_unauth.url)

        # Patient user cannot access staff dashboard
        self.client.login(username="john_patient", password="Password123")
        response = self.client.get(reverse('staff_dashboard'))
        self.assertEqual(response.status_code, 302)

        # Staff user can access staff dashboard
        self.client.login(username="staff_user", password="Password123")
        response = self.client.get(reverse('staff_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hospital Operations")

    def test_staff_can_update_status(self):
        self.client.login(username="staff_user", password="Password123")
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=1),
            time_slot="14:00-14:30",
            reason="Staff status update test",
            status=AppointmentStatusChoices.PENDING
        )
        response = self.client.post(
            reverse('update_appointment_status', kwargs={'pk': app.pk}),
            data={'status': AppointmentStatusChoices.CONFIRMED}
        )
        self.assertEqual(response.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, AppointmentStatusChoices.CONFIRMED)

    def test_patient_registration_success(self):
        reg_data = {
            'username': 'mary_jane',
            'name': 'Mary Jane',
            'email': 'mary.jane@example.com',
            'phone': '+1-555-8833',
            'gender': 'Female',
            'date_of_birth': '1995-04-12',
            'blood_group': 'B+',
            'address': '789 Pine Rd, Metropolis',
            'password': 'StrongPassword123',
            'confirm_password': 'StrongPassword123',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('patient_dashboard'))

        # Verify User and Patient models were created and linked
        user = User.objects.get(username='mary_jane')
        self.assertTrue(user.check_password('StrongPassword123'))
        patient = Patient.objects.get(email='mary.jane@example.com')
        self.assertEqual(patient.user, user)
        self.assertEqual(patient.name, 'Mary Jane')
        self.assertEqual(patient.blood_group, 'B+')

    def test_patient_registration_duplicate_username_or_email(self):
        reg_data = {
            'username': 'john_patient',  # already exists from setUp
            'name': 'Duplicate John',
            'email': 'different.email@example.com',
            'phone': '+1-555-9999',
            'gender': 'Male',
            'password': 'Password123',
            'confirm_password': 'Password123',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Username already taken")

    def test_patient_login_and_logout(self):
        # Successful login
        response = self.client.post(reverse('patient_login'), data={
            'username': 'john_patient',
            'password': 'Password123'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('patient_dashboard'))

        # Logout via POST
        logout_resp = self.client.post(reverse('patient_logout'))
        self.assertEqual(logout_resp.status_code, 302)
        self.assertEqual(logout_resp.url, reverse('home'))

    def test_appointment_cancellation_by_owner_via_post(self):
        self.client.login(username="john_patient", password="Password123")
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=3),
            time_slot="10:00-10:30",
            reason="Routine checkup",
            status=AppointmentStatusChoices.PENDING
        )
        response = self.client.post(reverse('cancel_appointment', kwargs={'pk': app.pk}))
        self.assertEqual(response.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, AppointmentStatusChoices.CANCELLED)

    def test_appointment_cancellation_rejected_on_get(self):
        self.client.login(username="john_patient", password="Password123")
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=3),
            time_slot="10:30-11:00",
            reason="Checkup",
            status=AppointmentStatusChoices.CONFIRMED
        )
        # Attempting cancellation via GET request
        response = self.client.get(reverse('cancel_appointment', kwargs={'pk': app.pk}))
        self.assertEqual(response.status_code, 302)
        app.refresh_from_db()
        # Status must NOT have changed to Cancelled
        self.assertEqual(app.status, AppointmentStatusChoices.CONFIRMED)

    def test_patient_cannot_cancel_another_patients_appointment(self):
        # Create second patient user
        other_user = User.objects.create_user(username="other_patient", password="Password123")
        other_patient = Patient.objects.create(
            user=other_user,
            name="Other Patient",
            email="other@example.com",
            phone="+1-555-3344"
        )
        other_app = Appointment.objects.create(
            patient=other_patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=3),
            time_slot="11:30-12:00",
            reason="Private consultation",
            status=AppointmentStatusChoices.CONFIRMED
        )

        # First patient logs in and attempts to cancel other patient's appointment
        self.client.login(username="john_patient", password="Password123")
        response = self.client.post(reverse('cancel_appointment', kwargs={'pk': other_app.pk}))
        self.assertEqual(response.status_code, 302)
        other_app.refresh_from_db()
        # Status must remain Confirmed
        self.assertEqual(other_app.status, AppointmentStatusChoices.CONFIRMED)

    def test_patient_cannot_cancel_completed_appointment(self):
        self.client.login(username="john_patient", password="Password123")
        completed_app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today - timedelta(days=2),
            time_slot="09:00-09:30",
            reason="Past visit",
            status=AppointmentStatusChoices.COMPLETED
        )
        response = self.client.post(reverse('cancel_appointment', kwargs={'pk': completed_app.pk}))
        self.assertEqual(response.status_code, 302)
        completed_app.refresh_from_db()
        self.assertEqual(completed_app.status, AppointmentStatusChoices.COMPLETED)

    def test_medical_report_access_authorization(self):
        # Create other patient and medical report
        other_user = User.objects.create_user(username="alex_patient", password="Password123")
        other_patient = Patient.objects.create(
            user=other_user,
            name="Alex Green",
            email="alex@example.com",
            phone="+1-555-5566"
        )
        app = Appointment.objects.create(
            patient=other_patient,
            doctor=self.doc_cardio,
            date=self.today - timedelta(days=1),
            time_slot="09:30-10:00",
            status=AppointmentStatusChoices.COMPLETED,
            reason="Chest evaluation"
        )
        report = MedicalReport.objects.create(
            patient=other_patient,
            doctor=self.doc_cardio,
            appointment=app,
            diagnosis="Arrhythmia resolved",
            prescription="Aspirin 81mg"
        )

        # Unauthenticated user is redirected to login
        response = self.client.get(reverse('medical_report_detail', kwargs={'pk': report.pk}))
        self.assertEqual(response.status_code, 302)

        # John patient cannot view Alex's report
        self.client.login(username="john_patient", password="Password123")
        response = self.client.get(reverse('medical_report_detail', kwargs={'pk': report.pk}))
        self.assertEqual(response.status_code, 302)

        # Alex can view his own report
        self.client.login(username="alex_patient", password="Password123")
        response = self.client.get(reverse('medical_report_detail', kwargs={'pk': report.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Arrhythmia resolved")

        # Staff can view Alex's report
        self.client.login(username="staff_user", password="Password123")
        response = self.client.get(reverse('medical_report_detail', kwargs={'pk': report.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Arrhythmia resolved")

    def test_doctor_search_by_name_specialization_and_department(self):
        # Search by doctor name
        resp_name = self.client.get(reverse('doctor_list') + '?search=Sarah')
        self.assertEqual(resp_name.status_code, 200)
        self.assertContains(resp_name, "Dr. Sarah Jenkins")
        self.assertNotContains(resp_name, "Dr. David Brooks")

        # Search by specialization
        resp_spec = self.client.get(reverse('doctor_list') + '?search=Interventional')
        self.assertEqual(resp_spec.status_code, 200)
        self.assertContains(resp_spec, "Dr. Sarah Jenkins")
        self.assertNotContains(resp_spec, "Dr. David Brooks")

        # Search by department
        resp_dept = self.client.get(reverse('doctor_list') + '?search=Pediatrics')
        self.assertEqual(resp_dept.status_code, 200)
        self.assertContains(resp_dept, "Dr. David Brooks")
        self.assertNotContains(resp_dept, "Dr. Sarah Jenkins")

    def test_inactive_doctor_cannot_be_booked(self):
        inactive_doc = Doctor.objects.create(
            name="Gregory OnLeave",
            department=DepartmentChoices.NEUROLOGY,
            specialization="Neurology",
            consultation_fee=100.00,
            active_status=False
        )

        # Detail view shows inactive status
        resp_detail = self.client.get(reverse('doctor_detail', kwargs={'pk': inactive_doc.pk}))
        self.assertEqual(resp_detail.status_code, 200)
        self.assertContains(resp_detail, "Inactive")
        self.assertContains(resp_detail, "Booking Unavailable")

        # Booking POST attempt must be rejected by form validation
        booking_date = self.today + timedelta(days=2)
        post_data = {
            'patient_name': 'Test Patient',
            'patient_email': 'test@example.com',
            'patient_phone': '+1-555-0000',
            'doctor': inactive_doc.id,
            'date': booking_date.isoformat(),
            'time_slot': '09:00-09:30',
            'reason': 'Checkup attempt'
        }
        resp_book = self.client.post(reverse('book_appointment'), data=post_data)
        self.assertEqual(resp_book.status_code, 200)
        self.assertContains(resp_book, "Select a valid choice")

        # Model validation full_clean must also reject inactive doctor
        unclean_app = Appointment(
            patient=self.patient,
            doctor=inactive_doc,
            date=booking_date,
            time_slot='09:00-09:30',
            reason='Model clean check'
        )
        with self.assertRaises(ValidationError):
            unclean_app.full_clean()

    def test_authenticated_patient_quick_booking(self):
        self.client.login(username="john_patient", password="Password123")
        booking_date = self.today + timedelta(days=3)
        post_data = {
            'doctor': self.doc_cardio.id,
            'date': booking_date.isoformat(),
            'time_slot': '15:00-15:30',
            'reason': 'Quick appointment booking for logged in patient'
        }
        response = self.client.post(reverse('book_appointment'), data=post_data)
        self.assertEqual(response.status_code, 302)

        # Verify appointment was created and linked to John Doe's patient profile
        created_app = Appointment.objects.get(reason='Quick appointment booking for logged in patient')
        self.assertEqual(created_app.patient, self.patient)
        self.assertEqual(created_app.status, AppointmentStatusChoices.PENDING)

    def test_appointment_success_view_content(self):
        booking_date = self.today + timedelta(days=2)
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=booking_date,
            time_slot="10:00-10:30",
            reason="Heart checkup",
            status=AppointmentStatusChoices.PENDING
        )
        response = self.client.get(reverse('appointment_success', kwargs={'pk': app.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{app.id}")
        self.assertContains(response, "Dr. Sarah Jenkins")
        self.assertContains(response, "Cardiology")
        self.assertContains(response, "Pending")
        self.assertContains(response, "Heart checkup")
        self.assertContains(response, reverse('patient_dashboard'))

    def test_staff_can_cancel_appointment(self):
        self.client.login(username="staff_user", password="Password123")
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=2),
            time_slot="14:30-15:00",
            reason="Staff cancellation test",
            status=AppointmentStatusChoices.PENDING
        )
        response = self.client.post(
            reverse('update_appointment_status', kwargs={'pk': app.pk}),
            data={'status': AppointmentStatusChoices.CANCELLED}
        )
        self.assertEqual(response.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, AppointmentStatusChoices.CANCELLED)

    def test_staff_can_mark_confirmed_appointment_completed(self):
        self.client.login(username="staff_user", password="Password123")
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=2),
            time_slot="15:00-15:30",
            reason="Staff completion test",
            status=AppointmentStatusChoices.CONFIRMED
        )
        response = self.client.post(
            reverse('update_appointment_status', kwargs={'pk': app.pk}),
            data={'status': AppointmentStatusChoices.COMPLETED}
        )
        self.assertEqual(response.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, AppointmentStatusChoices.COMPLETED)

    def test_patient_cannot_change_appointment_status(self):
        self.client.login(username="john_patient", password="Password123")
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=2),
            time_slot="15:30-16:00",
            reason="Patient unauthorized status change test",
            status=AppointmentStatusChoices.PENDING
        )
        response = self.client.post(
            reverse('update_appointment_status', kwargs={'pk': app.pk}),
            data={'status': AppointmentStatusChoices.CONFIRMED}
        )
        self.assertEqual(response.status_code, 302)
        app.refresh_from_db()
        # Status must remain PENDING because non-staff cannot change status
        self.assertEqual(app.status, AppointmentStatusChoices.PENDING)

    def test_staff_can_create_medical_report(self):
        self.client.login(username="staff_user", password="Password123")
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=1),
            time_slot="16:00-16:30",
            reason="Cardiology consultation",
            status=AppointmentStatusChoices.CONFIRMED
        )
        post_data = {
            'diagnosis': 'Normal ECG. Mild hypertension observed.',
            'prescription': 'Lisinopril 10mg once daily',
            'doctor_notes': 'Reduce sodium intake. Follow up in 3 months.'
        }
        response = self.client.post(
            reverse('add_medical_report', kwargs={'appointment_id': app.id}),
            data=post_data
        )
        self.assertEqual(response.status_code, 302)

        # Verify report was created and linked
        report = MedicalReport.objects.get(appointment=app)
        self.assertEqual(report.patient, self.patient)
        self.assertEqual(report.doctor, self.doc_cardio)
        self.assertIn('Lisinopril', report.prescription)
        self.assertEqual(response.url, reverse('medical_report_detail', kwargs={'pk': report.pk}))

        # Verify appointment status was automatically updated to COMPLETED
        app.refresh_from_db()
        self.assertEqual(app.status, AppointmentStatusChoices.COMPLETED)

    def test_duplicate_medical_report_prevented(self):
        self.client.login(username="staff_user", password="Password123")
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=1),
            time_slot="16:30-17:00",
            reason="Consultation with existing report",
            status=AppointmentStatusChoices.COMPLETED
        )
        initial_report = MedicalReport.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            appointment=app,
            diagnosis="Initial diagnosis",
            prescription="Initial meds"
        )

        # Attempt to create duplicate report via POST
        response = self.client.post(
            reverse('add_medical_report', kwargs={'appointment_id': app.id}),
            data={'diagnosis': 'Duplicate diagnosis', 'prescription': 'Duplicate meds'}
        )
        # Should redirect to existing report detail
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('medical_report_detail', kwargs={'pk': initial_report.pk}))

        # Ensure only 1 report exists for this appointment
        self.assertEqual(MedicalReport.objects.filter(appointment=app).count(), 1)

    def test_staff_dashboard_displays_all_five_kpis(self):
        self.client.login(username="staff_user", password="Password123")
        response = self.client.get(reverse('staff_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('total_count', response.context)
        self.assertIn('pending_count', response.context)
        self.assertIn('confirmed_count', response.context)
        self.assertIn('completed_count', response.context)
        self.assertIn('cancelled_count', response.context)

    def test_setup_staff_missing_username(self):
        """When STAFF_USERNAME is absent, command exits safely without changes."""
        old_env = os.environ.get('STAFF_USERNAME')
        if 'STAFF_USERNAME' in os.environ:
            del os.environ['STAFF_USERNAME']

        out = io.StringIO()
        call_command('setup_staff', stdout=out)
        self.assertIn("STAFF_USERNAME environment variable is not set", out.getvalue())

        if old_env is not None:
            os.environ['STAFF_USERNAME'] = old_env

    def test_setup_staff_unknown_username(self):
        """When STAFF_USERNAME refers to a nonexistent user, exits safely with warning."""
        os.environ['STAFF_USERNAME'] = "completely_nonexistent_user_99"
        out = io.StringIO()
        call_command('setup_staff', stdout=out)
        self.assertIn("was not found in the database", out.getvalue())

        del os.environ['STAFF_USERNAME']

    def test_setup_staff_promotes_existing_user(self):
        """Promotes an existing non-staff user to is_staff=True, is_superuser=False."""
        test_patient_user = User.objects.create_user(
            username="promote_me_user",
            password="OriginalPassword123!",
            email="promote@example.com"
        )
        self.assertFalse(test_patient_user.is_staff)
        self.assertFalse(test_patient_user.is_superuser)

        os.environ['STAFF_USERNAME'] = "promote_me_user"
        out = io.StringIO()
        call_command('setup_staff', stdout=out)
        self.assertIn("Successfully promoted user 'promote_me_user' to hospital staff", out.getvalue())

        test_patient_user.refresh_from_db()
        self.assertTrue(test_patient_user.is_staff)
        self.assertFalse(test_patient_user.is_superuser)
        # Verify password was preserved
        self.assertTrue(test_patient_user.check_password("OriginalPassword123!"))

        del os.environ['STAFF_USERNAME']

    def test_activate_staff_disabled_when_env_key_missing(self):
        """When STAFF_ACTIVATION_KEY is not set in environment, endpoint returns 404."""
        old_key = os.environ.get('STAFF_ACTIVATION_KEY')
        if 'STAFF_ACTIVATION_KEY' in os.environ:
            del os.environ['STAFF_ACTIVATION_KEY']

        self.client.login(username="john_patient", password="Password123")
        # GET request returns 404
        resp_get = self.client.get(reverse('activate_staff'))
        self.assertEqual(resp_get.status_code, 404)

        # POST request returns 404
        resp_post = self.client.post(reverse('activate_staff'), {
            'username': 'john_patient',
            'activation_key': 'any_key'
        })
        self.assertEqual(resp_post.status_code, 404)

        if old_key is not None:
            os.environ['STAFF_ACTIVATION_KEY'] = old_key

    def test_activate_staff_requires_login(self):
        """Unauthenticated requests are redirected to login."""
        os.environ['STAFF_ACTIVATION_KEY'] = 'SuperSecretKey999!'
        resp = self.client.get(reverse('activate_staff'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('patient_login'), resp.url)
        del os.environ['STAFF_ACTIVATION_KEY']

    def test_activate_staff_rejects_wrong_secret(self):
        """Rejects submission when activation key does not match."""
        os.environ['STAFF_ACTIVATION_KEY'] = 'CorrectKey123!'
        self.client.login(username="john_patient", password="Password123")

        resp = self.client.post(reverse('activate_staff'), {
            'username': 'john_patient',
            'activation_key': 'WrongKey456!'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid activation secret key")

        self.patient_user.refresh_from_db()
        self.assertFalse(self.patient_user.is_staff)
        del os.environ['STAFF_ACTIVATION_KEY']

    def test_activate_staff_rejects_mismatched_username(self):
        """Rejects attempt to activate a username other than the authenticated user."""
        os.environ['STAFF_ACTIVATION_KEY'] = 'CorrectKey123!'
        self.client.login(username="john_patient", password="Password123")

        resp = self.client.post(reverse('activate_staff'), {
            'username': 'other_random_user',
            'activation_key': 'CorrectKey123!'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Permission denied")

        self.patient_user.refresh_from_db()
        self.assertFalse(self.patient_user.is_staff)
        del os.environ['STAFF_ACTIVATION_KEY']

    def test_activate_staff_success(self):
        """Successful activation sets is_staff=True, is_superuser=False, and preserves password."""
        os.environ['STAFF_ACTIVATION_KEY'] = 'UniqueActivationKey2026!'
        self.client.login(username="john_patient", password="Password123")

        resp = self.client.post(reverse('activate_staff'), {
            'username': 'john_patient',
            'activation_key': 'UniqueActivationKey2026!'
        })
        # Redirects directly to staff dashboard
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('staff_dashboard'))

        self.patient_user.refresh_from_db()
        self.assertTrue(self.patient_user.is_staff)
        self.assertFalse(self.patient_user.is_superuser)
        self.assertTrue(self.patient_user.check_password("Password123"))
        del os.environ['STAFF_ACTIVATION_KEY']

    def test_login_get_displays_form_for_unauthenticated_visitor(self):
        """Unauthenticated GET request to /login/ displays the login form."""
        response = self.client.get(reverse('patient_login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'appointments/login.html')
        self.assertContains(response, 'Sign In')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertNotContains(response, 'Signed in as')

    def test_login_get_displays_form_for_authenticated_visitor(self):
        """Authenticated GET request to /login/ displays the login form and active session banner."""
        self.client.login(username="john_patient", password="Password123")
        response = self.client.get(reverse('patient_login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'appointments/login.html')
        self.assertContains(response, 'Signed in as')
        self.assertContains(response, 'john_patient')
        self.assertContains(response, 'name="username"')

    def test_login_invalid_credentials_does_not_redirect(self):
        """Invalid credentials submission remains on login page and shows error message."""
        response = self.client.post(reverse('patient_login'), {
            'username': 'john_patient',
            'password': 'WrongPassword123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'appointments/login.html')
        self.assertContains(response, "Invalid username or password. Please try again.")

    def test_login_valid_patient_redirects_to_patient_dashboard(self):
        """Valid patient login authenticates and redirects to patient dashboard."""
        response = self.client.post(reverse('patient_login'), {
            'username': 'john_patient',
            'password': 'Password123'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('patient_dashboard'))

    def test_login_valid_staff_redirects_to_staff_dashboard(self):
        """Valid staff login authenticates and redirects to staff dashboard."""
        response = self.client.post(reverse('patient_login'), {
            'username': 'staff_user',
            'password': 'Password123'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('staff_dashboard'))

    def test_login_redirects_to_safe_next_url(self):
        """Login honors safe 'next' query parameter."""
        response = self.client.post(reverse('patient_login') + f"?next={reverse('book_appointment')}", {
            'username': 'john_patient',
            'password': 'Password123'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('book_appointment'))






