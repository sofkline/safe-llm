"""remove_fk_predict_user_id

Revision ID: 5118ea6ab344
Revises: 
Create Date: 2026-05-17 17:22:45.693808

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5118ea6ab344'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_LiteLLM_PredictTable_user_id_LiteLLM_UserTable",
        "LiteLLM_PredictTable",
        type_="foreignkey"
    )

def downgrade() -> None:
    op.create_foreign_key(
        "fk_LiteLLM_PredictTable_user_id_LiteLLM_UserTable",
        "LiteLLM_PredictTable",
        "LiteLLM_UserTable",
        ["user_id"],
        ["user_id"],
        ondelete="CASCADE"
    )