# Zoho CRM — custom "Properties" module spec

This is the listings store inside Zoho CRM. Agents add a property here; the sync
script reads it and the website displays it. Create it in **Setup → Modules and
Fields → Create New Module** (or **New Custom Module**), name it **Properties**.

The **API Name** of each field (right-hand column) must match what
`app/zoho.py → _normalise()` expects. If you rename a field, update both places.

| Field label        | Type                         | API name        | Notes |
|--------------------|------------------------------|-----------------|-------|
| Title              | Single Line (default `Name`) | `Name`          | The listing headline |
| Slug               | Single Line                  | `Slug`          | URL-safe id, e.g. `marina-2br-sea-view`. Leave blank to auto-generate. |
| Listing Type       | Picklist (`sale`,`rent`)     | `Listing_Type`  | lowercase values |
| Price              | Number / Currency            | `Price`         | number only |
| Currency           | Picklist (`AED`,`USD`…)      | `Currency`      | defaults to AED |
| Bedrooms           | Number                       | `Bedrooms`      | use 0 for studio |
| Bathrooms          | Number                       | `Bathrooms`     | |
| Area (sqft)        | Number                       | `Area_Sqft`     | |
| Location           | Single Line                  | `Location`      | e.g. "Dubai Marina" |
| Community          | Single Line                  | `Community`     | e.g. "Marina Gate" |
| Status             | Picklist                     | `Status`        | `available` / `under_offer` / `sold` / `let` |
| Featured           | Checkbox                     | `Featured`      | shows on the homepage |
| Publish to Web     | Checkbox                     | `Publish_to_Web`| **only checked records appear on the site** |
| Description        | Multi Line                   | `Description`   | |
| Agent Name         | Single Line                  | `Agent_Name`    | or swap for a lookup to Users later |
| Agent Phone        | Phone                        | `Agent_Phone`   | |
| Photos             | (Attachments — built in)     | —               | agents upload photos as record attachments; sync re-hosts them |

## How photos work (important)
Agents upload photos the normal way — as **attachments on the record**. They do
**not** touch Supabase. The sync script downloads those attachments server-side
and re-hosts them to the public Supabase bucket, then the site serves those URLs.
This avoids Zoho's "attachments need auth to view" problem on a public site.

> Alternative if you'd rather skip attachments entirely: add a multi-line
> `Image_URLs` field and paste hosted URLs (one per line). `_normalise()` already
> reads `Image_URLs` if present and the sync step will skip re-hosting.

## Web Form (optional, lazy lead capture)
Zoho can generate a **Web Form** that drops submissions straight into Leads with
no code (**Setup → Developer Space → Web Forms → Leads**). The site already posts
inquiries to Leads via the API (`zoho.create_lead`), so the Web Form is only if
you'd rather embed Zoho's own form somewhere.
