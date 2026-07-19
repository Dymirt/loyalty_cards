from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from marketing.models import MarketingLead


class Command(BaseCommand):
    help = "Report marketing leads due for review without changing or deleting them."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.MARKETING_LEAD_RETENTION_DAYS)

    def handle(self, *args, **options):
        if options["days"] <= 0:
            raise CommandError("--days must be positive.")
        cutoff = timezone.now() - timedelta(days=options["days"])
        count = MarketingLead.objects.filter(created_at__lt=cutoff).count()
        self.stdout.write(
            f"cutoff={cutoff.isoformat()} due_for_review={count} mutation=none"
        )
