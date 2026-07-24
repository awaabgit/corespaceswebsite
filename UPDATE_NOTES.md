# v4 — icon size, stale CSS, and the photo fix

## Why it looked broken
Two separate things, both now fixed.

### 1. Stale stylesheet (the giant icons / janky search bar / janky video)
The stylesheet was linked as a plain `/static/css/styles.css`, so browsers kept
serving the **cached old copy** alongside the new HTML. With the new markup but
the old CSS:
  * SVG icons had no size rule -> rendered at default size (huge)
  * the Buy/Rent slider and hero video had no positioning -> looked janky
  * the new filter dropdowns were unstyled -> looked missing

Fixed three ways so it cannot happen again:
  * CSS and JS are now served as `styles.css?v=<hash-of-file>` — the URL changes
    whenever the file changes, so a new copy is always fetched.
  * every icon carries `width`/`height` **on the SVG itself**, so size no longer
    depends on CSS loading at all.
  * a `max-width:18px` ceiling on icons inside buttons and spec rows.

If you ever still see a stale page: **Ctrl+Shift+R** forces a hard refresh.

### 2. Photos from the CRM not showing
Your Zoho photo field is named **`Image_Upload`**; the code was looking for
`Property_Photos`. It now reads `Image_Upload` (plus older names and
`Record_Image`) and handles every shape Zoho returns it in — list, single entry,
plain URL, or an entry carrying a direct file URL.

Empty photo field now shows a **branded CORE placeholder**, not grey "No photo".
Bedrooms / bathrooms / size are hidden when empty instead of printing "0".

## After deploying
1. Hard-refresh once (**Ctrl+Shift+R**).
2. Upload photos to a property in Zoho, tick Publish to Web, check the site.
3. If photos still don't load, open `/debug/zoho`, then try one image directly:
       https://corespaces.info/img/<record_id>/<file_id>
   Send me what that returns — Zoho moved this endpoint between API versions and
   the code tries v8, v7, v2 and attachments in order.

## Still open
* Host swap (Render free tier shows a wake-up page on cold start).
