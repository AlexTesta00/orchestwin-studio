"""Distinguish owner source edits from generated and execution-repair revisions."""

from alembic import op

revision = "0042_web_source_owner_edits"
down_revision = "0041_source_text_evidence"
branch_labels = None
depends_on = None

_ORIGINS = "'GENERATED_PLAN', 'IMPORTED_BROWNFIELD', 'REPAIR_CHANGE_SET', 'DETERMINISTIC_FIXTURE'"


def upgrade():
    op.drop_constraint("ck_web_source_revisions_origin", "web_source_revisions", type_="check")
    op.create_check_constraint(
        "ck_web_source_revisions_origin",
        "web_source_revisions",
        f"origin IN ({_ORIGINS}, 'OWNER_EDIT')",
    )


def downgrade():
    # Existing owner edits are immutable audit history; a downgrade must never erase them.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM web_source_revisions WHERE origin = 'OWNER_EDIT') "
        "THEN RAISE EXCEPTION 'Cannot remove owner-edit support while owner edits exist'; "
        "END IF; END $$;"
    )
    op.drop_constraint("ck_web_source_revisions_origin", "web_source_revisions", type_="check")
    op.create_check_constraint(
        "ck_web_source_revisions_origin", "web_source_revisions", f"origin IN ({_ORIGINS})"
    )
