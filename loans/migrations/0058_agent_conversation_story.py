# Story field on AgentConversation

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0057_agent_conversation'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentconversation',
            name='story',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Held loan draft: applicant, amount, flags, revision history.',
            ),
        ),
    ]
