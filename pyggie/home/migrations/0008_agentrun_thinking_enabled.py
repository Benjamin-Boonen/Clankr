from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("home", "0007_attachments"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="thinking_enabled",
            field=models.BooleanField(default=True),
        ),
    ]
