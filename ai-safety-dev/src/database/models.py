import enum

from sqlalchemy import (
    ARRAY,
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    text,
)
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    __abstract__ = True

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_`%(constraint_name)s`",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )

    def __str__(self):
        attrs = ", ".join(f"{key}={value!r}" for key, value in vars(self).items())
        return f"{self.__class__.__name__}({attrs})"


class JobStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LiteLLM_BudgetTable(Base):
    __tablename__ = "LiteLLM_BudgetTable"
    budget_id = mapped_column(String, primary_key=True)
    max_budget = mapped_column(Float, nullable=True)
    soft_budget = mapped_column(Float, nullable=True)
    max_parallel_requests = mapped_column(Integer, nullable=True)
    tpm_limit = mapped_column(BigInteger, nullable=True)
    rpm_limit = mapped_column(BigInteger, nullable=True)
    model_max_budget = mapped_column(JSON, nullable=True)
    budget_duration = mapped_column(String, nullable=True)
    budget_reset_at = mapped_column(DateTime, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=False)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=False)


class LiteLLM_CredentialsTable(Base):
    __tablename__ = "LiteLLM_CredentialsTable"
    credential_id = mapped_column(String, primary_key=True)
    credential_name = mapped_column(String, unique=True, nullable=False)
    credential_values = mapped_column(JSON, nullable=False)
    credential_info = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=False)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=False)


class LiteLLM_ProxyModelTable(Base):
    __tablename__ = "LiteLLM_ProxyModelTable"
    model_id = mapped_column(String, primary_key=True)
    model_name = mapped_column(String, nullable=False)
    litellm_params = mapped_column(JSON, nullable=False)
    model_info = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=False)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=False)


class LiteLLM_AgentsTable(Base):
    __tablename__ = "LiteLLM_AgentsTable"
    agent_id = mapped_column(String, primary_key=True)
    agent_name = mapped_column(String, unique=True, nullable=False)
    litellm_params = mapped_column(JSON, nullable=True)
    agent_card_params = mapped_column(JSON, nullable=False)
    agent_access_groups = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=False)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=False)


