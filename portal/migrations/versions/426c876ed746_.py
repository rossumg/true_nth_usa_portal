"""empty message

Revision ID: 426c876ed746
Revises: b92dc277c384
Create Date: 2017-05-12 11:57:29.387852

"""

# revision identifiers, used by Alembic.
revision = '426c876ed746'
down_revision = 'b92dc277c384'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('organizations', sa.Column('default_locale_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'organizations', 'codings', ['default_locale_id'], ['id'])
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'organizations', type_='foreignkey')
    op.drop_column('organizations', 'default_locale_id')
    ### end Alembic commands ###
