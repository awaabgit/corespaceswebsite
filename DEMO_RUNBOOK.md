# CORE Spaces — go-live runbook (the parts only you can do)

Everything else is built. This is the ~30 min of clicking that needs your logins.
Order matters. Each tier is independently presentable.

---

## ⚡ TL;DR for the meeting
- **Tier 1 (guaranteed):** deploy to Render → live URL on clean sample listings.
- **Tier 2 (the wow):** add 3 Zoho keys → site flips to REAL Zoho data → add a
  listing in Zoho live → it appears on the site.

---

## A. Fix 2 Zoho fields first (~5 min)
In your Properties module (Setup → Modules → Properties → Edit Layout):
1. **Listing Type** — if it's still a *Decimal*, delete it and re-add as a
   **Pick List** with two values: `sale`, `rent`. (This is what the site filters on.)
2. Add a field **Image URLs** — type **Multi-Line**. (You'll paste photo links here.)
3. Confirm the **Publish to Web** checkbox exists. Save.

> The code auto-detects your field API names (Currency_Type, Area_sqft,
> publish_to_web, Listing_Type1, etc.) — you do **not** need to rename anything.

## B. Zoho OAuth → 3 keys (~10 min)
1. Go to **https://api-console.zoho.com** → **Add Client** → **Self Client** → Create.
   Copy the **Client ID** and **Client Secret**.
2. Open the **Generate Code** tab. Scope:
   ```
   ZohoCRM.modules.ALL,ZohoCRM.settings.ALL
   ```
   Duration 10 min → **Create** → copy the **grant code**.
3. Exchange it for a refresh token — paste this in a terminal (works in Windows
   CMD/PowerShell), filling in the three values. Do it quickly, the code expires:
   ```
   curl "https://accounts.zoho.com/oauth/v2/token" -d "grant_type=authorization_code" -d "client_id=YOUR_ID" -d "client_secret=YOUR_SECRET" -d "code=YOUR_GRANT_CODE"
   ```
   In the JSON reply, copy the **`refresh_token`**. You now have your 3 keys:
   `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`.

## C. Deploy to Render (~10 min)
**Get the code on GitHub** (easiest non-dev path):
- Install **GitHub Desktop** → sign in.
- **File → New repository** → set the local path to the unzipped `core-spaces-site`
  folder → Create → **Publish repository**.

**Deploy on Render:**
1. **https://render.com** → sign in → **New + → Blueprint**.
2. Connect the GitHub repo → Render reads `render.yaml` → **Apply**.
3. Wait for the build (~2–3 min). You get a public URL like
   `https://core-spaces-site.onrender.com`. **Tier 1 done — it's live on samples.**

**Flip it to live Zoho data:**
4. In Render → your service → **Environment** → add the three secrets from step B:
   `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN` → **Save**.
5. It auto-redeploys. Now the site reads Zoho live. **Tier 2 wired.**

> ⚠️ Render free tier **sleeps after 15 min idle** — first hit then takes ~40s.
> Open the URL a minute before you present so it's awake.

## D. The live demonstration (in the meeting)
1. In Zoho → **Properties → + New**. Fill Title, Listing Type (sale/rent), Price,
   Bedrooms, etc.
2. In **Image URLs**, paste 2–3 image links (one per line). Quick source: open a
   Bayut/Dubizzle listing, right-click a photo → **Copy image address** → paste.
   (If one doesn't show, the site just skips it — use another, or postimages.org.)
3. Tick **Publish to Web** → **Save**.
4. Refresh the Render URL → **the listing is there.** That's the money shot:
   *"Add it in Zoho, tick publish — it's on the website."*

---

## Notes
- Until the Zoho keys are set, the site shows polished **sample listings** (never blank).
- If a Zoho call ever fails, the site falls back to samples instead of erroring.
- This demo runs in **zoho-direct** mode (site reads Zoho live). For production we
  later add the Supabase cache + image hosting for speed — already built, just off for now.
