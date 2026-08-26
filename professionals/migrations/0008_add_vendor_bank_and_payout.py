from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('professionals', '0007_review_admin_note_review_ai_flag_review_booking_and_more'),
    ]
    operations = [
        migrations.CreateModel(
            name='VendorBankAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('bank_name', models.CharField(max_length=100)),
                ('account_name', models.CharField(max_length=150)),
                ('iban', models.CharField(max_length=40)),
                ('is_primary', models.BooleanField(default=True)),
                ('is_verified', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('professional', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bank_accounts', to='professionals.professional')),
            ],
            options={'unique_together': {('professional', 'is_primary')}},
        ),
        migrations.CreateModel(
            name='PayoutRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month_start', models.DateField()),
                ('month_end', models.DateField()),
                ('gross_amount', models.DecimalField(decimal_places=3, max_digits=12)),
                ('platform_fee', models.DecimalField(decimal_places=3, max_digits=12)),
                ('net_amount', models.DecimalField(decimal_places=3, max_digits=12)),
                ('booking_ids', models.JSONField(default=list)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('paid', 'Paid'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('admin_note', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('bank_account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='professionals.vendorbankaccount')),
                ('professional', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payout_requests', to='professionals.professional')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]