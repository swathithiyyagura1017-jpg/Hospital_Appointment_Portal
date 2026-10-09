from django.urls import path
from . import views

urlpatterns = [
    # Public & Doctors
    path('', views.home_view, name='home'),
    path('doctors/', views.doctor_list_view, name='doctor_list'),
    path('doctors/<int:pk>/', views.doctor_detail_view, name='doctor_detail'),

    # Appointment Booking & Dynamic Slots API
    path('book/', views.book_appointment_view, name='book_appointment'),
    path('book/success/<int:pk>/', views.appointment_success_view, name='appointment_success'),
    path('api/slots/', views.api_get_slots, name='api_get_slots'),

    # Patient Portal
    path('dashboard/', views.patient_dashboard_view, name='patient_dashboard'),
    path('appointment/<int:pk>/cancel/', views.cancel_appointment_view, name='cancel_appointment'),
    path('reports/<int:pk>/', views.medical_report_detail_view, name='medical_report_detail'),

    # Hospital Staff & Admin Workflow
    path('staff/dashboard/', views.staff_dashboard_view, name='staff_dashboard'),
    path('staff/appointment/<int:pk>/status/', views.update_appointment_status_view, name='update_appointment_status'),
    path('staff/appointment/<int:appointment_id>/report/', views.add_medical_report_view, name='add_medical_report'),
    path('activate-staff/', views.activate_staff_view, name='activate_staff'),

    # Authentication
    path('register/', views.patient_register_view, name='patient_register'),
    path('login/', views.patient_login_view, name='patient_login'),
    path('logout/', views.patient_logout_view, name='patient_logout'),
]
