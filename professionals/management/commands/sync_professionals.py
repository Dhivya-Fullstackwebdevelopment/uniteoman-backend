from django.core.management.base import BaseCommand
from professionals.models import Professional as ProProfessional
from services.models import Professional as ServiceProfessional

class Command(BaseCommand):
    help = 'Sync professionals from professionals app to services app'

    def handle(self, *args, **options):
        pro_pros = ProProfessional.objects.filter(is_active=True)
        
        for pro in pro_pros:
            service_pro, created = ServiceProfessional.objects.get_or_create(
                name=pro.name,
                defaults={
                    'specialty': pro.specialty,
                    'rating': pro.rating,
                    'jobs_count': pro.jobs_done,
                    'avatar': pro.avatar
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created: {service_pro.name}'))
            else:
                self.stdout.write(f'Already exists: {service_pro.name}')
        
        self.stdout.write(self.style.SUCCESS('Sync completed!'))