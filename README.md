# MSR Member Role Checker

A utility for club administrators to audit and fix member roles in [MotorsportReg](https://www.motorsportreg.com/) (MSR). It scans past events for attendees who purchased a membership renewal package and verifies that each person's MSR member record has the `Member` role assigned — offering to fix any that are missing.

## What it does

1. Fetches all past events for the configured year from the MSR API
2. Scans each event's attendee list for anyone who purchased a membership renewal package
3. Looks up each purchaser's member record and checks for the `Member` role
4. Prints a summary table showing who has the role and who is missing it
5. Prompts to automatically fix any members missing the `Member` role
6. Saves full results to `msr_membership_role_check.json`

## Requirements

- Python 3.8+
- `requests` library

```bash
pip install requests
```

## Configuration

Edit the constants at the top of `membership.py`:

| Variable | Description |
|---|---|
| `MSR_USERNAME` | Admin email address for your MSR account |
| `MSR_PASSWORD` | MSR account password |
| `ORGANIZATION_ID` | Your 35-character MSR organization ID |
| `MEMBERSHIP_PACKAGES` | Set of membership package names to match (edit to match your club's package names) |

Your organization ID can be found in the MSR admin panel URL or via the API.

## Usage

```bash
python membership.py
```

The script will print progress as it scans events, then display a results table:

```
NAME                      EMAIL                          HAS MEMBER   CURRENT TYPES
──────────────────────────────────────────────────────────────────────────────────────────
Jane Smith                jane@example.com               ✓            Member, Driver
John Doe                  john@example.com               ✗ MISSING    Non-Member, Driver
```

If any members are missing the `Member` role, you'll be prompted:

```
Fix these members now? (yes/no):
```

Entering `yes` will update each affected member's record via the API, removing the `Non-Member` role and adding `Member` while preserving all other roles.

## Output

Full results are always saved to `msr_membership_role_check.json` in the current directory, regardless of whether any fixes were applied.

## Notes

- The script only scans **past** events (events with a start date before today)
- Each member is only counted once even if they attended multiple events
- The `MEMBERSHIP_PACKAGES` set must match the exact package names used in MSR
