from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from appointments.models import Doctor, Patient, Appointment, MedicalReport, DepartmentChoices, AppointmentStatusChoices


class Command(BaseCommand):
    help = "Seeds database with initial doctors across all required departments, admin user, and sample data."

    def handle(self, *args, **options):
        self.stdout.write("Starting database seeding...")

        # Create superuser if not exists
        admin_user, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@hospitalportal.org",
                "is_staff": True,
                "is_superuser": True
            }
        )
        if created:
            admin_user.set_password("Admin@12345")
            admin_user.save()
            self.stdout.write(self.style.SUCCESS("Created superuser: admin / Admin@12345"))

        # Create demo patient user
        patient_user, p_created = User.objects.get_or_create(
            username="patient_john",
            defaults={
                "email": "john.doe@example.com",
                "first_name": "John",
                "last_name": "Doe"
            }
        )
        if p_created:
            patient_user.set_password("Patient@123")
            patient_user.save()

        # Seed Doctors
        doctors_data = [
            # Cardiology
            {
                "name": "Eleanor Vance",
                "department": DepartmentChoices.CARDIOLOGY,
                "specialization": "Interventional Cardiology",
                "consultation_fee": 120.00,
                "available_days": "Monday, Tuesday, Wednesday, Thursday, Friday",
                "active_status": True,
                "email": "dr.vance@hospitalportal.org",
                "phone": "+1-555-0101",
                "bio": "Board-certified cardiologist specializing in coronary artery disease, angioplasty, and preventative cardiology.",
                "experience_years": 14,
            },
            {
                "name": "Marcus Chen",
                "department": DepartmentChoices.CARDIOLOGY,
                "specialization": "Heart Failure & Arrhythmia",
                "consultation_fee": 110.00,
                "available_days": "Monday, Wednesday, Friday",
                "active_status": True,
                "email": "dr.chen@hospitalportal.org",
                "phone": "+1-555-0102",
                "bio": "Expert in cardiac rhythm disorders, pacemakers, and comprehensive advanced heart care.",
                "experience_years": 9,
            },
            # Pediatrics
            {
                "name": "Sarah Jenkins",
                "department": DepartmentChoices.PEDIATRICS,
                "specialization": "General Pediatrics & Neonatal Care",
                "consultation_fee": 85.00,
                "available_days": "Monday, Tuesday, Wednesday, Thursday, Friday",
                "active_status": True,
                "email": "dr.jenkins@hospitalportal.org",
                "phone": "+1-555-0201",
                "bio": "Devoted pediatrician focused on newborn care, immunization milestones, and adolescent health.",
                "experience_years": 11,
            },
            {
                "name": "David Brooks",
                "department": DepartmentChoices.PEDIATRICS,
                "specialization": "Pediatric Critical Care",
                "consultation_fee": 95.00,
                "available_days": "Tuesday, Thursday, Saturday",
                "active_status": True,
                "email": "dr.brooks@hospitalportal.org",
                "phone": "+1-555-0202",
                "bio": "Over a decade of pediatric intensive care experience, chronic pediatric illnesses, and emergency medicine.",
                "experience_years": 15,
            },
            # Orthopedics
            {
                "name": "Robert Hayes",
                "department": DepartmentChoices.ORTHOPEDICS,
                "specialization": "Joint Replacement & Sports Medicine",
                "consultation_fee": 130.00,
                "available_days": "Monday, Tuesday, Thursday",
                "active_status": True,
                "email": "dr.hayes@hospitalportal.org",
                "phone": "+1-555-0301",
                "bio": "Specializes in minimally invasive hip and knee replacements, ligament reconstruction, and athlete rehabilitation.",
                "experience_years": 16,
            },
            {
                "name": "Priya Patel",
                "department": DepartmentChoices.ORTHOPEDICS,
                "specialization": "Spine & Musculoskeletal Trauma",
                "consultation_fee": 140.00,
                "available_days": "Wednesday, Friday, Saturday",
                "active_status": True,
                "email": "dr.patel@hospitalportal.org",
                "phone": "+1-555-0302",
                "bio": "Fellowship-trained orthopedic spine specialist handling degenerative disc conditions, posture, and trauma.",
                "experience_years": 10,
            },
            # Neurology
            {
                "name": "Amanda Sterling",
                "department": DepartmentChoices.NEUROLOGY,
                "specialization": "Stroke & Neurovascular Medicine",
                "consultation_fee": 150.00,
                "available_days": "Monday, Tuesday, Wednesday, Thursday",
                "active_status": True,
                "email": "dr.sterling@hospitalportal.org",
                "phone": "+1-555-0401",
                "bio": "Leading clinical neurologist treating complex acute strokes, migraine syndromes, and neurodegenerative conditions.",
                "experience_years": 18,
            },
            {
                "name": "James Wilson",
                "department": DepartmentChoices.NEUROLOGY,
                "specialization": "Epilepsy & Neuromuscular Disorders",
                "consultation_fee": 135.00,
                "available_days": "Tuesday, Wednesday, Friday",
                "active_status": True,
                "email": "dr.wilson@hospitalportal.org",
                "phone": "+1-555-0402",
                "bio": "Dedicated to neurological diagnosis, EEG evaluations, epilepsy therapeutics, and peripheral nerve disorders.",
                "experience_years": 12,
            },
        ]

        doctors_objs = []
        for doc in doctors_data:
            obj, _ = Doctor.objects.update_or_create(
                name=doc["name"],
                defaults=doc
            )
            doctors_objs.append(obj)
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(doctors_objs)} doctors across 4 departments."))

        # Seed Patients
        patient1, _ = Patient.objects.get_or_create(
            email="john.doe@example.com",
            defaults={
                "user": patient_user,
                "name": "John Doe",
                "phone": "+1-555-7788",
                "date_of_birth": "1988-06-15",
                "gender": "Male",
                "blood_group": "O+",
                "address": "452 Elm Street, Springfield",
            }
        )

        patient2, _ = Patient.objects.get_or_create(
            email="alice.smith@example.com",
            defaults={
                "name": "Alice Smith",
                "phone": "+1-555-9922",
                "date_of_birth": "1994-11-23",
                "gender": "Female",
                "blood_group": "A+",
                "address": "12 Maple Avenue, Metropolis",
            }
        )
        self.stdout.write(self.style.SUCCESS("Seeded sample patients."))

        # Seed sample appointments (upcoming and past)
        today = timezone.localdate()
        doc_cardio = doctors_objs[0]
        doc_peds = doctors_objs[2]
        doc_ortho = doctors_objs[4]
        doc_neuro = doctors_objs[6]

        # Upcoming appointment
        app1, created1 = Appointment.objects.get_or_create(
            patient=patient1,
            doctor=doc_cardio,
            date=today + timedelta(days=2),
            time_slot="10:00-10:30",
            defaults={
                "reason": "Routine cardiac checkup and blood pressure assessment.",
                "status": AppointmentStatusChoices.CONFIRMED,
            }
        )

        # Pending appointment
        app2, created2 = Appointment.objects.get_or_create(
            patient=patient1,
            doctor=doc_neuro,
            date=today + timedelta(days=4),
            time_slot="14:00-14:30",
            defaults={
                "reason": "Recurring tension headaches and vision blur.",
                "status": AppointmentStatusChoices.PENDING,
            }
        )

        # Past completed appointment
        past_date = today - timedelta(days=10)
        app3, created3 = Appointment.objects.get_or_create(
            patient=patient1,
            doctor=doc_ortho,
            date=past_date,
            time_slot="11:00-11:30",
            defaults={
                "reason": "Right knee swelling after running marathon.",
                "status": AppointmentStatusChoices.COMPLETED,
            }
        )

        # Seed Medical Report for completed appointment
        if app3:
            report, _ = MedicalReport.objects.get_or_create(
                patient=patient1,
                doctor=doc_ortho,
                appointment=app3,
                defaults={
                    "diagnosis": "Mild patellar tendinitis with minor joint effusion.",
                    "prescription": "Ibuprofen 400mg twice daily for 5 days after food. Apply ice compress for 15 mins daily.",
                    "doctor_notes": "Advised physical therapy exercises and 2-week rest from high-impact sports.",
                }
            )

        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
