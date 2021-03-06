"""empty message

Revision ID: bb6381842dea
Revises: 45282885249b
Create Date: 2016-11-03 13:23:28.734655

"""

# revision identifiers, used by Alembic.
revision = 'bb6381842dea'
down_revision = '45282885249b'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user_indigenous',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('user_id', sa.Integer(), nullable=False),
                    sa.Column('coding_id', sa.Integer(), nullable=False),
                    sa.ForeignKeyConstraint(['coding_id'], ['codings.id'], ),
                    sa.ForeignKeyConstraint(
                        ['user_id'], ['users.id'], ondelete='CASCADE'),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('user_id', 'coding_id',
                                        name='_indigenous_user_coding')
                    )
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('user_indigenous')
    ### end Alembic commands ###
