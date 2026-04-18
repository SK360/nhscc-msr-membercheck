import requests
import json
from base64 import b64encode
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────
MSR_USERNAME    = "your_admin_email@example.com"
MSR_PASSWORD    = "your_password"
ORGANIZATION_ID = "your-35-char-org-id-here"

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

def fix_member_roles(member_id, current_types):
    """Remove Non-Member, add Member, keep everything else."""
    updated_types = [t for t in current_types if t != "Non-Member"]
    if "Member" not in updated_types:
        updated_types.append("Member")

    url = f"{BASE_URL}/rest/members/{member_id}.json"
    headers = get_headers()
    headers["Content-Type"] = "application/json"
    r = requests.put(url, headers=headers, json={"types": updated_types})
    r.raise_for_status()
    return updated_types

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("Fetching 2026 events...")
    events = get_2026_events()

    if not events:
        print("No past events found for 2026.")
        return

    print(f"Scanning {len(events)} past event(s).\n")

    # ── Step 1: find everyone who bought a membership renewal package ──────────
    membership_buyers = {}

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

            if member_id not in membership_buyers:
                membership_buyers[member_id] = {
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

    print(f"\nFound {len(membership_buyers)} unique membership renewal purchaser(s).\n")

    # ── Step 2: check each person's member roles ───────────────────────────────
    results = []

    for member_id, buyer in membership_buyers.items():
        print(f"  Checking {buyer['name']} ({buyer['email']})...")
        try:
            member = get_member(member_id)
        except requests.HTTPError as e:
            print(f"    ⚠ Could not fetch member record: {e}")
            buyer["types"]      = "ERROR"
            buyer["has_member"] = False
            results.append(buyer)
            continue

        raw_types  = member.get("types", [])
        type_names = [t if isinstance(t, str) else t.get("name", "") for t in raw_types]

        buyer["types"]      = ", ".join(type_names) if type_names else "(none)"
        buyer["has_member"] = any(t.lower() == "member" for t in type_names)
        buyer["raw_types"]  = type_names
        results.append(buyer)

    # ── Print results ──────────────────────────────────────────────────────────
    print(f"\n{'─'*90}")
    print(f"{'NAME':<25} {'EMAIL':<30} {'HAS MEMBER':<12} {'CURRENT TYPES'}")
    print(f"{'─'*90}")

    needs_update = []
    for r in sorted(results, key=lambda x: x["name"]):
        member_flag = "✓" if r["has_member"] else "✗ MISSING"
        print(f"{r['name'][:24]:<25} {r['email'][:29]:<30} {member_flag:<12} {r['types']}")
        if not r["has_member"]:
            needs_update.append(r)

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'─'*90}")
    print(f"Total renewal purchasers:  {len(results)}")
    print(f"Missing Member role:       {len(needs_update)}")

    # ── Step 3: offer to fix ───────────────────────────────────────────────────
    if needs_update:
        print("\nPeople who need roles fixed:")
        for r in needs_update:
            print(f"  • {r['name']} ({r['email']}) — current types: {r['types']}")

        print()
        answer = input("Fix these members now? (yes/no): ").strip().lower()
        if answer == "yes":
            print()
            for r in needs_update:
                print(f"  Fixing {r['name']}...", end=" ")
                try:
                    new_types = fix_member_roles(r["member_id"], r["raw_types"])
                    print(f"✓  types now: {', '.join(new_types)}")
                except requests.HTTPError as e:
                    print(f"✗ FAILED: {e}")
            print("\nDone.")
        else:
            print("No changes made.")
    else:
        print("\nEveryone looks good — no fixes needed.")

    # ── Save full results ──────────────────────────────────────────────────────
    output_file = "msr_membership_role_check.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Full results saved to {output_file}")

if __name__ == "__main__":
    main()
