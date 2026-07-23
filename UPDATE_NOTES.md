# Update — new Properties module + photo uploads

## What changed
1. **Agents upload photos in Zoho; the website shows them.**
   Uploaded files sit behind Zoho auth, so the site now fetches them
   server-side with its token and streams them out via `/img/<record>/<file>`.
   Cached 24h in the browser + in memory, so Zoho isn't hit on every view.
2. **Buy/Rent now comes from `Status`** (the module no longer has a Listing Type
   field). Anything with "rent" in the status = rent, everything else = sale.
3. **`Agent Contact`** (one field) is split automatically into name + phone.
4. Old **`Image URLs`** text field still works as a fallback if it's ever re-added.

## Zoho — Status values (already set)
    Available - Off Plan   -> shows on site, Buy tab, "Off Plan" badge
    Available Ready        -> shows on site, Buy tab
    For Rent - Available   -> shows on site, RENT tab
    Under Offer            -> shows on site, Buy tab
    Sold                   -> HIDDEN from site automatically
    Off Market             -> HIDDEN from site automatically

Rules the code follows:
  * the word "rent" in the status puts a listing on the Rent tab
  * "off plan" in the status adds an "Off Plan" badge to the card
  * Sold / Off Market are hidden even if "Publish to Web" is still ticked

## Render — nothing to change
`ZOHO_PROPERTIES_MODULE` is already `Properties`, which now points at the
renamed module. The three Zoho keys are unchanged.

## FINISH checklist (live, together)
- [ ] Add a property in Zoho, upload 2 photos, tick **Publish to Web**, Save.
- [ ] Open the site → the listing appears with its photos.
- [ ] If photos are broken but the listing shows: the image-download endpoint
      needs one tweak — send me the record id + what `/img/<id>/<file>` returns.
      (Zoho moved this endpoint between API versions; the code tries v8, v7, v2
      and the attachments path in order.)
- [ ] Check a rent listing shows under the Rent tab.
