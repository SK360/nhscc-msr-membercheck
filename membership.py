import argparse
import os
import re
import sys
import requests
import json
from base64 import b64encode
from collections import defaultdict
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────
MSR_USERNAME    = os.getenv("MSR_USERNAME", "")
MSR_PASSWORD    = os.getenv("MSR_PASSWORD", "")
ORGANIZATION_ID = os.getenv("MSR_ORGANIZATION_ID", "")

if not all([MSR_USERNAME, MSR_PASSWORD, ORGANIZATION_ID]):
    print("Error: MSR_USERNAME, MSR_PASSWORD, and MSR_ORGANIZATION_ID must be set in your .env file.")
    sys.exit(1)

BASE_URL = "https://api.motorsportreg.com"

MEMBERSHIP_PACKAGES = {
    "Family Membership Renew with Single Event Fee",
    "Single Membership Renew and Event Fee",
}

# ─── Auth Headers ─────────────────────────────────────────────────────────────
def get_headers():
    credentials = b64encode(f"{MSR_USERNAME}:{MSR_PASSWORD}".encode()).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "X-Organization-Id": ORGANIZATION_ID,
        "Accept": "application/vnd.pukkasoft+json",
    }

# ─── API Helpers ──────────────────────────────────────────────────────────────
def get_2026_events():
    params = {
        "start":   "2026-01-01",
        "end":     "2026-12-31",
        "archive": "true",
    }
    url = f"{BASE_URL}/rest/calendars/organization/{ORGANIZATION_ID}.json"
    r = requests.get(url, headers=get_headers(), params=params)
    r.raise_for_status()
    all_events = r.json()["response"]["events"]

    today = datetime.now(timezone.utc).date()
    past_events = [e for e in all_events if datetime.fromisoformat(e["start"]).date() < today]

    print(f"  ({len(all_events)} total events, {len(past_events)} already occurred)")
    return past_events

def get_attendees_with_packages(event_id):
    url = f"{BASE_URL}/rest/events/{event_id}/attendees.json"
    r = requests.get(url, headers=get_headers(), params={"fields": "packages"})
    r.raise_for_status()
    return r.json()["response"]["attendees"]

def get_member(member_id):
    url = f"{BASE_URL}/rest/members/{member_id}.json"
    r = requests.get(url, headers=get_headers())
    r.raise_for_status()
    return r.json()["response"]["member"]

def get_all_members(types_filter=None):
    url = f"{BASE_URL}/rest/members.json"
    params = {}
    if types_filter:
        params["types"] = types_filter
    r = requests.get(url, headers=get_headers(), params=params)
    r.raise_for_status()
    return r.json()["response"]["members"]

def get_member_types():
    url = f"{BASE_URL}/rest/members/types.json"
    r = requests.get(url, headers=get_headers())
    r.raise_for_status()
    response = r.json()["response"]
    # Find the types list regardless of key name
    for key, val in response.items():
        if isinstance(val, list):
            return val
    raise KeyError(f"No list found in response. Keys: {list(response.keys())}")

def parse_member_end(end_str):
    """Parse a memberEnd string in any of MSR's date formats. Returns a date or None."""
    if not end_str:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(end_str, fmt).date()
        except ValueError:
            continue
    return None

def fix_member(member_id, current_types, set_member_end=None):
    """Remove Non-Member, add Member, and optionally set memberEnd."""
    updated_types = [t for t in current_types if t != "Non-Member"]
    if "Member" not in updated_types:
        updated_types.append("Member")

    payload = {"types": updated_types}
    if set_member_end:
        payload["memberEnd"] = set_member_end

    url = f"{BASE_URL}/rest/members/{member_id}.json"
    headers = get_headers()
    headers["Content-Type"] = "application/json"
    r = requests.put(url, headers=headers, json=payload)
    r.raise_for_status()
    return updated_types

# ─── Shared: scan events for renewal purchasers ───────────────────────────────
def get_renewal_purchasers():
    print("Fetching 2026 events...")
    events = get_2026_events()

    if not events:
        print("No past events found for 2026.")
        return {}

    print(f"Scanning {len(events)} past event(s).\n")

    purchasers = {}
    for event in events:
        event_id   = event["id"]
        event_name = event["name"]
        event_date = event.get("start", "")[:10]
        print(f"  → Scanning {event_name} ({event_date})...")

        try:
            attendees = get_attendees_with_packages(event_id)
        except requests.HTTPError as e:
            print(f"     ⚠ Could not fetch attendees: {e}")
            continue

        for attendee in attendees:
            packages = attendee.get("packages", [])
            bought_membership = any(
                pkg.get("name", "") in MEMBERSHIP_PACKAGES
                for pkg in packages
            )
            if not bought_membership:
                continue

            member_uri = attendee.get("memberuri", "")
            if not member_uri:
                continue
            member_id = member_uri.split("/members/")[-1]

            if member_id not in purchasers:
                purchasers[member_id] = {
                    "member_id":  member_id,
                    "name":       f"{attendee.get('firstName', '')} {attendee.get('lastName', '')}".strip(),
                    "email":      attendee.get("email", ""),
                    "reg_status": attendee.get("status", ""),
                    "package":    next(
                                      pkg.get("name", "") for pkg in packages
                                      if pkg.get("name", "") in MEMBERSHIP_PACKAGES
                                  ),
                    "event_name": event_name,
                }

    print(f"\nFound {len(purchasers)} unique membership renewal purchaser(s).\n")
    return purchasers

