import getpass
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


class Command(BaseCommand):
    help = "Creates or updates the dedicated staff account 'demo_staff' with secure password prompt or argument."

    def add_arguments(self, parser):
        parser.add_argument(
            '--check',
            action='store_true',
            help='Check status and permissions of demo_staff without modifying database.'
        )
        parser.add_argument(
            '--password',
            type=str,
            nargs='?',
            default=None,
            help='Optional password value for scripted setups (if omitted, prompts interactively).'
        )

    def handle(self, *args, **options):
        if options.get('check'):
            staff = User.objects.filter(username='demo_staff').first()
            if not staff:
                self.stdout.write(self.style.ERROR("User 'demo_staff' does not exist in the database."))
                return
            self.stdout.write(self.style.SUCCESS(
                f"demo_staff exists | is_staff={staff.is_staff} | is_superuser={staff.is_superuser} | "
                f"is_active={staff.is_active} | has_usable_password={staff.has_usable_password()}"
            ))
            return

        password = options.get('password')
        if password is None:
            self.stdout.write(self.style.NOTICE("=== Secure Staff Account Setup: demo_staff ==="))
            self.stdout.write("Enter the password for 'demo_staff'. Input is masked and will not be displayed or printed.")

            while True:
                password = getpass.getpass("Enter password: ")
                if not password:
                    self.stdout.write(self.style.ERROR("Password cannot be blank. Please try again."))
                    continue
                confirm = getpass.getpass("Confirm password: ")
                if password != confirm:
                    self.stdout.write(self.style.ERROR("Passwords do not match. Please try again."))
                    continue
                try:
                    validate_password(password)
                except ValidationError as err:
                    for msg in err.messages:
                        self.stdout.write(self.style.ERROR(f"- {msg}"))
                    self.stdout.write(self.style.WARNING("Please choose a stronger password matching the requirements above."))
                    continue
                break
        else:
            try:
                validate_password(password)
            except ValidationError as err:
                for msg in err.messages:
                    self.stdout.write(self.style.ERROR(f"- {msg}"))
                self.stdout.write(self.style.WARNING("Password validation warning; proceeding with setup."))

        user, created = User.objects.get_or_create(
            username='demo_staff',
            defaults={
                'email': 'demo.staff@hospitalportal.org',
                'first_name': 'Demo',
                'last_name': 'Staff',
                'is_staff': True,
                'is_superuser': False,
                'is_active': True,
            }
        )
        user.is_staff = True
        user.is_superuser = False
        user.is_active = True
        user.set_password(password)
        user.save()

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"Successfully {action.lower()} staff user 'demo_staff' (is_staff=True, is_superuser=False, is_active=True)."
        ))
