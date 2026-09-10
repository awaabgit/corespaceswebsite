#!/usr/bin/env python3
"""
One-shot: replace plain-text passcodes in kpi_users with scrypt hashes.

Nobody's password changes — only how it is stored. The login page accepts both
forms (app/kpi.py: verify_passcode), so the site keeps working before, during
and after this runs, and running it twice is harmless: already-hashed rows are
skipped.

Needs the SERVICE ROLE key, which bypasses RLS:

    KPI_SUPABASE_URL=https://xxxx.supabase.co \
    KPI_SUPABASE_KEY=<service-role-key> \
    python3 scripts/hash_kpi_passwords.py            # dry run, shows the plan
    ... --apply                                      # actually write

Once every row is hashed the passwords are no longer recoverable from the
table — so make sure they are recorded somewhere first.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import kpi  # noqa: E402


def main() -> int:
    apply = "--apply" in sys.argv
    if not kpi.enabled():
        print("No Supabase credentials. Set KPI_SUPABASE_URL and KPI_SUPABASE_KEY "
              "(service role key).")
        return 1

    client = kpi._get_client()
    rows = client.table("kpi_users").select("name,passcode").execute().data or []
    if not rows:
        print("kpi_users is empty — nothing to do.")
        return 0

    todo = [r for r in rows if not str(r.get("passcode") or "").startswith("scrypt$")]
    done = len(rows) - len(todo)
    print(f"{len(rows)} rows: {done} already hashed, {len(todo)} to hash.")
    if not todo:
        return 0

    for r in todo:
        name = r["name"]
        if not apply:
            print(f"  would hash: {name}")
            continue
        client.table("kpi_users").update(
            {"passcode": kpi.hash_passcode(str(r["passcode"]))}
        ).eq("name", name).execute()
        print(f"  hashed: {name}")

    if not apply:
        print("\nDry run. Re-run with --apply to write the changes.")
    else:
        print(f"\nDone — {len(todo)} row(s) hashed. Log in once to confirm, "
              "then the plain-text copies are gone for good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
