"""contacts confirm and constraints

Revision ID: c9af97b1b25c
Revises: 2583d9590873
Create Date: 2026-09-04 17:51:59.621790

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9af97b1b25c'
down_revision: Union[str, Sequence[str], None] = '2583d9590873'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `contacts` has never held a row -- no endpoint or service has written to
    # it since the initial migration, and seed_demo does not create any -- so
    # these constraints cannot fail on existing data and no backfill is needed.
    op.add_column('contacts', sa.Column('confirmed_at', sa.DateTime(),
                                        nullable=True))
    op.add_column('contacts', sa.Column('discovery_note', sa.String(),
                                        nullable=True))
    op.create_unique_constraint('uq_contacts_business_email', 'contacts',
                                ['business_id', 'email'])
    op.create_index('uq_contacts_one_primary', 'contacts', ['business_id'],
                    unique=True, postgresql_where=sa.text('is_primary'))
    op.alter_column('contacts', 'created_at',
                    server_default=sa.text('now()'), existing_type=sa.DateTime(),
                    existing_nullable=True)


def downgrade() -> None:
    op.alter_column('contacts', 'created_at', server_default=None,
                    existing_type=sa.DateTime(), existing_nullable=True)
    op.drop_index('uq_contacts_one_primary', table_name='contacts')
    op.drop_constraint('uq_contacts_business_email', 'contacts', type_='unique')
    op.drop_column('contacts', 'discovery_note')
    op.drop_column('contacts', 'confirmed_at')
