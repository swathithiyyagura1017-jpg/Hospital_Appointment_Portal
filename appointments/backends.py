import logging
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q

logger = logging.getLogger('appointments.auth')


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Custom authentication backend that permits authentication using either:
    1. Case-insensitive username
    2. Case-insensitive email address
    
    Security:
    - Strips leading and trailing whitespace from the identifier.
    - Never logs passwords or sensitive information.
    - Defends against timing attacks by calling User().set_password(password)
      when no user record is found.
    - Enforces is_active via self.user_can_authenticate(user).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        clean_identifier = str(username).strip()
        if not clean_identifier:
            return None

        try:
            # Query case-insensitively by username or email
            user = User.objects.filter(
                Q(username__iexact=clean_identifier) | Q(email__iexact=clean_identifier)
            ).first()
        except Exception as e:
            logger.error(f"Error querying user during authentication: {type(e).__name__}")
            return None

        if user is None:
            # Timing attack mitigation: run password hasher even if user doesn't exist
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
