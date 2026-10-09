import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = "Promotes a registered user to hospital staff using the STAFF_USERNAME environment variable."

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            help="Optional command-line override for the target username."
        )

    def handle(self, *args, **options):
        # 1. Read target username from STAFF_USERNAME environment variable (or command argument)
        target_username = os.environ.get('STAFF_USERNAME')
        if not target_username:
            target_username = options.get('username')

        # 2. If the variable is absent, exit safely without changing anything
        if not target_username or not target_username.strip():
            self.stdout.write(
                self.style.WARNING("STAFF_USERNAME environment variable is not set. No changes were made.")
            )
            return

        target_username = target_username.strip()

        # 3. Look up user by username
        user = User.objects.filter(username=target_username).first()
        if not user:
            self.stdout.write(
                self.style.WARNING(f"User '{target_username}' was not found in the database. No changes were made.")
            )
            return

        # 4. Set is_staff = True and is_superuser = False (do not alter password or other fields)
        user.is_staff = True
        user.is_superuser = False
        user.save(update_fields=['is_staff', 'is_superuser'])

        self.stdout.write(
            self.style.SUCCESS(f"Successfully promoted user '{target_username}' to hospital staff (is_staff=True).")
        )
