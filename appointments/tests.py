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
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!',
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
        self.client.login(username="john_patient", password="Password123")
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

    def test_activate_staff_endpoint_permanently_returns_404_unauthenticated(self):
        """Unauthenticated GET and POST requests to /activate-staff/ return 404."""
        resp_get = self.client.get(reverse('activate_staff'))
        self.assertEqual(resp_get.status_code, 404)

        resp_post = self.client.post(reverse('activate_staff'), {
            'username': 'john_patient',
            'activation_key': 'any_secret_attempt'
        })
        self.assertEqual(resp_post.status_code, 404)

    def test_activate_staff_endpoint_permanently_returns_404_authenticated(self):
        """Authenticated patient GET and POST requests to /activate-staff/ return 404 and cannot promote user."""
        self.client.login(username="john_patient", password="Password123")
        resp_get = self.client.get(reverse('activate_staff'))
        self.assertEqual(resp_get.status_code, 404)

        resp_post = self.client.post(reverse('activate_staff'), {
            'username': 'john_patient',
            'activation_key': 'any_secret_attempt'
        })
        self.assertEqual(resp_post.status_code, 404)

        self.patient_user.refresh_from_db()
        self.assertFalse(self.patient_user.is_staff)
        self.assertFalse(self.patient_user.is_superuser)

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

    def test_end_to_end_registration_and_login_success(self):
        """Register through the real registration endpoint and log in through the real login endpoint."""
        reg_data = {
            'username': 'mary_jane',
            'name': 'Mary Jane Watson',
            'email': 'mary.jane@example.com',
            'phone': '+1-555-7788',
            'gender': 'Female',
            'password': 'ComplexPassword123!',
            'confirm_password': 'ComplexPassword123!',
        }
        reg_resp = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(reg_resp.status_code, 302)
        self.assertEqual(reg_resp.url, reverse('patient_dashboard'))

        # Log out
        self.client.post(reverse('patient_logout'))

        # Log in with exact credentials
        login_resp = self.client.post(reverse('patient_login'), data={
            'username': 'mary_jane',
            'password': 'ComplexPassword123!'
        })
        self.assertEqual(login_resp.status_code, 302)
        self.assertEqual(login_resp.url, reverse('patient_dashboard'))

    def test_end_to_end_registration_and_login_invalid_password(self):
        """Register through real registration endpoint and verify wrong password fails at login."""
        reg_data = {
            'username': 'david_test',
            'name': 'David Tester',
            'email': 'david.tester@example.com',
            'phone': '+1-555-9900',
            'gender': 'Male',
            'password': 'CorrectPassword123!',
            'confirm_password': 'CorrectPassword123!',
        }
        reg_resp = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(reg_resp.status_code, 302)

        # Log out
        self.client.post(reverse('patient_logout'))

        # Attempt login with incorrect password
        bad_login_resp = self.client.post(reverse('patient_login'), data={
            'username': 'david_test',
            'password': 'WrongPassword999!'
        })
        self.assertEqual(bad_login_resp.status_code, 200)
        self.assertContains(bad_login_resp, "Invalid username or password. Please try again.")

    def test_login_supports_case_insensitive_username(self):
        """User registered with mixed case can log in using lowercase or uppercase username."""
        reg_data = {
            'username': 'CaseMixedUser',
            'name': 'Case Tester',
            'email': 'case.tester@example.com',
            'phone': '+1-555-1199',
            'gender': 'Male',
            'password': 'Password12345!',
            'confirm_password': 'Password12345!',
        }
        self.client.post(reverse('patient_register'), data=reg_data)
        self.client.post(reverse('patient_logout'))

        # Login with lowercase
        resp_lower = self.client.post(reverse('patient_login'), data={
            'username': 'casemixeduser',
            'password': 'Password12345!'
        })
        self.assertEqual(resp_lower.status_code, 302)
        self.assertEqual(resp_lower.url, reverse('patient_dashboard'))

    def test_login_supports_email_as_identifier(self):
        """User can log in using their registered email address instead of username."""
        reg_data = {
            'username': 'email_login_patient',
            'name': 'Email Tester',
            'email': 'patient.email@example.com',
            'phone': '+1-555-2288',
            'gender': 'Female',
            'password': 'Password12345!',
            'confirm_password': 'Password12345!',
        }
        self.client.post(reverse('patient_register'), data=reg_data)
        self.client.post(reverse('patient_logout'))

        # Login using email (including mixed-case email)
        resp_email = self.client.post(reverse('patient_login'), data={
            'username': 'PATIENT.EMAIL@EXAMPLE.COM',
            'password': 'Password12345!'
        })
        self.assertEqual(resp_email.status_code, 302)
        self.assertEqual(resp_email.url, reverse('patient_dashboard'))

    def test_login_supports_whitespace_trimmed_identifier(self):
        """Leading and trailing spaces in username/email are cleanly ignored."""
        reg_data = {
            'username': 'trimmed_patient',
            'name': 'Trim Tester',
            'email': 'trimmed@example.com',
            'phone': '+1-555-3399',
            'gender': 'Male',
            'password': 'Password12345!',
            'confirm_password': 'Password12345!',
        }
        self.client.post(reverse('patient_register'), data=reg_data)
        self.client.post(reverse('patient_logout'))

        # Login with untrimmed whitespace
        resp_trimmed = self.client.post(reverse('patient_login'), data={
            'username': '   trimmed_patient   ',
            'password': 'Password12345!'
        })
        self.assertEqual(resp_trimmed.status_code, 302)
        self.assertEqual(resp_trimmed.url, reverse('patient_dashboard'))

    def test_csrf_protection_rejects_post_without_token(self):
        """CSRF protection is strictly enabled and rejects POST requests lacking a CSRF token."""
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(reverse('patient_login'), data={
            'username': 'john_patient',
            'password': 'Password123'
        })
        self.assertEqual(resp.status_code, 403)

    def test_production_https_login_with_csrf_succeeds(self):
        """Production-style HTTPS request with valid CSRF token and proxy headers succeeds without 403."""
        csrf_client = Client(enforce_csrf_checks=True)
        # GET request fetches the page and receives CSRF cookie
        get_resp = csrf_client.get(
            reverse('patient_login'),
            secure=True,
            HTTP_HOST='hospital-appointment-portal-25sx.onrender.com',
            HTTP_X_FORWARDED_PROTO='https'
        )
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn('csrftoken', csrf_client.cookies)
        csrf_token = csrf_client.cookies['csrftoken'].value

        # POST with CSRF token, Origin, and Referer matching production Render setup
        post_resp = csrf_client.post(
            reverse('patient_login'),
            data={
                'csrfmiddlewaretoken': csrf_token,
                'username': 'john_patient',
                'password': 'Password123'
            },
            secure=True,
            HTTP_HOST='hospital-appointment-portal-25sx.onrender.com',
            HTTP_ORIGIN='https://hospital-appointment-portal-25sx.onrender.com',
            HTTP_REFERER='https://hospital-appointment-portal-25sx.onrender.com/login/',
            HTTP_X_FORWARDED_PROTO='https'
        )
        self.assertEqual(post_resp.status_code, 302)
        self.assertEqual(post_resp.url, reverse('patient_dashboard'))

    def test_production_https_registration_with_csrf_succeeds(self):
        """Production-style HTTPS registration with CSRF token succeeds without 403."""
        csrf_client = Client(enforce_csrf_checks=True)
        get_resp = csrf_client.get(
            reverse('patient_register'),
            secure=True,
            HTTP_HOST='hospital-appointment-portal-25sx.onrender.com',
            HTTP_X_FORWARDED_PROTO='https'
        )
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn('csrftoken', csrf_client.cookies)
        csrf_token = csrf_client.cookies['csrftoken'].value

        reg_data = {
            'csrfmiddlewaretoken': csrf_token,
            'username': 'csrf_patient_user',
            'name': 'CSRF Patient',
            'email': 'csrf.patient@example.com',
            'phone': '+1-555-4477',
            'gender': 'Female',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
        }
        post_resp = csrf_client.post(
            reverse('patient_register'),
            data=reg_data,
            secure=True,
            HTTP_HOST='hospital-appointment-portal-25sx.onrender.com',
            HTTP_ORIGIN='https://hospital-appointment-portal-25sx.onrender.com',
            HTTP_REFERER='https://hospital-appointment-portal-25sx.onrender.com/register/',
            HTTP_X_FORWARDED_PROTO='https'
        )
        self.assertEqual(post_resp.status_code, 302)
        self.assertEqual(post_resp.url, reverse('patient_dashboard'))

    def test_production_https_logout_with_csrf_succeeds(self):
        """Production-style HTTPS logout via POST with CSRF token succeeds without 403."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username="john_patient", password="Password123")
        get_resp = csrf_client.get(
            reverse('home'),
            secure=True,
            HTTP_HOST='hospital-appointment-portal-25sx.onrender.com',
            HTTP_X_FORWARDED_PROTO='https'
        )
        csrf_token = csrf_client.cookies['csrftoken'].value

        post_resp = csrf_client.post(
            reverse('patient_logout'),
            data={'csrfmiddlewaretoken': csrf_token},
            secure=True,
            HTTP_HOST='hospital-appointment-portal-25sx.onrender.com',
            HTTP_ORIGIN='https://hospital-appointment-portal-25sx.onrender.com',
            HTTP_REFERER='https://hospital-appointment-portal-25sx.onrender.com/',
            HTTP_X_FORWARDED_PROTO='https'
        )
        self.assertEqual(post_resp.status_code, 302)
        self.assertEqual(post_resp.url, reverse('home'))

    def test_navbar_staff_login_option_for_unauthenticated_user(self):
        """Navbar displays a clearly visible Staff Login link pointing to /login/ for unauthenticated visitors."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Staff Login')
        self.assertContains(response, f'href="{reverse("patient_login")}"')

    def test_navbar_hides_staff_login_for_authenticated_users(self):
        """Navbar hides Staff Login when a user (patient or staff) is logged in."""
        # Patient logged in
        self.client.login(username="john_patient", password="Password123")
        resp_patient = self.client.get(reverse('home'))
        self.assertEqual(resp_patient.status_code, 200)
        self.assertNotContains(resp_patient, 'Staff Login')
        self.assertContains(resp_patient, 'My Dashboard')

        # Staff logged in
        self.client.login(username="staff_user", password="Password123")
        resp_staff = self.client.get(reverse('home'))
        self.assertEqual(resp_staff.status_code, 200)
        self.assertNotContains(resp_staff, 'Staff Login')
        self.assertContains(resp_staff, 'Staff Portal')

    def test_dedicated_staff_account_role_and_dashboard_access(self):
        """Dedicated staff user (is_staff=True, is_superuser=False) logs in and accesses staff dashboard while patient cannot."""
        dedicated_staff = User.objects.create_user(
            username="dedicated_demo_staff",
            password="DemoStaffPassword123!",
            email="demo.staff@hospitalportal.org",
            is_staff=True
        )
        self.assertFalse(dedicated_staff.is_superuser)
        self.assertTrue(dedicated_staff.is_staff)

        # 1. Logging in via /login/ redirects to staff_dashboard
        login_resp = self.client.post(reverse('patient_login'), {
            'username': 'dedicated_demo_staff',
            'password': 'DemoStaffPassword123!'
        })
        self.assertEqual(login_resp.status_code, 302)
        self.assertEqual(login_resp.url, reverse('staff_dashboard'))

        # 2. Can access /staff/dashboard/ and view operations
        dash_resp = self.client.get(reverse('staff_dashboard'))
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, "Hospital Operations")

        # 3. Patient login continues to redirect to /dashboard/
        self.client.logout()
        patient_resp = self.client.post(reverse('patient_login'), {
            'username': 'john_patient',
            'password': 'Password123'
        })
        self.assertEqual(patient_resp.status_code, 302)
        self.assertEqual(patient_resp.url, reverse('patient_dashboard'))

        # 4. Patient is blocked from /staff/dashboard/
        blocked_resp = self.client.get(reverse('staff_dashboard'))
        self.assertEqual(blocked_resp.status_code, 302)
        self.assertEqual(blocked_resp.url, reverse('patient_dashboard'))

    def test_appointment_success_anonymous_without_session_is_rejected(self):
        """Anonymous user without a verified booking session cannot view appointment receipt (IDOR protection)."""
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=2),
            time_slot="10:00-10:30",
            reason="Cardio consultation",
            status=AppointmentStatusChoices.PENDING
        )
        response = self.client.get(reverse('appointment_success', kwargs={'pk': app.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))

    def test_appointment_success_verified_booking_session_succeeds(self):
        """Anonymous user who legitimately booked through the form can view their confirmation receipt."""
        booking_data = {
            'doctor': self.doc_cardio.id,
            'date': (self.today + timedelta(days=5)).isoformat(),
            'time_slot': '14:00-14:30',
            'reason': 'Guest booking receipt access test',
            'patient_name': 'Guest Patient',
            'patient_email': 'guest.patient@example.com',
            'patient_phone': '+1-555-8833',
            'patient_gender': 'Other'
        }
        post_resp = self.client.post(reverse('book_appointment'), data=booking_data)
        self.assertEqual(post_resp.status_code, 302)

        # Access the confirmation receipt using the legitimate booking session
        receipt_resp = self.client.get(post_resp.url)
        self.assertEqual(receipt_resp.status_code, 200)
        self.assertContains(receipt_resp, "Appointment Successfully Booked!")
        self.assertContains(receipt_resp, "Guest booking receipt access test")

    def test_appointment_success_session_cannot_access_other_appointments(self):
        """Session authorized for appointment A cannot view appointment B (session boundary enforced)."""
        app_other = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=3),
            time_slot="11:00-11:30",
            reason="Private consultation",
            status=AppointmentStatusChoices.PENDING
        )
        # Establish session with a different appointment ID
        session = self.client.session
        session['confirmed_booking_ids'] = [999999]
        session.save()

        response = self.client.get(reverse('appointment_success', kwargs={'pk': app_other.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))

    def test_appointment_success_unrelated_authenticated_patient_is_rejected(self):
        """Authenticated patient cannot view another patient's booking confirmation receipt."""
        User.objects.create_user(
            username="unrelated_patient",
            password="Password123",
            email="unrelated@example.com"
        )
        app_john = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=2),
            time_slot="10:00-10:30",
            reason="John's private checkup",
            status=AppointmentStatusChoices.PENDING
        )
        # Log in as unrelated patient
        login_success = self.client.login(username="unrelated_patient", password="Password123")
        self.assertTrue(login_success)
        response = self.client.get(reverse('appointment_success', kwargs={'pk': app_john.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('patient_dashboard'))

    def test_appointment_success_staff_access_succeeds(self):
        """Hospital staff can access any appointment confirmation receipt."""
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc_cardio,
            date=self.today + timedelta(days=2),
            time_slot="10:00-10:30",
            reason="Staff oversight test",
            status=AppointmentStatusChoices.PENDING
        )
        self.client.login(username="staff_user", password="Password123")
        response = self.client.get(reverse('appointment_success', kwargs={'pk': app.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff oversight test")

    def test_logout_get_request_does_not_log_out_user(self):
        """GET request to logout does not terminate session; POST is required."""
        self.client.login(username="john_patient", password="Password123")

        # GET request to logout
        get_resp = self.client.get(reverse('patient_logout'))
        self.assertEqual(get_resp.status_code, 302)
        self.assertEqual(get_resp.url, reverse('home'))

        # User is still authenticated and can access their dashboard
        dash_resp = self.client.get(reverse('patient_dashboard'))
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, "Welcome, John Doe")

        # POST request legitimately logs the user out
        post_resp = self.client.post(reverse('patient_logout'))
        self.assertEqual(post_resp.status_code, 302)
        self.assertEqual(post_resp.url, reverse('home'))

        # User is now logged out; accessing dashboard redirects to login
        dash_after_logout = self.client.get(reverse('patient_dashboard'))
        self.assertEqual(dash_after_logout.status_code, 302)
        self.assertIn(reverse('patient_login'), dash_after_logout.url)


class HospitalPortalRoleAndDataSeparationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.today = timezone.localdate()

        self.doctor = Doctor.objects.create(
            name="Alice Hamilton",
            department=DepartmentChoices.CARDIOLOGY,
            specialization="Cardiovascular Health",
            consultation_fee=100.00,
            active_status=True
        )

        self.patient_user = User.objects.create_user(
            username="test_patient_user",
            password="PatientPassword123!",
            email="patient.user@hospitalportal.org"
        )
        self.patient = Patient.objects.create(
            user=self.patient_user,
            name="Test Patient",
            email="patient.user@hospitalportal.org",
            phone="+1-555-7711",
            gender="Female"
        )

        self.staff_user = User.objects.create_user(
            username="hospital_staff_user",
            password="StaffPassword123!",
            email="staff.user@hospitalportal.org",
            is_staff=True,
            is_superuser=False
        )

        self.superuser = User.objects.create_superuser(
            username="hospital_super_admin",
            password="AdminPassword123!",
            email="admin@hospitalportal.org"
        )

    def test_staff_accessing_patient_dashboard_redirects_to_staff_dashboard_without_creating_patient(self):
        """Staff visiting /dashboard/ must redirect to /staff/dashboard/ without creating a Patient record."""
        self.assertFalse(hasattr(self.staff_user, 'patient_profile'))
        patient_count_before = Patient.objects.count()

        self.client.login(username="hospital_staff_user", password="StaffPassword123!")
        response = self.client.get(reverse('patient_dashboard'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('staff_dashboard'))
        self.assertEqual(Patient.objects.count(), patient_count_before)
        self.assertFalse(Patient.objects.filter(user=self.staff_user).exists())

    def test_superuser_accessing_patient_dashboard_redirects_to_staff_dashboard_without_creating_patient(self):
        """Superuser visiting /dashboard/ must redirect to /staff/dashboard/ without creating a Patient record."""
        patient_count_before = Patient.objects.count()

        self.client.login(username="hospital_super_admin", password="AdminPassword123!")
        response = self.client.get(reverse('patient_dashboard'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('staff_dashboard'))
        self.assertEqual(Patient.objects.count(), patient_count_before)
        self.assertFalse(Patient.objects.filter(user=self.superuser).exists())

    def test_patient_can_access_own_dashboard(self):
        """Authenticated patient successfully accesses their patient dashboard."""
        self.client.login(username="test_patient_user", password="PatientPassword123!")
        response = self.client.get(reverse('patient_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'appointments/patient_dashboard.html')
        self.assertContains(response, "Test Patient")
        self.assertEqual(response.context['patient'], self.patient)

    def test_staff_login_with_next_dashboard_redirects_to_staff_dashboard(self):
        """Staff login with ?next=/dashboard/ routes to /staff/dashboard/ instead of /dashboard/."""
        response = self.client.post(reverse('patient_login') + f"?next={reverse('patient_dashboard')}", {
            'username': 'hospital_staff_user',
            'password': 'StaffPassword123!'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('staff_dashboard'))

    def test_staff_booking_appointment_does_not_attach_staff_as_patient_user(self):
        """When staff books an appointment, the Patient record created is unattached to the staff user."""
        self.client.login(username="hospital_staff_user", password="StaffPassword123!")
        booking_data = {
            'doctor': self.doctor.id,
            'date': (self.today + timedelta(days=4)).isoformat(),
            'time_slot': '10:00-10:30',
            'reason': 'Walk-in booking entered by staff',
            'patient_name': 'Walk-in Patient',
            'patient_email': 'walkin.patient@example.com',
            'patient_phone': '+1-555-9922',
            'patient_gender': 'Other'
        }
        response = self.client.post(reverse('book_appointment'), data=booking_data)
        self.assertEqual(response.status_code, 302)

        walkin = Patient.objects.get(email='walkin.patient@example.com')
        self.assertIsNone(walkin.user)
        self.assertFalse(Patient.objects.filter(user=self.staff_user).exists())

    def test_medical_report_detail_role_separation(self):
        """Medical report is accessible by the patient owner and staff, but forbidden for unrelated patients."""
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=self.today + timedelta(days=2),
            time_slot="11:00-11:30",
            reason="Confidential cardiology exam",
            status=AppointmentStatusChoices.COMPLETED
        )
        report = MedicalReport.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            appointment=app,
            diagnosis="Sinus Bradycardia",
            prescription="Follow up resting ECG",
            doctor_notes="Private notes"
        )

        unrelated_user = User.objects.create_user(
            username="unrelated_user",
            password="UnrelatedPassword123!",
            email="unrelated.user@example.com"
        )
        unrelated_patient = Patient.objects.create(
            user=unrelated_user,
            name="Unrelated Patient",
            email="unrelated.user@example.com",
            phone="+1-555-0044"
        )

        # 1. Patient owner accesses report -> 200
        self.client.login(username="test_patient_user", password="PatientPassword123!")
        owner_resp = self.client.get(reverse('medical_report_detail', kwargs={'pk': report.pk}))
        self.assertEqual(owner_resp.status_code, 200)
        self.assertContains(owner_resp, "Sinus Bradycardia")

        # 2. Staff user accesses report -> 200
        self.client.login(username="hospital_staff_user", password="StaffPassword123!")
        staff_resp = self.client.get(reverse('medical_report_detail', kwargs={'pk': report.pk}))
        self.assertEqual(staff_resp.status_code, 200)
        self.assertContains(staff_resp, "Sinus Bradycardia")

        # 3. Unrelated patient tries to access report -> 302 to patient_dashboard
        self.client.login(username="unrelated_user", password="UnrelatedPassword123!")
        unrelated_resp = self.client.get(reverse('medical_report_detail', kwargs={'pk': report.pk}))
        self.assertEqual(unrelated_resp.status_code, 302)
        self.assertEqual(unrelated_resp.url, reverse('patient_dashboard'))

    def test_cancel_appointment_role_separation(self):
        """Unrelated patients cannot cancel another patient's appointment, while staff can."""
        app = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=self.today + timedelta(days=3),
            time_slot="14:00-14:30",
            reason="Cardiology review",
            status=AppointmentStatusChoices.CONFIRMED
        )

        unrelated_user = User.objects.create_user(
            username="other_patient_user",
            password="OtherPassword123!",
            email="other.patient@example.com"
        )
        Patient.objects.create(
            user=unrelated_user,
            name="Other Patient",
            email="other.patient@example.com",
            phone="+1-555-8855"
        )

        # Unrelated patient attempts to cancel
        self.client.login(username="other_patient_user", password="OtherPassword123!")
        cancel_resp = self.client.post(reverse('cancel_appointment', kwargs={'pk': app.pk}))
        self.assertEqual(cancel_resp.status_code, 302)
        self.assertEqual(cancel_resp.url, reverse('patient_dashboard'))

        app.refresh_from_db()
        self.assertEqual(app.status, AppointmentStatusChoices.CONFIRMED)

        # Staff cancels appointment
        self.client.login(username="hospital_staff_user", password="StaffPassword123!")
        staff_cancel_resp = self.client.post(reverse('cancel_appointment', kwargs={'pk': app.pk}))
        self.assertEqual(staff_cancel_resp.status_code, 302)
        self.assertEqual(staff_cancel_resp.url, reverse('staff_dashboard'))

        app.refresh_from_db()
        self.assertEqual(app.status, AppointmentStatusChoices.CANCELLED)

    def test_patient_register_view_redirects_authenticated_staff_to_staff_dashboard(self):
        """Authenticated staff navigating to /register/ is redirected to /staff/dashboard/."""
        self.client.login(username="hospital_staff_user", password="StaffPassword123!")
        response = self.client.get(reverse('patient_register'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('staff_dashboard'))


class HospitalPortalSecurityAndAuthenticationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.today = timezone.localdate()

        self.doctor = Doctor.objects.create(
            name="Gregory House",
            department=DepartmentChoices.NEUROLOGY,
            specialization="Diagnostic Medicine",
            consultation_fee=150.00,
            active_status=True
        )

        self.existing_patient_user = User.objects.create_user(
            username="existing_patient",
            password="SecurePassword2026!#$",
            email="existing.patient@example.com"
        )
        self.existing_patient = Patient.objects.create(
            user=self.existing_patient_user,
            name="Existing Patient",
            email="existing.patient@example.com",
            phone="+1-555-1010",
            gender="Female"
        )

    def test_registration_weak_password_rejected_too_short(self):
        """Registration with short password (< 8 chars) fails Django's MinimumLengthValidator."""
        reg_data = {
            'username': 'new_user_1',
            'name': 'New User One',
            'email': 'new.user1@example.com',
            'phone': '+1-555-0101',
            'gender': 'Male',
            'password': 'short',
            'confirm_password': 'short',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This password is too short")
        self.assertFalse(User.objects.filter(username='new_user_1').exists())

    def test_registration_weak_password_rejected_too_common(self):
        """Registration with common password fails Django's CommonPasswordValidator."""
        reg_data = {
            'username': 'new_user_2',
            'name': 'New User Two',
            'email': 'new.user2@example.com',
            'phone': '+1-555-0102',
            'gender': 'Female',
            'password': 'password123',
            'confirm_password': 'password123',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This password is too common")
        self.assertFalse(User.objects.filter(username='new_user_2').exists())

    def test_registration_weak_password_rejected_entirely_numeric(self):
        """Registration with numeric password fails Django's NumericPasswordValidator."""
        reg_data = {
            'username': 'new_user_3',
            'name': 'New User Three',
            'email': 'new.user3@example.com',
            'phone': '+1-555-0103',
            'gender': 'Other',
            'password': '123456789012',
            'confirm_password': '123456789012',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This password is entirely numeric")
        self.assertFalse(User.objects.filter(username='new_user_3').exists())

    def test_registration_weak_password_rejected_similar_to_username(self):
        """Registration with password similar to username fails UserAttributeSimilarityValidator."""
        reg_data = {
            'username': 'richard_feynman',
            'name': 'Richard Feynman',
            'email': 'richard.feynman@example.com',
            'phone': '+1-555-0104',
            'gender': 'Male',
            'password': 'richard_feynman2026',
            'confirm_password': 'richard_feynman2026',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The password is too similar to the username")
        self.assertFalse(User.objects.filter(username='richard_feynman').exists())

    def test_registration_passwords_mismatch(self):
        """Registration with mismatched passwords fails validation."""
        reg_data = {
            'username': 'mismatch_user',
            'name': 'Mismatch User',
            'email': 'mismatch@example.com',
            'phone': '+1-555-0105',
            'gender': 'Male',
            'password': 'ValidPassword2026!#',
            'confirm_password': 'DifferentPassword2026!#',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match")
        self.assertFalse(User.objects.filter(username='mismatch_user').exists())

    def test_registration_valid_password_succeeds(self):
        """Registration with valid, strong password creates user with hashed password and logs in."""
        reg_data = {
            'username': 'strong_user',
            'name': 'Strong User',
            'email': 'strong.user@example.com',
            'phone': '+1-555-0106',
            'gender': 'Female',
            'password': 'ComplexPassword2026!#$',
            'confirm_password': 'ComplexPassword2026!#$',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('patient_dashboard'))

        user = User.objects.get(username='strong_user')
        self.assertTrue(user.check_password('ComplexPassword2026!#$'))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

        patient = Patient.objects.get(user=user)
        self.assertEqual(patient.email, 'strong.user@example.com')

    def test_registration_attempt_to_claim_existing_patient_email_is_blocked(self):
        """Attacker cannot register an existing patient's email to hijack their medical records."""
        # Setup guest patient without user account
        guest_patient = Patient.objects.create(
            name="Confidential Walkin",
            email="confidential.walkin@example.com",
            phone="+1-555-8899",
            gender="Female"
        )
        app = Appointment.objects.create(
            patient=guest_patient,
            doctor=self.doctor,
            date=self.today + timedelta(days=2),
            time_slot="10:00-10:30",
            reason="Sensitive medical issue",
            status=AppointmentStatusChoices.CONFIRMED
        )
        report = MedicalReport.objects.create(
            patient=guest_patient,
            doctor=self.doctor,
            appointment=app,
            diagnosis="Confidential Diagnosis",
            prescription="Confidential Medication"
        )

        # Attacker attempts to register with the guest patient's email
        reg_data = {
            'username': 'attacker_user',
            'name': 'Attacker Account',
            'email': 'confidential.walkin@example.com',
            'phone': '+1-555-0666',
            'gender': 'Other',
            'password': 'AttackerPassword2026!#$',
            'confirm_password': 'AttackerPassword2026!#$',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "associated with existing hospital patient records")

        # Confirm attacker account was NOT created
        self.assertFalse(User.objects.filter(username='attacker_user').exists())

        # Confirm guest patient remains untransferred and safe
        guest_patient.refresh_from_db()
        self.assertIsNone(guest_patient.user)
        self.assertEqual(guest_patient.name, "Confidential Walkin")
        self.assertEqual(app.patient, guest_patient)
        self.assertEqual(report.patient, guest_patient)

    def test_registration_duplicate_username_case_insensitive(self):
        """Registration rejects duplicate username regardless of case."""
        reg_data = {
            'username': 'EXISTING_PATIENT',
            'name': 'Duplicate Case User',
            'email': 'different.email@example.com',
            'phone': '+1-555-0107',
            'gender': 'Male',
            'password': 'ValidPassword2026!#$',
            'confirm_password': 'ValidPassword2026!#$',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Username already taken")
        self.assertFalse(User.objects.filter(email='different.email@example.com').exists())

    def test_registration_duplicate_email_case_insensitive(self):
        """Registration rejects duplicate email regardless of case."""
        reg_data = {
            'username': 'unique_user_99',
            'name': 'Duplicate Email User',
            'email': 'EXISTING.PATIENT@EXAMPLE.COM',
            'phone': '+1-555-0108',
            'gender': 'Male',
            'password': 'ValidPassword2026!#$',
            'confirm_password': 'ValidPassword2026!#$',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "An account with this email address already exists")
        self.assertFalse(User.objects.filter(username='unique_user_99').exists())

    def test_registration_normalizes_whitespace_in_username_and_email(self):
        """Registration cleanly strips whitespace from username and email."""
        reg_data = {
            'username': '  clean_spaced_user  ',
            'name': 'Clean Spaced User',
            'email': '  Clean.Spaced@Example.com  ',
            'phone': '  +1-555-0109  ',
            'gender': 'Male',
            'password': 'ValidPassword2026!#$',
            'confirm_password': 'ValidPassword2026!#$',
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username='clean_spaced_user')
        self.assertEqual(user.email, 'clean.spaced@example.com')
        patient = Patient.objects.get(user=user)
        self.assertEqual(patient.phone, '+1-555-0109')

    def test_public_registration_never_grants_staff_or_superuser(self):
        """Public registration rejects/ignores any attempt to inject is_staff or is_superuser."""
        reg_data = {
            'username': 'hacker_staff_attempt',
            'name': 'Hacker Staff',
            'email': 'hacker@example.com',
            'phone': '+1-555-0110',
            'gender': 'Other',
            'password': 'ValidPassword2026!#$',
            'confirm_password': 'ValidPassword2026!#$',
            'is_staff': True,
            'is_superuser': True,
        }
        response = self.client.post(reverse('patient_register'), data=reg_data)
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username='hacker_staff_attempt')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_decommissioned_staff_activation_returns_404_and_does_not_promote(self):
        """HTTP requests to /activate-staff/ return 404 and cannot promote any account."""
        self.client.login(username="existing_patient", password="SecurePassword2026!#$")
        response = self.client.post(reverse('activate_staff'), {
            'username': 'existing_patient',
            'activation_key': 'AttemptAdminEscalation!'
        })
        self.assertEqual(response.status_code, 404)

        self.existing_patient_user.refresh_from_db()
        self.assertFalse(self.existing_patient_user.is_staff)
        self.assertFalse(self.existing_patient_user.is_superuser)













