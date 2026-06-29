# Realty site — Zoho CRM + FastAPI

Company display website (FastAPI + Jinja2) for a Dubai real estate company, wired
to **Zoho CRM** as the source of truth and **Supabase** as the fast read cache +
image bucket + leads log.

The loop: **agent adds a listing in Zoho → sync caches it to Supabase → site shows it
→ visitor enquires → lead lands back in Zoho.**

> Built per the one-shot rule: everything that can be built without live keys is
> built and **route-tested standalone**. The live-keys work is the FINISH checklist
> at the bottom.

---

## Runs right now (no credentials)

```bash
./run.sh
# or:  pip install -r requirements.txt  &&  uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 — it serves **6 sample listings** in MOCK mode so you can
see the whole site working before any Zoho/Supabase setup. `GET /health` shows the
current mode.

### Three modes, picked automatically from `.env` (zero code changes)
| Mode | When | Data source |
|------|------|-------------|
| **mock** | no creds (default) | `app/mock_data.py` |
| **supabase** | `SUPABASE_*` set | cached listings (production read path) |
| **zoho-direct** | only `ZOHO_*` set | live Zoho (testing only — rate-limited) |

Production = the cron fills Supabase, the site reads Supabase.

---

## What's in here
```
app/
  main.py              FastAPI app + routes
  config.py            env-driven settings + mode detection
  data.py              single data layer (routes mock / supabase / zoho)
  zoho.py              Zoho OAuth + fetch Properties + create Lead
  supabase_client.py   read listings, log leads, upload images
  mock_data.py         sample listings (standalone mode)
  templates/           Jinja2 pages (home, listings, detail, about, contact, 404)
  static/css/styles.css  one stylesheet — REBRAND tokens at the very top
scripts/
  sync_zoho_to_supabase.py   the cron job (Zoho → Supabase + image re-host)
supabase/schema.sql          tables + storage bucket (run in Supabase SQL editor)
zoho/properties_module_schema.md   the custom module fields to build in Zoho
zoho/oauth_setup.md          step-by-step to get a Zoho refresh token
.env.example                 copy to .env in the FINISH phase
```

---

## FINISH checklist (the hands-on part — do this together)

Mapped to the plan phases. None of it is code; it's config + keys + the investor's
real content.

### P1 — Zoho CRM
- [ ] Build the custom **Properties** module — fields in `zoho/properties_module_schema.md`.
- [ ] Add the **Publish to Web** checkbox (only checked records go public) + **Featured**.
- [ ] Confirm Leads module is on (it is by default) for inquiry capture.
- [ ] Add the company's agents as users; set roles.
- [ ] (Optional) generate a Zoho **Web Form** if you want their native lead form too.

### P1.5 — Zoho OAuth (the time sink — budget a session)
- [ ] Follow `zoho/oauth_setup.md` → get `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`.
- [ ] Confirm the data-centre hosts (UAE is usually `.com`).

### P2 — Supabase
- [ ] Create a Supabase project; run `supabase/schema.sql` in the SQL editor.
- [ ] Create the public **`listing-photos`** bucket (the SQL does this, or do it in the UI).
- [ ] Copy `SUPABASE_URL` + **service-role** key into `.env`.

### P3 — Wire it
- [ ] `cp .env.example .env` and fill everything in.
- [ ] Drop in the investor's real `COMPANY_*` values.
- [ ] Add a couple of real listings in Zoho (tick Publish to Web), upload photos.
- [ ] `python scripts/sync_zoho_to_supabase.py` → check Supabase fills + images re-host.
- [ ] Restart the site → real listings should now show (mode = supabase).
- [ ] Submit a test enquiry → confirm a Lead appears in Zoho.

### P4 — Go live
- [ ] Point the company domain at the VPS.
- [ ] Run behind Caddy (auto-HTTPS) → uvicorn/gunicorn (see deploy note below).
- [ ] Add the sync to cron (line is in `scripts/sync_zoho_to_supabase.py`).
- [ ] Replace placeholder About copy; check it on mobile.

---

## Deploy note (VPS — your usual pattern)
```bash
# on the VPS, in /srv/realty-zoho-site
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt gunicorn
./.venv/bin/gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000
```
Caddyfile (auto-HTTPS):
```
yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
```
Run gunicorn under systemd, add the sync cron line, done.

---

## Rebranding
Open `app/static/css/styles.css` — the top block is the full palette + fonts. Change
those tokens and the whole site re-skins. Company name/phone/etc. come from `.env`.

## Notes / deliberate choices
- Site reads **Supabase**, never Zoho live, so it's fast and never hits API limits.
- Agents upload photos **as Zoho attachments** (the natural action); the sync
  re-hosts them to Supabase so the public site can serve them without auth.
- Inquiry forms post to Zoho **Leads** via API, with an optional Supabase backup.
- Service-role Supabase key is **server-side only** — never expose it to the browser.
