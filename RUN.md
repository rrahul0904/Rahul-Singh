# UMA — Run It (Simplified)

Short version of the commands you need. For the full story, see `LAUNCH.md`.

## 0. Clean up your old folder first

You had 5 copies of uma-backend and several zips. Delete them all and start fresh:

```bash
cd ~/Desktop
rm -rf unified_data_migration_accelerator
mkdir unified_data_migration_accelerator
cd unified_data_migration_accelerator
```

Put **only** the new `uma-platform.zip` from this turn into that folder, then:

```bash
unzip uma-platform.zip
cd uma-backend
```

## 1. One-time setup

```bash
# Copy the env template and give it a secret
cp .env.example .env
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env
```

Open `.env` in nano/VS Code and set at minimum:
- `SECRET_KEY` — already added by the command above
- `ANTHROPIC_API_KEY=sk-ant-...` — optional, only if you want AI features

Leave everything else blank for now.

## 2. Launch

```bash
docker compose up -d --build
```

First build: 3–5 minutes.

If you're on a corporate network and Docker fails downloading Microsoft ODBC packages (the SSL cert error from earlier), the Dockerfile in this release has already been simplified to skip that step. SQL Server + Synapse + DB2 + SAP HANA connectors are disabled; the other 27 connectors all work.

## 3. Verify

```bash
# Wait ~60 seconds after docker compose up, then:
curl http://localhost:8000/api/health
# Should return: {"status":"ok", ...}
```

## 4. Create the first admin user

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@uma.local",
    "name": "Admin",
    "password": "Admin123!Secure"
  }'
```

Password requirements: 12+ chars, upper, lower, digit, special. `Admin123!Secure` works.

## 5. Open the app

Go to **http://localhost:5173** and sign in with:
- Email: `admin@uma.local`
- Password: `Admin123!Secure`

You'll land on the dashboard. In the top-right you'll see:
- Theme toggle (☀ / ☾) — click to switch between dark and light mode
- Your email + role badge (ADMIN in purple)
- Logout button

## 6. Try the fixed flows

### Add a Snowflake connection
1. **Connections** → **+ New Connection**
2. Pick `Snowflake`
3. Fill in account identifier, username, password, etc.
4. Click **Test Connection** — should show success with account/warehouse/role OR an actionable diagnostic error
5. Click **Create Connection**

### Edit a connection (new)
1. **Connections** page → click **Edit** next to any connection
2. Change fields as needed. Leave credential fields blank to keep existing values.
3. **Save Changes**

### Add a user (new)
1. **Admin → Users** in the sidebar (only visible if you're admin)
2. **+ Add User**
3. Fill in email, name, password, role
4. **Create User**

### Switch to light mode
Click the ☀ icon in the top-right. Click ☾ to go back to dark.

## 7. Common commands

```bash
docker compose logs -f uma-api      # watch backend logs
docker compose logs -f frontend     # watch frontend logs
docker compose ps                   # check status
docker compose stop                 # pause
docker compose start                # resume
docker compose down -v              # nuke everything (data gone)
docker compose up -d --build        # rebuild after code changes
```

## 8. Troubleshooting

**"Port 8000 in use"** → `lsof -i :8000` to find what's using it

**"401 Unauthorized" everywhere** → JWT expired (24h lifetime). Log in again.

**"Authentication required" + "Connection successful" shown together** → You're on the old version. Make sure you downloaded this release's zip, not the old one.

**Tables / Users / other pages 404** → Rebuild: `docker compose up -d --build`

**Database is stale after schema changes** →
```bash
docker compose down -v    # destroys data!
docker compose up -d
# then re-register your admin user
```

## 9. What's different in this build

- Connection **Test** button now actually tests (calls real backend endpoint)
- No more "Authentication required" + "Connection successful" at the same time
- Connection **Edit** button added
- **Users** page added (admin-only)
- Tables moved from Platform to Data in the sidebar
- Dark / **Light** mode toggle in topbar
- Your **role badge** is visible in the topbar
- Snowflake connection errors include **diagnostic hints** (e.g. "Check account identifier format")

See `CHANGES.md` for the full list.
