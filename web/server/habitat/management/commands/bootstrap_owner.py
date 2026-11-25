from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from habitat.models import User, SiteSettings
from habitat.views import activation_link


class Command(BaseCommand):
    help = "Create the first owner without a password. Print a one-hour, single-use setup link."

    def handle(self, *args, **options):
        with transaction.atomic():
            if User.objects.filter(role=User.Role.OWNER).exists():
                raise CommandError(
                    "Owner already exists. Never overwrite an existing owner."
                )
            SiteSettings.objects.get_or_create(pk=1)
            user = User(
                username="habitatosdevel",
                display_name="총괄 관리자",
                role=User.Role.OWNER,
            )
            user.set_unusable_password()
            user.save()
            self.stdout.write(activation_link(user))
