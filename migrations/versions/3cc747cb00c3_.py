"""empty message

Revision ID: 3cc747cb00c3
Revises: 50da86128cfc
Create Date: 2016-03-03 15:46:00.210735

"""

# revision identifiers, used by Alembic.
revision = '3cc747cb00c3'
down_revision = '50da86128cfc'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'locale')
    op.add_column('users', sa.Column('locale_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_users_locale_id', 'users', 'codeable_concepts', ['locale_id'], ['id'])
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('fk_users_locale_id', 'users', type_='foreignkey')
    op.drop_column('users', 'locale_id')
    op.add_column('users', sa.Column('locale', sa.String(length=20),
                                     nullable=True))
    ### end Alembic commands ###
