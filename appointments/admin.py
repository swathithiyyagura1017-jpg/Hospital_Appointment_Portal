from django.contrib import admin
from .models import Doctor, Patient, Appointment, MedicalReport


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ('name', 'department', 'specialization', 'consultation_fee', 'active_status')
    list_filter = ('department', 'active_status')
    search_fields = ('name', 'specialization', 'department')
    list_editable = ('active_status', 'consultation_fee')


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email', 'gender', 'blood_group', 'created_at')
    list_filter = ('gender', 'blood_group')
    search_fields = ('name', 'phone', 'email')


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'doctor', 'date', 'time_slot', 'status', 'created_date')
    list_filter = ('status', 'doctor__department', 'date')
    search_fields = ('patient__name', 'doctor__name', 'reason')
    list_editable = ('status',)
    actions = ['mark_confirmed', 'mark_completed', 'mark_cancelled']

    @admin.action(description="Mark selected appointments as Confirmed")
    def mark_confirmed(self, request, queryset):
        queryset.update(status='Confirmed')

    @admin.action(description="Mark selected appointments as Completed")
    def mark_completed(self, request, queryset):
        queryset.update(status='Completed')

    @admin.action(description="Mark selected appointments as Cancelled")
    def mark_cancelled(self, request, queryset):
        queryset.update(status='Cancelled')


@admin.register(MedicalReport)
class MedicalReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'doctor', 'report_date', 'created_at')
    list_filter = ('report_date', 'doctor__department')
    search_fields = ('patient__name', 'doctor__name', 'diagnosis')
