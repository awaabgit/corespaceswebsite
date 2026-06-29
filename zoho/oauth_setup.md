# Zoho OAuth — getting a refresh token (one-time, FINISH phase)

You do this once. It produces a long-lived **refresh token** that the app uses to
mint short-lived access tokens automatically. ~10 minutes.

> Pick the right data centre. UAE accounts are usually **.com**. If the company's
> Zoho lives on another DC, swap the hosts in `.env`:
> | DC | Accounts host | API host |
> |----|----|----|
> | .com | https://accounts.zoho.com | https://www.zohoapis.com |
> | .eu  | https://accounts.zoho.eu  | https://www.zohoapis.eu |
> | .in  | https://accounts.zoho.in  | https://www.zohoapis.in |
> | .sa  | https://accounts.zoho.sa  | https://www.zohoapis.sa |

## 1. Register a Self-Client
1. Go to **https://api-console.zoho.com** → **Add Client** → **Self Client** → Create.
2. Note the **Client ID** and **Client Secret** → put them in `.env`.

## 2. Generate a grant code
1. In the Self Client, open the **Generate Code** tab.
2. Scope (read listings + create leads + read attachments):
   ```
   ZohoCRM.modules.ALL,ZohoCRM.settings.ALL
   ```
3. Time duration: 10 minutes. Description: anything. **Create** → copy the **grant code**.

## 3. Exchange grant code for a refresh token
Run this once (replace the three values). The grant code expires fast, so be quick:
```bash
curl -s "https://accounts.zoho.com/oauth/v2/token" \
  -d grant_type=authorization_code \
  -d client_id=YOUR_CLIENT_ID \
  -d client_secret=YOUR_CLIENT_SECRET \
  -d code=YOUR_GRANT_CODE
```
The JSON response includes a **`refresh_token`**. Copy it into `.env` as
`ZOHO_REFRESH_TOKEN`. (The access_token in that same response expires in 1h —
ignore it, the app refreshes on its own.)

## 4. Verify
```bash
python scripts/sync_zoho_to_supabase.py
```
You should see it fetch your published Properties. Done.
