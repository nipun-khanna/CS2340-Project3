from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge_base", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="UsageLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("question_length", models.PositiveIntegerField()),
                ("success", models.BooleanField()),
                ("response_seconds", models.FloatField()),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