# ─── --check-roles ────────────────────────────────────────────────────────────
def run_check_roles():
    membership_buyers = get_renewal_purchasers()
    if not membership_buyers:
        return

    current_year = datetime.now(timezone.utc).year
    expected_end = datetime(current_year, 12, 31).date()
    expected_end_str = f"12/31/{current_year}"

    results = []
    for member_id, buyer in membership_buyers.items():
        print(f"  Checking {buyer['name']} ({buyer['email']})...")
        try:
            member = get_member(member_id)
        except requests.HTTPError as e:
            print(f"    ⚠ Could not fetch member record: {e}")
            buyer["types"]       = "ERROR"
            buyer["has_member"]  = False
            buyer["end_date"]    = "ERROR"
            buyer["end_ok"]      = False
            results.append(buyer)
            continue

        raw_types  = member.get("types", [])
        type_names = [t if isinstance(t, str) else t.get("name", "") for t in raw_types]

        end_str  = member.get("memberEnd", "")
        end_date = parse_member_end(end_str)

        buyer["types"]      = ", ".join(type_names) if type_names else "(none)"
        buyer["has_member"] = any(t.lower() == "member" for t in type_names)
        buyer["raw_types"]  = type_names
        buyer["end_date"]   = str(end_date) if end_date else (end_str or "(none)")
        buyer["end_ok"]     = end_date == expected_end
        results.append(buyer)

    print(f"\n{'─'*100}")
    print(f"{'NAME':<25} {'EMAIL':<30} {'MEMBER':<10} {'END DATE':<14} {'TYPES'}")
    print(f"{'─'*100}")

    needs_update = []
    for r in sorted(results, key=lambda x: x["name"]):
        member_flag = "✓" if r["has_member"] else "✗"
        end_flag    = "✓" if r["end_ok"] else "✗"
        end_display = f"{end_flag} {r['end_date']}"
        print(f"{r['name'][:24]:<25} {r['email'][:29]:<30} {member_flag:<10} {end_display[:13]:<14} {r['types']}")
        if not r["has_member"] or not r["end_ok"]:
            needs_update.append(r)

    print(f"\n{'─'*100}")
    print(f"Total renewal purchasers:  {len(results)}")
    print(f"Missing Member role:       {sum(1 for r in results if not r['has_member'])}")
    print(f"Wrong/missing end date:    {sum(1 for r in results if not r['end_ok'])}")
    print(f"Need any fix:              {len(needs_update)}")

    if needs_update:
        print(f"\nPeople who need fixes (target end date: {expected_end_str}):")
        for r in needs_update:
            issues = []
            if not r["has_member"]:
                issues.append("role")
            if not r["end_ok"]:
                issues.append(f"end date ({r['end_date']})")
            print(f"  • {r['name']} ({r['email']}) — needs: {', '.join(issues)}")

        print()
        answer = input("Fix these members now? (yes/no): ").strip().lower()
        if answer == "yes":
            print()
            for r in needs_update:
                print(f"  Fixing {r['name']}...", end=" ")
                try:
                    set_end = expected_end_str if not r["end_ok"] else None
                    new_types = fix_member(r["member_id"], r["raw_types"], set_member_end=set_end)
                    msg = f"types now: {', '.join(new_types)}"
                    if set_end:
                        msg += f"; end date set to {set_end}"
                    print(f"✓ {msg}")
                except requests.HTTPError as e:
                    print(f"✗ FAILED: {e}")
            print("\nDone.")
        else:
            print("No changes made.")
    else:
        print("\nEveryone looks good — no fixes needed.")

    output_file = "msr_membership_role_check.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Full results saved to {output_file}")

# ─── --expired-members ────────────────────────────────────────────────────────
def run_expired_members():
    print("Fetching all current Member-typed accounts...")
    try:
        current_members = get_all_members(types_filter="Member")
    except requests.HTTPError as e:
        print(f"⚠ Could not fetch member list: {e}")
        return
    print(f"  ({len(current_members)} accounts with Member type)")
    print(f"  Fetching individual records for memberEnd dates...\n")

    today = datetime.now(timezone.utc).date()
    expired = []
    for i, m in enumerate(current_members, 1):
        member_id = m.get("id", "")
        name = f"{m.get('firstName','')} {m.get('lastName','')}".strip()
        print(f"  [{i}/{len(current_members)}] {name}...", end=" ", flush=True)
        try:
            detail = get_member(member_id)
        except requests.HTTPError as e:
            print(f"⚠ skipped ({e})")
            continue

        end_str = detail.get("memberEnd", "")
        end_date = parse_member_end(end_str)

        if not end_date:
            print("no date" if not end_str else f"invalid date (raw: {end_str!r})")
            detail["_end_date"] = None
            expired.append(detail)
        elif end_date < today:
            print(f"expired {end_date}")
            detail["_end_date"] = end_date
            expired.append(detail)
        else:
            print(f"ok ({end_date})")

    expired.sort(key=lambda x: f"{x.get('lastName','')} {x.get('firstName','')}")

    print(f"{'─'*80}")
    print(f"{'NAME':<25} {'EMAIL':<30} {'MEMBER END':<14} {'MEMBER ID'}")
    print(f"{'─'*80}")

    for m in expired:
        name     = f"{m.get('firstName','')} {m.get('lastName','')}".strip()
        email    = m.get("email", "")
        end_date = str(m["_end_date"]) if m["_end_date"] else "(none)"
        mid      = m.get("id", "")
        print(f"{name[:24]:<25} {email[:29]:<30} {end_date:<14} {mid}")

    print(f"\n{'─'*80}")
    print(f"Current members:       {len(current_members)}")
    print(f"Expired or no date:    {len(expired)}")

    output_file = "msr_expired_members.json"
    with open(output_file, "w") as f:
        json.dump([{k: v for k, v in m.items() if k != "_end_date"} for m in expired], f, indent=2)
    print(f"\n✓ Full results saved to {output_file}")

