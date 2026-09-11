from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0096_document_committee_gate'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoanCommitteeVoteEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vote', models.CharField(choices=[('approve', 'Approve'), ('decline', 'Decline'), ('pend', 'Pend')], max_length=20)),
                ('previous_vote', models.CharField(blank=True, default='', max_length=20)),
                ('amount_supported', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('comments', models.TextField(blank=True)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, default='', max_length=512)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('approval_level', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='vote_events', to='loans.approvalcommitteelevel')),
                ('cast_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='committee_vote_events_cast_for_others', to='loans.customuser')),
                ('loan_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='committee_vote_events', to='loans.loanrequest')),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='committee_vote_events', to='loans.customuser')),
            ],
            options={
                'verbose_name': 'Committee vote event',
                'verbose_name_plural': 'Committee vote events',
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='loancommitteevoteevent',
            index=models.Index(fields=['loan_request', '-created_at'], name='loans_loanc_loan_re_7c2a1e_idx'),
        ),
    ]
