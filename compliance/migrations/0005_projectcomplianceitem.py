"""
A project can drop a checklist line it does not need.

>>> ANCHOR: COMPLIANCE-PRUNING <<<
Until now "not applicable to this site" could only be said by deactivating the
line in the MASTER, which removed it from every project at once. Saahil hit
exactly that: "I removed something and it disappeared from every project."

⚠⚠ AN EMPTY TABLE MEANS NOTHING HAS CHANGED. This records what a project has
   REMOVED, so on the day it ships every project still shows every line it showed
   before. There is no data migration and there is nothing to backfill — which is
   the point of storing removals rather than selections. A selection table would
   have had to write every project x every line here, and get it right.

⚠ THE TYPE-LEVEL TICK IS NOT TOUCHED. `ProjectCompliance` is untouched, and
  `applies_to()` is untouched. Ticking RERA on a project still loads all eleven
  of its items. This works one level below that, on individual lines.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('compliance', '0004_corrections_are_recorded'),
        ('projects', '0010_who_raised_delivered_and_paid'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ProjectComplianceItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('removed_at', models.DateTimeField(auto_now_add=True)),
                ('reason', models.CharField(blank=True, max_length=200)),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='removed_from_projects', to='compliance.complianceitem')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='removed_compliance_items', to='projects.project')),
                ('removed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='compliance_removals', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['item__sort_order', 'item__name'],
                'constraints': [models.UniqueConstraint(fields=('project', 'item'), name='one_removal_per_project_item')],
            },
        ),
    ]