class LiteLLM_OrganizationTable(Base):
    __tablename__ = "LiteLLM_OrganizationTable"
    organization_id = mapped_column(String, primary_key=True)
    organization_alias = mapped_column(String, nullable=False)
    budget_id = mapped_column(String, ForeignKey("LiteLLM_BudgetTable.budget_id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False)
    metadata_json = mapped_column("metadata", JSON, nullable=False, server_default=text("'{}'"))
    models = mapped_column(ARRAY(String), nullable=True)
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    model_spend = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    object_permission_id = mapped_column(String, ForeignKey("LiteLLM_ObjectPermissionTable.object_permission_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=False)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=False)


class LiteLLM_ModelTable(Base):
    __tablename__ = "LiteLLM_ModelTable"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    aliases = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=False)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=False)


class LiteLLM_TeamTable(Base):
    __tablename__ = "LiteLLM_TeamTable"
    team_id = mapped_column(String, primary_key=True)
    team_alias = mapped_column(String, nullable=True)
    organization_id = mapped_column(String, ForeignKey("LiteLLM_OrganizationTable.organization_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    object_permission_id = mapped_column(String, ForeignKey("LiteLLM_ObjectPermissionTable.object_permission_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    admins = mapped_column(ARRAY(String), nullable=True)
    members = mapped_column(ARRAY(String), nullable=True)
    members_with_roles = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    metadata_json = mapped_column("metadata", JSON, nullable=False, server_default=text("'{}'"))
    max_budget = mapped_column(Float, nullable=True)
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    models = mapped_column(ARRAY(String), nullable=True)
    max_parallel_requests = mapped_column(Integer, nullable=True)
    tpm_limit = mapped_column(BigInteger, nullable=True)
    rpm_limit = mapped_column(BigInteger, nullable=True)
    budget_duration = mapped_column(String, nullable=True)
    budget_reset_at = mapped_column(DateTime, nullable=True)
    blocked = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    model_spend = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    model_max_budget = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    router_settings = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    team_member_permissions = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    policies = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    model_id = mapped_column(Integer, ForeignKey("LiteLLM_ModelTable.id", ondelete="SET NULL", onupdate="CASCADE"), unique=True, nullable=True)


class LiteLLM_DeletedTeamTable(Base):
    __tablename__ = "LiteLLM_DeletedTeamTable"
    __table_args__ = (
        Index("LiteLLM_DeletedTeamTable_team_id_idx", "team_id"),
        Index("LiteLLM_DeletedTeamTable_deleted_at_idx", "deleted_at"),
        Index("LiteLLM_DeletedTeamTable_organization_id_idx", "organization_id"),
        Index("LiteLLM_DeletedTeamTable_team_alias_idx", "team_alias"),
        Index("LiteLLM_DeletedTeamTable_created_at_idx", "created_at"),
    )
    id = mapped_column(String, primary_key=True)
    team_id = mapped_column(String, nullable=False)
    team_alias = mapped_column(String, nullable=True)
    organization_id = mapped_column(String, nullable=True)
    object_permission_id = mapped_column(String, nullable=True)
    admins = mapped_column(ARRAY(String), nullable=True)
    members = mapped_column(ARRAY(String), nullable=True)
    members_with_roles = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    metadata_json = mapped_column("metadata", JSON, nullable=False, server_default=text("'{}'"))
    max_budget = mapped_column(Float, nullable=True)
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    models = mapped_column(ARRAY(String), nullable=True)
    max_parallel_requests = mapped_column(Integer, nullable=True)
    tpm_limit = mapped_column(BigInteger, nullable=True)
    rpm_limit = mapped_column(BigInteger, nullable=True)
    budget_duration = mapped_column(String, nullable=True)
    budget_reset_at = mapped_column(DateTime, nullable=True)
    blocked = mapped_column(Boolean, nullable=False, server_default=text("false"))
    model_spend = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    model_max_budget = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    router_settings = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    team_member_permissions = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    policies = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    model_id = mapped_column(Integer, nullable=True)
    created_at = mapped_column(DateTime, nullable=True)
    updated_at = mapped_column(DateTime, nullable=True)
    deleted_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    deleted_by = mapped_column(String, nullable=True)
    deleted_by_api_key = mapped_column(String, nullable=True)
    litellm_changed_by = mapped_column(String, nullable=True)


class LiteLLM_UserTable(Base):
    __tablename__ = "LiteLLM_UserTable"
    user_id = mapped_column(String, primary_key=True)
    user_alias = mapped_column(String, nullable=True)
    team_id = mapped_column(String, nullable=True)
    sso_user_id = mapped_column(String, unique=True, nullable=True)
    organization_id = mapped_column(String, ForeignKey("LiteLLM_OrganizationTable.organization_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    object_permission_id = mapped_column(String, ForeignKey("LiteLLM_ObjectPermissionTable.object_permission_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    password = mapped_column(String, nullable=True)
    teams = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    user_role = mapped_column(String, nullable=True)
    max_budget = mapped_column(Float, nullable=True)
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    user_email = mapped_column(String, nullable=True)
    models = mapped_column(ARRAY(String), nullable=True)
    metadata_json = mapped_column("metadata", JSON, nullable=False, server_default=text("'{}'"))
    max_parallel_requests = mapped_column(Integer, nullable=True)
    tpm_limit = mapped_column(BigInteger, nullable=True)
    rpm_limit = mapped_column(BigInteger, nullable=True)
    budget_duration = mapped_column(String, nullable=True)
    budget_reset_at = mapped_column(DateTime, nullable=True)
    allowed_cache_controls = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    policies = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    model_spend = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    model_max_budget = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    created_at = mapped_column(DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP"))


class LiteLLM_ObjectPermissionTable(Base):
    __tablename__ = "LiteLLM_ObjectPermissionTable"
    object_permission_id = mapped_column(String, primary_key=True)
    mcp_servers = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    mcp_access_groups = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    mcp_tool_permissions = mapped_column(JSON, nullable=True)
    vector_stores = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    agents = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    agent_access_groups = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))


class LiteLLM_MCPServerTable(Base):
    __tablename__ = "LiteLLM_MCPServerTable"
    server_id = mapped_column(String, primary_key=True)
    server_name = mapped_column(String, nullable=True)
    alias = mapped_column(String, nullable=True)
    description = mapped_column(String, nullable=True)
    url = mapped_column(String, nullable=True)
    transport = mapped_column(String, nullable=False, server_default=text("'sse'"))
    auth_type = mapped_column(String, nullable=True)
    credentials = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    created_at = mapped_column(DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=True)
    updated_at = mapped_column(DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=True)
    mcp_info = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    mcp_access_groups = mapped_column(ARRAY(String), nullable=True)
    allowed_tools = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    extra_headers = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    static_headers = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    status = mapped_column(String, nullable=True, server_default=text("'unknown'"))
    last_health_check = mapped_column(DateTime, nullable=True)
    health_check_error = mapped_column(String, nullable=True)
    command = mapped_column(String, nullable=True)
    args = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    env = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    authorization_url = mapped_column(String, nullable=True)
    token_url = mapped_column(String, nullable=True)
    registration_url = mapped_column(String, nullable=True)
    allow_all_keys = mapped_column(Boolean, nullable=False, server_default=text("false"))


class LiteLLM_VerificationToken(Base):
    __tablename__ = "LiteLLM_VerificationToken"
    token = mapped_column(String, primary_key=True)
    key_name = mapped_column(String, nullable=True)
    key_alias = mapped_column(String, nullable=True)
    soft_budget_cooldown = mapped_column(Boolean, nullable=False, server_default=text("false"))
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    expires = mapped_column(DateTime, nullable=True)
    models = mapped_column(ARRAY(String), nullable=True)
    aliases = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    config = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    router_settings = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    user_id = mapped_column(String, nullable=True)
    team_id = mapped_column(String, nullable=True)
    permissions = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    max_parallel_requests = mapped_column(Integer, nullable=True)
    metadata_json = mapped_column("metadata", JSON, nullable=False, server_default=text("'{}'"))
    blocked = mapped_column(Boolean, nullable=True)
    tpm_limit = mapped_column(BigInteger, nullable=True)
    rpm_limit = mapped_column(BigInteger, nullable=True)
    max_budget = mapped_column(Float, nullable=True)
    budget_duration = mapped_column(String, nullable=True)
    budget_reset_at = mapped_column(DateTime, nullable=True)
    allowed_cache_controls = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    allowed_routes = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    policies = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    model_spend = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    model_max_budget = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    budget_id = mapped_column(String, ForeignKey("LiteLLM_BudgetTable.budget_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    organization_id = mapped_column(String, ForeignKey("LiteLLM_OrganizationTable.organization_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    object_permission_id = mapped_column(String, ForeignKey("LiteLLM_ObjectPermissionTable.object_permission_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    created_at = mapped_column(DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=True)
    updated_at = mapped_column(DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=True)
    rotation_count = mapped_column(Integer, nullable=True, server_default=text("0"))
    auto_rotate = mapped_column(Boolean, nullable=True, server_default=text("false"))
    rotation_interval = mapped_column(String, nullable=True)
    last_rotation_at = mapped_column(DateTime, nullable=True)
    key_rotation_at = mapped_column(DateTime, nullable=True)


class LiteLLM_DeletedVerificationToken(Base):
    __tablename__ = "LiteLLM_DeletedVerificationToken"
    __table_args__ = (
        Index("LiteLLM_DeletedVerificationToken_token_idx", "token"),
        Index("LiteLLM_DeletedVerificationToken_deleted_at_idx", "deleted_at"),
        Index("LiteLLM_DeletedVerificationToken_user_id_idx", "user_id"),
        Index("LiteLLM_DeletedVerificationToken_team_id_idx", "team_id"),
        Index("LiteLLM_DeletedVerificationToken_organization_id_idx", "organization_id"),
        Index("LiteLLM_DeletedVerificationToken_key_alias_idx", "key_alias"),
        Index("LiteLLM_DeletedVerificationToken_created_at_idx", "created_at"),
    )
    id = mapped_column(String, primary_key=True)
    token = mapped_column(String, nullable=False)
    key_name = mapped_column(String, nullable=True)
    key_alias = mapped_column(String, nullable=True)
    soft_budget_cooldown = mapped_column(Boolean, nullable=False, server_default=text("false"))
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    expires = mapped_column(DateTime, nullable=True)
    models = mapped_column(ARRAY(String), nullable=True)
    aliases = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    config = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    user_id = mapped_column(String, nullable=True)
    team_id = mapped_column(String, nullable=True)
    permissions = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    max_parallel_requests = mapped_column(Integer, nullable=True)
    metadata_json = mapped_column("metadata", JSON, nullable=False, server_default=text("'{}'"))
    blocked = mapped_column(Boolean, nullable=True)
    tpm_limit = mapped_column(BigInteger, nullable=True)
    rpm_limit = mapped_column(BigInteger, nullable=True)
    max_budget = mapped_column(Float, nullable=True)
    budget_duration = mapped_column(String, nullable=True)
    budget_reset_at = mapped_column(DateTime, nullable=True)
    allowed_cache_controls = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    allowed_routes = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    policies = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    model_spend = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    model_max_budget = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    router_settings = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    budget_id = mapped_column(String, nullable=True)
    organization_id = mapped_column(String, nullable=True)
    object_permission_id = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime, nullable=True)
    created_by = mapped_column(String, nullable=True)
    updated_at = mapped_column(DateTime, nullable=True)
    updated_by = mapped_column(String, nullable=True)
    rotation_count = mapped_column(Integer, nullable=True, server_default=text("0"))
    auto_rotate = mapped_column(Boolean, nullable=True, server_default=text("false"))
    rotation_interval = mapped_column(String, nullable=True)
    last_rotation_at = mapped_column(DateTime, nullable=True)
    key_rotation_at = mapped_column(DateTime, nullable=True)
    deleted_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    deleted_by = mapped_column(String, nullable=True)
    deleted_by_api_key = mapped_column(String, nullable=True)
    litellm_changed_by = mapped_column(String, nullable=True)


class LiteLLM_EndUserTable(Base):
    __tablename__ = "LiteLLM_EndUserTable"
    user_id = mapped_column(String, primary_key=True)
    alias = mapped_column(String, nullable=True)
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    allowed_model_region = mapped_column(String, nullable=True)
    default_model = mapped_column(String, nullable=True)
    budget_id = mapped_column(String, ForeignKey("LiteLLM_BudgetTable.budget_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    blocked = mapped_column(Boolean, nullable=False, server_default=text("false"))


class LiteLLM_TagTable(Base):
    __tablename__ = "LiteLLM_TagTable"
    tag_name = mapped_column(String, primary_key=True)
    description = mapped_column(String, nullable=True)
    models = mapped_column(ARRAY(String), nullable=True)
    model_info = mapped_column(JSON, nullable=True)
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    budget_id = mapped_column(String, ForeignKey("LiteLLM_BudgetTable.budget_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=True)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class LiteLLM_Config(Base):
    __tablename__ = "LiteLLM_Config"
    param_name = mapped_column(String, primary_key=True)
    param_value = mapped_column(JSON, nullable=True)


class LiteLLM_SpendLogs(Base):
    __tablename__ = "LiteLLM_SpendLogs"
    __table_args__ = (
        Index("LiteLLM_SpendLogs_startTime_idx", "startTime"),
        Index("LiteLLM_SpendLogs_end_user_idx", "end_user"),
        Index("LiteLLM_SpendLogs_session_id_idx", "session_id"),
    )
    request_id = mapped_column(String, primary_key=True)
    call_type = mapped_column(String, nullable=False)
    api_key = mapped_column(String, nullable=False, server_default=text("''"))
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    total_tokens = mapped_column(Integer, nullable=False, server_default=text("0"))
    prompt_tokens = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens = mapped_column(Integer, nullable=False, server_default=text("0"))
    startTime = mapped_column(DateTime, nullable=False)
    endTime = mapped_column(DateTime, nullable=False)
    completionStartTime = mapped_column(DateTime, nullable=True)
    model = mapped_column(String, nullable=False, server_default=text("''"))
    model_id = mapped_column(String, nullable=True, server_default=text("''"))
    model_group = mapped_column(String, nullable=True, server_default=text("''"))
    custom_llm_provider = mapped_column(String, nullable=True, server_default=text("''"))
    api_base = mapped_column(String, nullable=True, server_default=text("''"))
    user = mapped_column(String, nullable=True, server_default=text("''"))
    metadata_json = mapped_column("metadata", JSON, nullable=True, server_default=text("'{}'"))
    cache_hit = mapped_column(String, nullable=True, server_default=text("''"))
    cache_key = mapped_column(String, nullable=True, server_default=text("''"))
    request_tags = mapped_column(JSON, nullable=True, server_default=text("'[]'"))
    team_id = mapped_column(String, nullable=True)
    organization_id = mapped_column(String, nullable=True)
    end_user = mapped_column(String, nullable=True)
    requester_ip_address = mapped_column(String, nullable=True)
    messages = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    response = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    session_id = mapped_column(String, nullable=True)
    status = mapped_column(String, nullable=True)
    mcp_namespaced_tool_name = mapped_column(String, nullable=True)
    agent_id = mapped_column(String, nullable=True)
    proxy_server_request = mapped_column(JSON, nullable=True, server_default=text("'{}'"))


class LiteLLM_ErrorLogs(Base):
    __tablename__ = "LiteLLM_ErrorLogs"
    request_id = mapped_column(String, primary_key=True)
    startTime = mapped_column(DateTime, nullable=False)
    endTime = mapped_column(DateTime, nullable=False)
    api_base = mapped_column(String, nullable=False, server_default=text("''"))
    model_group = mapped_column(String, nullable=False, server_default=text("''"))
    litellm_model_name = mapped_column(String, nullable=False, server_default=text("''"))
    model_id = mapped_column(String, nullable=False, server_default=text("''"))
    request_kwargs = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    exception_type = mapped_column(String, nullable=False, server_default=text("''"))
    exception_string = mapped_column(String, nullable=False, server_default=text("''"))
    status_code = mapped_column(String, nullable=False, server_default=text("''"))


class LiteLLM_UserNotifications(Base):
    __tablename__ = "LiteLLM_UserNotifications"
    request_id = mapped_column(String, primary_key=True)
    user_id = mapped_column(String, nullable=False)
    models = mapped_column(ARRAY(String), nullable=True)
    justification = mapped_column(String, nullable=False)
    status = mapped_column(String, nullable=False)


class LiteLLM_TeamMembership(Base):
    __tablename__ = "LiteLLM_TeamMembership"
    user_id = mapped_column(String, primary_key=True)
    team_id = mapped_column(String, primary_key=True)
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    budget_id = mapped_column(String, ForeignKey("LiteLLM_BudgetTable.budget_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)


class LiteLLM_OrganizationMembership(Base):
    __tablename__ = "LiteLLM_OrganizationMembership"
    __table_args__ = (
        Index("LiteLLM_OrganizationMembership_user_id_organization_id_key", "user_id", "organization_id", unique=True),
    )
    user_id = mapped_column(String, ForeignKey("LiteLLM_UserTable.user_id", ondelete="RESTRICT", onupdate="CASCADE"), primary_key=True)
    organization_id = mapped_column(String, ForeignKey("LiteLLM_OrganizationTable.organization_id", ondelete="RESTRICT", onupdate="CASCADE"), primary_key=True)
    user_role = mapped_column(String, nullable=True)
    spend = mapped_column(Float, nullable=True, server_default=text("0.0"))
    budget_id = mapped_column(String, ForeignKey("LiteLLM_BudgetTable.budget_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    created_at = mapped_column(DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP"))


class LiteLLM_InvitationLink(Base):
    __tablename__ = "LiteLLM_InvitationLink"
    id = mapped_column(String, primary_key=True)
    user_id = mapped_column(String, ForeignKey("LiteLLM_UserTable.user_id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False)
    is_accepted = mapped_column(Boolean, nullable=False, server_default=text("false"))
    accepted_at = mapped_column(DateTime, nullable=True)
    expires_at = mapped_column(DateTime, nullable=False)
    created_at = mapped_column(DateTime, nullable=False)
    created_by = mapped_column(String, ForeignKey("LiteLLM_UserTable.user_id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False)
    updated_at = mapped_column(DateTime, nullable=False)
    updated_by = mapped_column(String, ForeignKey("LiteLLM_UserTable.user_id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False)


class LiteLLM_AuditLog(Base):
    __tablename__ = "LiteLLM_AuditLog"
    id = mapped_column(String, primary_key=True)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    changed_by = mapped_column(String, nullable=False, server_default=text("''"))
    changed_by_api_key = mapped_column(String, nullable=False, server_default=text("''"))
    action = mapped_column(String, nullable=False)
    table_name = mapped_column(String, nullable=False)
    object_id = mapped_column(String, nullable=False)
    before_value = mapped_column(JSON, nullable=True)
    updated_values = mapped_column(JSON, nullable=True)


class LiteLLM_DailyUserSpend(Base):
    __tablename__ = "LiteLLM_DailyUserSpend"
    __table_args__ = (
        Index("LiteLLM_DailyUserSpend_date_idx", "date"),
        Index("LiteLLM_DailyUserSpend_user_id_idx", "user_id"),
        Index("LiteLLM_DailyUserSpend_api_key_idx", "api_key"),
        Index("LiteLLM_DailyUserSpend_model_idx", "model"),
        Index("LiteLLM_DailyUserSpend_mcp_namespaced_tool_name_idx", "mcp_namespaced_tool_name"),
        Index("LiteLLM_DailyUserSpend_endpoint_idx", "endpoint"),
        Index("LiteLLM_DailyUserSpend_user_id_date_api_key_model_custom_ll_key", "user_id", "date", "api_key", "model", "custom_llm_provider", "mcp_namespaced_tool_name", "endpoint", unique=True),
    )
    id = mapped_column(String, primary_key=True)
    user_id = mapped_column(String, nullable=True)
    date = mapped_column(String, nullable=False)
    api_key = mapped_column(String, nullable=False)
    model = mapped_column(String, nullable=True)
    model_group = mapped_column(String, nullable=True)
    custom_llm_provider = mapped_column(String, nullable=True)
    mcp_namespaced_tool_name = mapped_column(String, nullable=True)
    endpoint = mapped_column(String, nullable=True)
    prompt_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    completion_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_read_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_creation_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    api_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    successful_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    failed_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_DailyOrganizationSpend(Base):
    __tablename__ = "LiteLLM_DailyOrganizationSpend"
    __table_args__ = (
        Index("LiteLLM_DailyOrganizationSpend_date_idx", "date"),
        Index("LiteLLM_DailyOrganizationSpend_organization_id_idx", "organization_id"),
        Index("LiteLLM_DailyOrganizationSpend_api_key_idx", "api_key"),
        Index("LiteLLM_DailyOrganizationSpend_model_idx", "model"),
        Index("LiteLLM_DailyOrganizationSpend_mcp_namespaced_tool_name_idx", "mcp_namespaced_tool_name"),
        Index("LiteLLM_DailyOrganizationSpend_endpoint_idx", "endpoint"),
        Index("LiteLLM_DailyOrganizationSpend_organization_id_date_api_key_key", "organization_id", "date", "api_key", "model", "custom_llm_provider", "mcp_namespaced_tool_name", "endpoint", unique=True),
    )
    id = mapped_column(String, primary_key=True)
    organization_id = mapped_column(String, nullable=True)
    date = mapped_column(String, nullable=False)
    api_key = mapped_column(String, nullable=False)
    model = mapped_column(String, nullable=True)
    model_group = mapped_column(String, nullable=True)
    custom_llm_provider = mapped_column(String, nullable=True)
    mcp_namespaced_tool_name = mapped_column(String, nullable=True)
    endpoint = mapped_column(String, nullable=True)
    prompt_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    completion_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_read_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_creation_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    api_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    successful_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    failed_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_DailyEndUserSpend(Base):
    __tablename__ = "LiteLLM_DailyEndUserSpend"
    __table_args__ = (
        Index("LiteLLM_DailyEndUserSpend_date_idx", "date"),
        Index("LiteLLM_DailyEndUserSpend_end_user_id_idx", "end_user_id"),
        Index("LiteLLM_DailyEndUserSpend_api_key_idx", "api_key"),
        Index("LiteLLM_DailyEndUserSpend_model_idx", "model"),
        Index("LiteLLM_DailyEndUserSpend_mcp_namespaced_tool_name_idx", "mcp_namespaced_tool_name"),
        Index("LiteLLM_DailyEndUserSpend_endpoint_idx", "endpoint"),
        Index("LiteLLM_DailyEndUserSpend_end_user_id_date_api_key_model_cu_key", "end_user_id", "date", "api_key", "model", "custom_llm_provider", "mcp_namespaced_tool_name", "endpoint", unique=True),
    )
    id = mapped_column(String, primary_key=True)
    end_user_id = mapped_column(String, nullable=True)
    date = mapped_column(String, nullable=False)
    api_key = mapped_column(String, nullable=False)
    model = mapped_column(String, nullable=True)
    model_group = mapped_column(String, nullable=True)
    custom_llm_provider = mapped_column(String, nullable=True)
    mcp_namespaced_tool_name = mapped_column(String, nullable=True)
    endpoint = mapped_column(String, nullable=True)
    prompt_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    completion_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_read_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_creation_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    api_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    successful_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    failed_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_DailyAgentSpend(Base):
    __tablename__ = "LiteLLM_DailyAgentSpend"
    __table_args__ = (
        Index("LiteLLM_DailyAgentSpend_date_idx", "date"),
        Index("LiteLLM_DailyAgentSpend_agent_id_idx", "agent_id"),
        Index("LiteLLM_DailyAgentSpend_api_key_idx", "api_key"),
        Index("LiteLLM_DailyAgentSpend_model_idx", "model"),
        Index("LiteLLM_DailyAgentSpend_mcp_namespaced_tool_name_idx", "mcp_namespaced_tool_name"),
        Index("LiteLLM_DailyAgentSpend_endpoint_idx", "endpoint"),
        Index("LiteLLM_DailyAgentSpend_agent_id_date_api_key_model_custom__key", "agent_id", "date", "api_key", "model", "custom_llm_provider", "mcp_namespaced_tool_name", "endpoint", unique=True),
    )
    id = mapped_column(String, primary_key=True)
    agent_id = mapped_column(String, nullable=True)
    date = mapped_column(String, nullable=False)
    api_key = mapped_column(String, nullable=False)
    model = mapped_column(String, nullable=True)
    model_group = mapped_column(String, nullable=True)
    custom_llm_provider = mapped_column(String, nullable=True)
    mcp_namespaced_tool_name = mapped_column(String, nullable=True)
    endpoint = mapped_column(String, nullable=True)
    prompt_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    completion_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_read_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_creation_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    api_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    successful_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    failed_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_DailyTeamSpend(Base):
    __tablename__ = "LiteLLM_DailyTeamSpend"
    __table_args__ = (
        Index("LiteLLM_DailyTeamSpend_date_idx", "date"),
        Index("LiteLLM_DailyTeamSpend_team_id_idx", "team_id"),
        Index("LiteLLM_DailyTeamSpend_api_key_idx", "api_key"),
        Index("LiteLLM_DailyTeamSpend_model_idx", "model"),
        Index("LiteLLM_DailyTeamSpend_mcp_namespaced_tool_name_idx", "mcp_namespaced_tool_name"),
        Index("LiteLLM_DailyTeamSpend_endpoint_idx", "endpoint"),
        Index("LiteLLM_DailyTeamSpend_team_id_date_api_key_model_custom_ll_key", "team_id", "date", "api_key", "model", "custom_llm_provider", "mcp_namespaced_tool_name", "endpoint", unique=True),
    )
    id = mapped_column(String, primary_key=True)
    team_id = mapped_column(String, nullable=True)
    date = mapped_column(String, nullable=False)
    api_key = mapped_column(String, nullable=False)
    model = mapped_column(String, nullable=True)
    model_group = mapped_column(String, nullable=True)
    custom_llm_provider = mapped_column(String, nullable=True)
    mcp_namespaced_tool_name = mapped_column(String, nullable=True)
    endpoint = mapped_column(String, nullable=True)
    prompt_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    completion_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_read_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_creation_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    api_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    successful_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    failed_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_DailyTagSpend(Base):
    __tablename__ = "LiteLLM_DailyTagSpend"
    __table_args__ = (
        Index("LiteLLM_DailyTagSpend_date_idx", "date"),
        Index("LiteLLM_DailyTagSpend_tag_idx", "tag"),
        Index("LiteLLM_DailyTagSpend_api_key_idx", "api_key"),
        Index("LiteLLM_DailyTagSpend_model_idx", "model"),
        Index("LiteLLM_DailyTagSpend_mcp_namespaced_tool_name_idx", "mcp_namespaced_tool_name"),
        Index("LiteLLM_DailyTagSpend_endpoint_idx", "endpoint"),
        Index("LiteLLM_DailyTagSpend_tag_date_api_key_model_custom_llm_pro_key", "tag", "date", "api_key", "model", "custom_llm_provider", "mcp_namespaced_tool_name", "endpoint", unique=True),
    )
    id = mapped_column(String, primary_key=True)
    request_id = mapped_column(String, nullable=True)
    tag = mapped_column(String, nullable=True)
    date = mapped_column(String, nullable=False)
    api_key = mapped_column(String, nullable=False)
    model = mapped_column(String, nullable=True)
    model_group = mapped_column(String, nullable=True)
    custom_llm_provider = mapped_column(String, nullable=True)
    mcp_namespaced_tool_name = mapped_column(String, nullable=True)
    endpoint = mapped_column(String, nullable=True)
    prompt_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    completion_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_read_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cache_creation_input_tokens = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    spend = mapped_column(Float, nullable=False, server_default=text("0.0"))
    api_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    successful_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    failed_requests = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_CronJob(Base):
    __tablename__ = "LiteLLM_CronJob"
    cronjob_id = mapped_column(String, primary_key=True)
    pod_id = mapped_column(String, nullable=False)
    status = mapped_column(Enum(JobStatus, name="JobStatus"), nullable=False, server_default=text("'INACTIVE'"))
    last_updated = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    ttl = mapped_column(DateTime, nullable=False)


class LiteLLM_ManagedFileTable(Base):
    __tablename__ = "LiteLLM_ManagedFileTable"
    __table_args__ = (
        Index("LiteLLM_ManagedFileTable_unified_file_id_idx", "unified_file_id"),
    )
    id = mapped_column(String, primary_key=True)
    unified_file_id = mapped_column(String, unique=True, nullable=False)
    file_object = mapped_column(JSON, nullable=True)
    model_mappings = mapped_column(JSON, nullable=False)
    flat_model_file_ids = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    storage_backend = mapped_column(String, nullable=True)
    storage_url = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=True)
    updated_at = mapped_column(DateTime, nullable=False)
    updated_by = mapped_column(String, nullable=True)


class LiteLLM_ManagedObjectTable(Base):
    __tablename__ = "LiteLLM_ManagedObjectTable"
    __table_args__ = (
        Index("LiteLLM_ManagedObjectTable_unified_object_id_idx", "unified_object_id"),
        Index("LiteLLM_ManagedObjectTable_model_object_id_idx", "model_object_id"),
    )
    id = mapped_column(String, primary_key=True)
    unified_object_id = mapped_column(String, unique=True, nullable=False)
    model_object_id = mapped_column(String, unique=True, nullable=False)
    file_object = mapped_column(JSON, nullable=False)
    file_purpose = mapped_column(String, nullable=False)
    status = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=True)
    updated_at = mapped_column(DateTime, nullable=False)
    updated_by = mapped_column(String, nullable=True)


class LiteLLM_ManagedVectorStoresTable(Base):
    __tablename__ = "LiteLLM_ManagedVectorStoresTable"
    __table_args__ = (
        Index("LiteLLM_ManagedVectorStoresTable_team_id_idx", "team_id"),
        Index("LiteLLM_ManagedVectorStoresTable_user_id_idx", "user_id"),
    )
    vector_store_id = mapped_column(String, primary_key=True)
    custom_llm_provider = mapped_column(String, nullable=False)
    vector_store_name = mapped_column(String, nullable=True)
    vector_store_description = mapped_column(String, nullable=True)
    vector_store_metadata = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)
    litellm_credential_name = mapped_column(String, nullable=True)
    litellm_params = mapped_column(JSON, nullable=True)
    team_id = mapped_column(String, nullable=True)
    user_id = mapped_column(String, nullable=True)


class LiteLLM_GuardrailsTable(Base):
    __tablename__ = "LiteLLM_GuardrailsTable"
    guardrail_id = mapped_column(String, primary_key=True)
    guardrail_name = mapped_column(String, unique=True, nullable=False)
    litellm_params = mapped_column(JSON, nullable=False)
    guardrail_info = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_PromptTable(Base):
    __tablename__ = "LiteLLM_PromptTable"
    __table_args__ = (
        Index("LiteLLM_PromptTable_prompt_id_idx", "prompt_id"),
        Index("LiteLLM_PromptTable_prompt_id_version_key", "prompt_id", "version", unique=True),
    )
    id = mapped_column(String, primary_key=True)
    prompt_id = mapped_column(String, nullable=False)
    version = mapped_column(Integer, nullable=False, server_default=text("1"))
    litellm_params = mapped_column(JSON, nullable=False)
    prompt_info = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_HealthCheckTable(Base):
    __tablename__ = "LiteLLM_HealthCheckTable"
    __table_args__ = (
        Index("LiteLLM_HealthCheckTable_model_name_idx", "model_name"),
        Index("LiteLLM_HealthCheckTable_checked_at_idx", "checked_at"),
        Index("LiteLLM_HealthCheckTable_status_idx", "status"),
    )
    health_check_id = mapped_column(String, primary_key=True)
    model_name = mapped_column(String, nullable=False)
    model_id = mapped_column(String, nullable=True)
    status = mapped_column(String, nullable=False)
    healthy_count = mapped_column(Integer, nullable=False, server_default=text("0"))
    unhealthy_count = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message = mapped_column(String, nullable=True)
    response_time_ms = mapped_column(Float, nullable=True)
    details = mapped_column(JSON, nullable=True)
    checked_by = mapped_column(String, nullable=True)
    checked_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_SearchToolsTable(Base):
    __tablename__ = "LiteLLM_SearchToolsTable"
    search_tool_id = mapped_column(String, primary_key=True)
    search_tool_name = mapped_column(String, unique=True, nullable=False)
    litellm_params = mapped_column(JSON, nullable=False)
    search_tool_info = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_SSOConfig(Base):
    __tablename__ = "LiteLLM_SSOConfig"
    id = mapped_column(String, primary_key=True, server_default=text("'sso_config'"))
    sso_settings = mapped_column(JSON, nullable=False)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_ManagedVectorStoreIndexTable(Base):
    __tablename__ = "LiteLLM_ManagedVectorStoreIndexTable"
    id = mapped_column(String, primary_key=True)
    index_name = mapped_column(String, unique=True, nullable=False)
    litellm_params = mapped_column(JSON, nullable=False)
    index_info = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=True)
    updated_at = mapped_column(DateTime, nullable=False)
    updated_by = mapped_column(String, nullable=True)


class LiteLLM_CacheConfig(Base):
    __tablename__ = "LiteLLM_CacheConfig"
    id = mapped_column(String, primary_key=True, server_default=text("'cache_config'"))
    cache_settings = mapped_column(JSON, nullable=False)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_UISettings(Base):
    __tablename__ = "LiteLLM_UISettings"
    id = mapped_column(String, primary_key=True, server_default=text("'ui_settings'"))
    ui_settings = mapped_column(JSON, nullable=False)
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, nullable=False)


class LiteLLM_SkillsTable(Base):
    __tablename__ = "LiteLLM_SkillsTable"
    skill_id = mapped_column(String, primary_key=True)
    display_title = mapped_column(String, nullable=True)
    description = mapped_column(String, nullable=True)
    instructions = mapped_column(String, nullable=True)
    source = mapped_column(String, nullable=False, server_default=text("'custom'"))
    latest_version = mapped_column(String, nullable=True)
    file_content = mapped_column(LargeBinary, nullable=True)
    file_name = mapped_column(String, nullable=True)
    file_type = mapped_column(String, nullable=True)
    metadata_json = mapped_column("metadata", JSON, nullable=True, server_default=text("'{}'"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=True)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=True)


class LiteLLM_PolicyTable(Base):
    __tablename__ = "LiteLLM_PolicyTable"
    policy_id = mapped_column(String, primary_key=True)
    policy_name = mapped_column(String, unique=True, nullable=False)
    inherit = mapped_column(String, nullable=True)
    description = mapped_column(String, nullable=True)
    guardrails_add = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    guardrails_remove = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    condition = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=True)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=True)


class LiteLLM_PolicyAttachmentTable(Base):
    __tablename__ = "LiteLLM_PolicyAttachmentTable"
    attachment_id = mapped_column(String, primary_key=True)
    policy_name = mapped_column(String, nullable=False)
    scope = mapped_column(String, nullable=True)
    teams = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    keys = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    models = mapped_column(ARRAY(String), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_by = mapped_column(String, nullable=True)
    updated_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String, nullable=True)


class LiteLLM_PredictTable(Base):
    __tablename__ = "LiteLLM_PredictTable"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id = mapped_column(
        String,
        ForeignKey("LiteLLM_UserTable.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    session_id = mapped_column(String, nullable=False)
    last_trace_id = mapped_column(String, nullable=False)

    predict = mapped_column(JSON, nullable=False)

    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


