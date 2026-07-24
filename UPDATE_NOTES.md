# CORE Spaces site — update

## YOUR MODULE'S API NAME IS `CustomModule7`
Confirmed from the Zoho URL. Either:
  * set `ZOHO_PROPERTIES_MODULE=CustomModule7` in Render's Environment, **or**
  * just deploy this build — it finds the module by itself (below).

## THE FIX FOR "properties not showing"
Renaming a module in Zoho changes its **label**, not its **API name**. A module
displayed as "Properties" can still be `Properties_New` or `CustomModule7`, so
the site was asking Zoho for a module that doesn't exist.

The site now **finds the module itself**: it asks Zoho for the module list and
matches on label or API name, caching the result for an hour. Nothing to
configure — a renamed module keeps working.

### If listings still don't appear, open this first:
    https://<your-site>/debug/zoho
It tells you in plain terms:
  * which modules Zoho can see (with their real API names)
  * which one it resolved to
  * how many records came back, and how many are published
  * the exact field names on the first record
  * a hint about what's wrong
Send me that page's output and I can pinpoint it immediately.

## Also in this update
* **Mobile responsive pass** — search/filters stack properly on phones, no
  sideways scrolling, bigger tap targets, header and hero scale down.
* **Bigger CORE Spaces title**, sized in proportion with the logo.
* **More filters** (Property Finder style): beds, baths, min size (sqft),
  min price, max price, status (Ready / Off Plan / Available).
* **Favicon** — proper .ico + PNG + Apple touch icon, generated from the logo.
* **Basic Google SEO** — canonical URLs, Open Graph + Twitter cards, RealEstateAgent
  structured data, `/robots.txt`, `/sitemap.xml` (includes every listing).
* **Share button** on each property — native share sheet on phones, copy-link on
  desktop.
* **Hero video — installed.** Your Higgsfield clip is in and playing.
  Compressed from 62 MB to 2.7 MB (1600px, silent, 15s loop) so the page still
  loads fast; a poster frame shows instantly while it starts. On phones, slow
  connections or data-saver it skips the video and uses the image slideshow.
  To swap it later, replace `app/static/hero/hero.mp4`.
* Number handling: commas tolerated, decimals kept (695.56 stays 695.56).

## Zoho status values (already set) — how they behave
    Available - Off Plan  -> Buy tab + "Off Plan" badge
    Available Ready       -> Buy tab
    For Rent - Available  -> RENT tab
    Under Offer           -> Buy tab
    Sold / Off Market     -> hidden from the site automatically

## FINISH checklist
- [ ] Push, then open `/debug/zoho` and confirm `resolved_module` + record count.
- [ ] Add a property, upload photos, tick Publish to Web -> check it appears.
- [ ] If the listing shows but photos don't: Zoho moved the image-download
      endpoint between API versions; the code tries v8, v7, v2 and attachments.
      Send me a record id and I'll fix it.
- [ ] Host swap (Render free tier shows a wake-up page) — planned separately.
