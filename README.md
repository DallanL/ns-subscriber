# Netsapiens Subscription Registry Addon

A production-grade, portal-integrated interface for managing event subscriptions and OAuth tokens within the Netsapiens PBX ecosystem. Designed for solo operators and small teams, it emphasizes security, auditability, and ease of deployment.

## Features

- **Portal Integration:** Adds a seamless "Subscriptions" tab to the Netsapiens User Portal (v44+).
- **Lifecycle Management:** Create, view, update, and archive subscription records.
- **Background Maintenance:** Automated service that:
  - Refreshes OAuth tokens to ensure persistent API access.
  - Renews subscription expirations on the PBX.
  - Archives records when users are deleted from the PBX.
- **Security First:**
  - **Strict API Lockdown:** Hardcoded to a specific PBX API server to prevent SSRF.
  - **Origin Whitelisting:** Enforces strict origin checks for all incoming requests.
  - **Encrypted Storage:** All tokens are envelope-encrypted at rest using Fernet.
  - **Audit Logging:** Every action (user or system) is recorded in an immutable audit log.

---

## Prerequisites

- **Docker & Docker Compose**
- **Netsapiens PBX (v44 or later)**
- A valid **Client ID** and **Client Secret** for the PBX (Authorization Code grant type).
- **NS-OAuth2-UI-Controller:** This addon requires the [NS-OAuth2-UI-Controller](https://github.com/DallanL/NS-OAuth2-UI-Controller) to be installed on your Netsapiens portal to handle the frontend OAuth2 authorization flow.
- A domain name for this application (e.g., `app.yourdomain.com`) with SSL termination (Traefik is included, but Nginx/Caddy works too).

---

## Installation (Docker Compose)

### 1. Clone & Prepare
```bash
git clone <your-repo-url> ns-subscriber
cd ns-subscriber
cp .env.example .env
```

### 2. Configuration
Edit `.env` with your specific details. This is the most critical step.

```ini
# --- Network & Domain ---
# The public URL where this app is reachable (used by the browser)
PUBLIC_API_URL=https://app.yourdomain.com

# Used by Traefik labels
SERVICE_DOMAIN=app.yourdomain.com
DOCKER_NETWORK=proxy_public  # Ensure this network exists or create it

# --- Security ---
# Generate a secure key: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
ENCRYPTION_KEY=your_generated_fernet_key

# Strict Whitelist: Only allow requests from your Portal URL
ALLOWED_ORIGINS=https://portal.yourpbx.com,*.yourpbx.com

# --- Netsapiens Connection ---
NS_CLIENT_ID=your_client_id
NS_CLIENT_SECRET=your_client_secret
# The authoritative API server. This app will ONLY connect to this server.
NS_API_URL=https://api.yourpbx.com/ns-api/v2

# --- Database ---
POSTGRES_USER=ns_user
POSTGRES_PASSWORD=secure_db_password
POSTGRES_DB=ns_subscriber
DATABASE_URL=postgresql+asyncpg://ns_user:secure_db_password@db:5432/ns_subscriber
```

### 3. Start Services
```bash
# Create the network if using an external proxy network
docker network create proxy_public

# Start the stack
docker compose up -d --build
```

### 4. Verify
Check the logs to ensure the application started successfully and connected to the database.
```bash
docker compose logs -f ns-app
```

---

## Netsapiens Portal Integration

To make the "Subscriptions" tab appear in your PBX portal, you must inject the JavaScript loader. **Note:** This registry works in tandem with the [NS-OAuth2-UI-Controller](https://github.com/DallanL/NS-OAuth2-UI-Controller). Ensure that is installed and configured first.

1.  **Locate your script URL:**
    `https://app.yourdomain.com/portal-script.js`

2.  **Update Portal Config:**
    Log in to your Netsapiens Superuser portal. Navigate to **System** -> **Configuration** (or similar based on version).

    Find or create the setting **`PORTAL_EXTRA_JS`**.

    Add your script URL to the list. If there are existing scripts, separate them appropriately (often newline or comma, check your specific portal version docs).

    **Example (Loader Script approach):**
    ```javascript
    (function() {
        var s = document.createElement('script');
        s.type = 'text/javascript';
        s.async = true;
        s.src = 'https://app.yourdomain.com/portal-script.js';
        var x = document.getElementsByTagName('script')[0];
        x.parentNode.insertBefore(s, x);
    })();
    ```

3.  **CSP (Content Security Policy):**
    If your portal enforces CSP, you must whitelist your app domain in **`PORTAL_CSP_CONNECT_ADDITIONS`** and **`PORTAL_CSP_SCRIPT_ADDITIONS`**.

---

## Usage

**NOTE**: I recommend you only create and manage subscriptions when masq'd as an office manager user as subscription ownership and visibility can be very unintuitive, and you will need the actual portal username and password of that user the first time you create a subscription.

1.  **Log in to the Portal:** Log in as a User or Office Manager.
2.  **Navigate:** Go to the **Phone Numbers** (or Inventory) tab.
3.  **Subscriptions Tab:** You should see a new tab labeled **Subscriptions**.
4.  **Connect Account:** On first use, or when adding a subscription, you will be prompted to "Connect your account". This performs the OAuth handshake to allow the background service to manage tokens on your behalf.
5.  **Manage:** Use the UI to Add, Edit, or Archive subscriptions.

---

## Maintenance & Troubleshooting

### Logs
View application logs:
```bash
docker compose logs -f --tail=100 ns-app
```
View background maintenance logs:
```bash
docker compose logs -f --tail=100 maintenance
```

### Database Backups
The database is a standard PostgreSQL container. Backup the volume or use `pg_dump`:
```bash
docker exec ns-subscriber-db pg_dump -U ns_user ns_subscriber > backup.sql
```

### Common Issues
-   **"Origin not allowed" (403):** Check `ALLOWED_ORIGINS` in `.env`. It must match the URL of the portal you are logging into (check the browser's console for the `Origin` header).
-   **"NS_API_URL is not configured":** The app will crash on startup if `NS_API_URL` is missing. Ensure it is set in `.env`.
-   **Token Refresh Failures:** Check the `maintenance` container logs. Ensure the Client ID/Secret are correct and have `offline_access` scope if required by your PBX version.

### License
[MIT](LICENSE)
