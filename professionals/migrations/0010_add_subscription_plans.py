from django.db import migrations


def create_subscription_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("professionals", "SubscriptionPlan")

    plans = [
        {
            "name": "starter",
            "price_omr": 5.00,
            "credits": 50,
            "leads_per_mo": 50,
            "dispatch_priority": "standard",
            "ai_job_matching": False,
            "support_level": "email",
            "dedicated_manager": False,
            "custom_sla": False,
            "is_active": True,
        },
        {
            "name": "professional",
            "price_omr": 15.00,
            "credits": 150,
            "leads_per_mo": 150,
            "dispatch_priority": "priority",
            "ai_job_matching": True,
            "support_level": "priority",
            "dedicated_manager": False,
            "custom_sla": False,
            "is_active": True,
        },
        {
            "name": "business",
            "price_omr": 30.00,
            "credits": 300,
            "leads_per_mo": 300,
            "dispatch_priority": "top",
            "ai_job_matching": True,
            "support_level": "priority",
            "dedicated_manager": True,
            "custom_sla": True,
            "is_active": True,
        },
        {
            "name": "custom",
            "price_omr": 0.00,
            "credits": 0,
            "leads_per_mo": 0,
            "dispatch_priority": "guaranteed",
            "ai_job_matching": True,
            "support_level": "dedicated",
            "dedicated_manager": True,
            "custom_sla": True,
            "is_active": True,
        },
    ]

    for plan_data in plans:
        SubscriptionPlan.objects.update_or_create(
            name=plan_data["name"],
            defaults=plan_data,
        )


class Migration(migrations.Migration):

    dependencies = [
      ("professionals", "0009_subscriptionplan_credittransaction_vendorlocation_and_more"),
]
    operations = [
        migrations.RunPython(create_subscription_plans),
    ]