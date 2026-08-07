# Generated manually for Agentic Assist chatbot

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0056_agent_run'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentConversation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, max_length=200)),
                ('messages', models.JSONField(blank=True, default=list)),
                ('ui_messages', models.JSONField(blank=True, default=list)),
                ('llm_provider', models.CharField(blank=True, max_length=40)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_loan_request', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='agent_conversations',
                    to='loans.loanrequest',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='agent_conversations',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Agent conversation',
                'verbose_name_plural': 'Agent conversations',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.AddField(
            model_name='agentrun',
            name='conversation',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='runs',
                to='loans.agentconversation',
            ),
        ),
    ]
