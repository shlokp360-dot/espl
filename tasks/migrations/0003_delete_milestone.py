"""
The Milestone model goes; a milestone is a header task.

⚠⚠ THIS DELETES A TABLE AND ITS ROWS. Saahil's call: "it's either milestone or
   head work… we can go ahead with head work, remove the milestone, and then we
   change the name of head work to milestone."

   The two were one concept built twice. A Milestone carried a date somebody
   TYPED; a header task's finish is COMPUTED from the work under it. The two
   could disagree and the typed one would never find out — the only place in
   this module where a date was declared rather than captured.

⚠ NOTHING POINTED AT IT. No foreign key anywhere referenced Milestone, so no
  other table changes and nothing is orphaned. What is lost is the rows: on the
  demonstration data, two per project. On his real database the table is empty —
  the feature was never used on a live site.

⚠ THIS IS NOT REVERSIBLE IN THE SENSE THAT MATTERS. Django can recreate the
  table; it cannot bring the rows back. That is why it is worth saying here
  rather than in a commit message nobody re-reads.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0002_baseline_dates_and_shift_reason'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Milestone',
        ),
    ]
