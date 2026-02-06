from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, Literal
from datetime import datetime
import ipaddress
from urllib.parse import urlparse


class SubscriptionBase(BaseModel):
    user: str = Field(..., description="Target user extension or '*' for all")
    subscription_model: str = Field(..., description="Event type")
    post_url: str = Field(..., description="Destination URL")
    description: Optional[str] = Field(None, description="Friendly note")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")

    @field_validator("post_url")
    @classmethod
    def validate_post_url(cls, v: str) -> str:
        # Basic SSRF prevention for destination URLs
        try:
            parsed = urlparse(v)
            if not parsed.scheme or parsed.scheme not in ["http", "https"]:
                raise ValueError("URL must be http or https")

            hostname = parsed.hostname
            if not hostname:
                raise ValueError("Invalid URL: missing hostname")

            ip = None
            try:
                clean_host = hostname.strip("[]")
                ip = ipaddress.ip_address(clean_host)
            except ValueError:
                pass

            if ip:
                if ip.is_loopback or ip.is_private:
                    raise ValueError(
                        "Destination cannot be a local or private network address"
                    )
            else:
                if hostname in ["localhost", "127.0.0.1"]:
                    raise ValueError("Destination cannot be localhost")

        except ValueError as e:
            raise e
        except Exception as e:
            raise ValueError(f"Invalid URL: {str(e)}")
        return v


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionUpdate(BaseModel):
    description: Optional[str] = None
    expires_at: Optional[datetime] = None
    post_url: Optional[str] = None

    @field_validator("post_url")
    @classmethod
    def validate_post_url(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return SubscriptionBase.validate_post_url(v)
        return v


class SubscriptionResponse(SubscriptionBase):
    id: Optional[int] = None
    api_server: Optional[str] = None
    domain: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    source: Literal["db", "pbx"] = "db"

    # Maintenance Tracking
    maintenance_status: Optional[str] = None
    last_maintenance_attempt: Optional[datetime] = None
    maintenance_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
