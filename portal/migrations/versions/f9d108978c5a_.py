"""empty message

Revision ID: f9d108978c5a
Revises: 24d8d4008534
Create Date: 2016-04-26 17:57:43.813601

"""

# revision identifiers, used by Alembic.
revision = 'f9d108978c5a'
down_revision = '24d8d4008534'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('access_strategies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('intervention_id', sa.Integer(), nullable=True),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('function_details', postgresql.JSONB(), nullable=False),
    sa.ForeignKeyConstraint(['intervention_id'], ['interventions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('access_strategies')
    ### end Alembic commands ###