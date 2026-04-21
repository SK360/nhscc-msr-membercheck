# MSR Membership Utility

A command-line utility for club administrators to audit membership data in [MotorsportReg](https://www.motorsportreg.com/) (MSR). It provides several tools for verifying member roles, finding expired memberships, listing member types, and detecting duplicate accounts.

## Features

| Flag | What it does |
|---|---|
| `--check-roles` | Scans past events for members who purchased a renewal package, verifies each has the `Member` role AND a `memberEnd` date of 12/31 of the current year, and offers to fix any that are wrong or missing. |
| `--expired-members` | Lists all current `Member`-typed accounts whose `memberEnd` date is in the past (or not set). Works regardless of whether the member renewed online or offline. |
| `--member-types` | Prints all available member type labels from MSR. |
| `--find-duplicates` | Scans the full member list for suspected duplicate accounts, matched by email, normalized name, or phone number. |
| *(no flags)* | Prints the usage screen. |

## Requirements

- Python 3.8+
- `requests`
- `python-dotenv`

```bash
pip install requests python-dotenv
```

## Configuration

Credentials are loaded from a `.env` file in the project root (never committed). Create one with:

```
MSR_USERNAME=your_admin_email@example.com
MSR_PASSWORD=your_password
MSR_ORGANIZATION_ID=your-35-char-org-id-here
```

Your organization ID can be found in the MSR admin panel URL or via the API at `motorsportreg.com/em360/index.cfm/event/profile.api`.

You may also want to edit the `MEMBERSHIP_PACKAGES` set near the top of `membership.py` to match the exact renewal package names your club uses.

## Usage

```bash
python membership.py                    # show usage screen
python membership.py --check-roles
python membership.py --expired-members
python membership.py --member-types
python membership.py --find-duplicates
```

### `--check-roles`

Scans every past event for attendees who bought a renewal package, then verifies each purchaser's MSR record meets both conditions for a valid member:

1. Has the `Member` role (not `Non-Member`)
2. Has a `memberEnd` date of 12/31 of the current year

Prints a summary table and prompts to fix anyone who fails either check:

```
NAME                      EMAIL                          MEMBER     END DATE       TYPES
────────────────────────────────────────────────────────────────────────────────────────────────────
Jane Smith                jane@example.com               ✓          ✓ 2026-12-31   Member, Driver
John Doe                  john@example.com               ✗          ✗ 2025-12-31   Non-Member, Driver
```

Entering `yes` at the prompt updates each affected record via the API — removing `Non-Member`, adding `Member`, and setting `memberEnd` to `12/31/<current year>`, preserving all other roles. Results saved to `msr_membership_role_check.json`.

### `--expired-members`

Fetches every account currently typed `Member` and pulls each individual record to check the `memberEnd` date. Anyone whose date is in the past (or missing) appears in the report. Unlike `--check-roles`, this does not depend on event purchases — it works for offline renewals too. Results saved to `msr_expired_members.json`.

Note: this makes one API call per member, so it's slower than the other commands.

### `--member-types`

Prints every member type label configured in your MSR organization (e.g. `Member`, `Non-Member`, `Life Member`, `Season Pass`, `Attendee`, `Instructor`). Useful for verifying role names before modifying the role-fix logic.

### `--find-duplicates`

Pulls the full member list and groups accounts that share the same email (case-insensitive), first+last name (non-alphabetic characters stripped), or phone number (last 10 digits). Only groups with more than one match are reported. Results saved to `msr_duplicate_members.json`.

## Output files

All JSON output files are gitignored by default since they may contain member PII:

- `msr_membership_role_check.json`
- `msr_expired_members.json`
- `msr_duplicate_members.json`

## Notes

- The role-check scan only looks at **past** events (start date before today)
- Each member is only counted once even if they appear in multiple events
- `memberEnd` dates are parsed from ISO (`YYYY-MM-DD`), US (`MM/DD/YYYY`), or short-year (`MM/DD/YY`) formats
