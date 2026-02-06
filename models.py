from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from sqlalchemy import String, Integer, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from database import Base
from security import encrypt_string, decrypt_string
from datetime import datetime

# --- Database Models ---


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    api_server: Mapped[str] = mapped_column(String, index=True, nullable=False)
    domain: Mapped[str] = mapped_column(String, index=True, nullable=False)
    user: Mapped[str] = mapped_column(String, index=True, nullable=False)
    subscription_model: Mapped[str] = mapped_column(String, nullable=False)
    post_url: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # active, expired, archived
    status: Mapped[str] = mapped_column(
        String, default="active", server_default="active", index=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # pending, success, failed, archived
    maintenance_status: Mapped[str] = mapped_column(
        String, default="pending", server_default="pending", index=True
    )
    last_maintenance_attempt: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    maintenance_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "api_server",
            "domain",
            "user",
            "subscription_model",
            "post_url",
            name="_subscription_uc",
        ),
    )

    @property
    def source(self) -> str:
        return "db"


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    api_server: Mapped[str] = mapped_column(String, index=True, nullable=False)
    domain: Mapped[str] = mapped_column(String, index=True, nullable=False)
    user: Mapped[str] = mapped_column(String, index=True, nullable=False)

    _refresh_token: Mapped[str] = mapped_column("refresh_token", Text, nullable=False)
    _access_token: Mapped[Optional[str]] = mapped_column(
        "access_token", Text, nullable=True
    )

    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_refresh_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # pending, success, failed, archived
    maintenance_status: Mapped[str] = mapped_column(
        String, default="pending", server_default="pending", index=True
    )
    last_maintenance_attempt: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    maintenance_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("api_server", "domain", "user", name="_credential_uc"),
    )

    @property
    def refresh_token(self) -> str:
        return decrypt_string(self._refresh_token) if self._refresh_token else ""

    @refresh_token.setter
    def refresh_token(self, value: str):
        self._refresh_token = encrypt_string(value) if value else ""

    @property
    def access_token(self) -> str:
        return decrypt_string(self._access_token) if self._access_token else ""

    @access_token.setter
    def access_token(self, value: str):
        self._access_token = encrypt_string(value) if value else ""


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    api_server: Mapped[str] = mapped_column(String, index=True, nullable=False)
    domain: Mapped[str] = mapped_column(String, index=True, nullable=False)
    user: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)

    # create, update, delete, refresh, renew, archive
    action: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # subscription, credential
    resource_type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    resource_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --- API Models ---


class NSUser(BaseModel):
    user: str = Field(..., alias="user")
    domain: str
    name_first_name: Optional[str] = Field(None, alias="name-first-name")
    name_last_name: Optional[str] = Field(None, alias="name-last-name")
    email: Optional[str] = Field(None, alias="email-address")
    department: Optional[str] = Field(None, alias="department")
    site: Optional[str] = Field(None, alias="site")
    status_message: Optional[str] = Field(None, alias="status-message")
    model_config = ConfigDict(populate_by_name=True)


class NSSubscription(BaseModel):

    id: Optional[str] = None

    user: str

    domain: str

    model: str

    post_url: str = Field(..., alias="post-url")

    description: Optional[str] = None

    expires: Optional[int] = None

    model_config = ConfigDict(populate_by_name=True)