# ─── --member-types ───────────────────────────────────────────────────────────
def run_member_types():
    print("Fetching member types...\n")
    try:
        types = get_member_types()
    except requests.HTTPError as e:
        print(f"⚠ Could not fetch member types: {e}")
        return

    for t in types:
        name = t if isinstance(t, str) else t.get("name", t)
        print(f"  • {name}")
    print(f"\n{len(types)} type(s) available.")

# ─── --find-duplicates ────────────────────────────────────────────────────────
def _norm_name(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())

def _norm_phone(s):
    digits = re.sub(r"\D", "", s or "")
    return digits[-10:] if len(digits) >= 10 else digits

def _norm_email(s):
    return (s or "").strip().lower()

def find_duplicate_members(members):
    by_email = defaultdict(list)
    by_name  = defaultdict(list)
    by_phone = defaultdict(list)

    for m in members:
        email = _norm_email(m.get("email"))
        first = _norm_name(m.get("firstName"))
        last  = _norm_name(m.get("lastName"))
        phone = _norm_phone(m.get("mobilePhone") or m.get("homePhone") or m.get("workPhone"))

        if email:
            by_email[email].append(m)
        if first and last:
            by_name[f"{first}|{last}"].append(m)
        if phone:
            by_phone[phone].append(m)

    return {
        "email": [g for g in by_email.values() if len(g) > 1],
        "name":  [g for g in by_name.values()  if len(g) > 1],
        "phone": [g for g in by_phone.values() if len(g) > 1],
    }

def _fmt_member(m):
    name  = f"{m.get('firstName','')} {m.get('lastName','')}".strip()
    email = m.get("email", "") or "(no email)"
    mid   = m.get("id", "") or ""
    return f"{name} <{email}> [{mid}]"

def run_duplicate_scan():
    print("Fetching full member list...")
    members = get_all_members()
    print(f"  ({len(members)} members)\n")

    dups = find_duplicate_members(members)
    seen_pairs = set()
    found_any = False

    for label, groups in (("EMAIL", dups["email"]), ("NAME", dups["name"]), ("PHONE", dups["phone"])):
        if not groups:
            continue
        print(f"── Duplicates by {label} ──")
        found_any = True
        for group in groups:
            key = tuple(sorted(m.get("id", "") for m in group))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            for m in group:
                print(f"  • {_fmt_member(m)}")
            print()

    if not found_any:
        print("No suspected duplicates found.")
        return

    output_file = "msr_duplicate_members.json"
    with open(output_file, "w") as f:
        json.dump(dups, f, indent=2)
    print(f"✓ Full results saved to {output_file}")

# ─── Usage ────────────────────────────────────────────────────────────────────
def print_usage():
    print("""
MSR Membership Utility
──────────────────────────────────────────────────────────────────────

  --check-roles        Scan 2026 events for renewal purchasers and verify
                       each has the Member role. Offers to fix any missing.
                       Output: msr_membership_role_check.json

  --expired-members    List current Member-typed accounts whose memberEnd
                       date is in the past or not set. Works regardless of
                       how they renewed (online or offline).
                       Output: msr_expired_members.json

  --member-types       Print all available member type labels from MSR.

  --find-duplicates    Scan the full member list for suspected duplicate
                       accounts, matched by email, name, or phone number.
                       Output: msr_duplicate_members.json

──────────────────────────────────────────────────────────────────────
Example:
  python membership.py --check-roles
  python membership.py --expired-members
  python membership.py --member-types
  python membership.py --find-duplicates
""")

# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--check-roles",      action="store_true")
    parser.add_argument("--expired-members",  action="store_true")
    parser.add_argument("--member-types",     action="store_true")
    parser.add_argument("--find-duplicates",  action="store_true")
    args = parser.parse_args()

    if args.check_roles:
        run_check_roles()
    elif args.expired_members:
        run_expired_members()
    elif args.member_types:
        run_member_types()
    elif args.find_duplicates:
        run_duplicate_scan()
    else:
        print_usage()
