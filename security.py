import logging
import fnmatch
from typing import Optional
from urllib.parse import urlparse
from cryptography.fernet import Fernet
from config import settings

logger = logging.getLogger(__name__)


def is_origin_allowed(origin: Optional[str], allowed_origins: str) -> bool:

    # Checks if origin matches any allowed patterns (supports wildcards)

    if not origin or not allowed_origins:

        return False

    def get_hostname(u: str) -> Optional[str]:

        try:

            if not u.startswith(("http://", "https://")):

                u = "https://" + u

            parsed = urlparse(u)

            return parsed.hostname

        except Exception:

            return None

    target_hostname = get_hostname(origin)

    if not target_hostname:

        return False

    target_hostname = target_hostname.lower()

    patterns = []

    for p in allowed_origins.split(","):

        p = p.strip()

        if not p:

            continue

        h = get_hostname(p)

        patterns.append(h.lower() if h else p.lower())

    for pattern in patterns:

        if fnmatch.fnmatch(target_hostname, pattern):

            return True

    return False


def encrypt_string(data: str) -> str:

    # Encrypts string using ENCRYPTION_KEY

    if not data:

        return ""

    f = Fernet(settings.ENCRYPTION_KEY.encode())

    return f.encrypt(data.encode()).decode()


def decrypt_string(encrypted_data: str) -> str:

    # Decrypts string using ENCRYPTION_KEY

    if not encrypted_data:

        return ""

    f = Fernet(settings.ENCRYPTION_KEY.encode())

    return f.decrypt(encrypted_data.encode()).decode()
