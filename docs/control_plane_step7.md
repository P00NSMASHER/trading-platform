# Control-Plane Step 7 - Dashboard and Pseudonymous Account Surveillance

Step 7 extends the existing loopback-only private dashboard with read-only control-plane and account-surveillance views.

It does not add market-data acquisition, live monitoring, trading outputs, model execution, gate-closing actions, publicity-clearance actions, lineage mutation, or release-authority issuance.

## Account-surveillance boundary

`src/control_plane/account_surveillance.py` links already-created immutable surveillance cases to a pseudonymous account subject.

The only accepted mapping columns are:

`account_key,case_id,research_use_only`

The mapping file must already exist locally. Step 7 does not fetch account or customer data.

### Identity minimization

The raw `account_key` is used only in memory to compute:

`acct_<SHA-256("account-subject\\0" + account_key)>`

Only the pseudonymous subject ID is stored.

The account database does not persist:

- raw account keys;
- names;
- email addresses;
- phone numbers;
- postal addresses;
- SSNs/tax IDs;
- dates of birth;
- credentials or access tokens.

Input files containing explicit identity columns or trading/output columns are rejected.

The source file itself is not copied into the account database or dashboard. The immutable link records only its SHA-256 and a path fingerprint.

## Case binding

Every account-case link is bound to an immutable case-evidence fingerprint covering the recorded case, event/security/time, surveillance score/threshold/flag, model SHA-256, creation time, and source-artifact hashes.

Before a link is accepted:

- the case must exist;
- the case must be research-only;
- its review hash chain must verify;
- its model source hash must match the case model hash.

Account subject and account-case-link rows are immutable: SQLite triggers reject UPDATE and DELETE.

Repeated ingestion of an identical account/case relationship is a no-op.

## Account views

The dashboard displays only pseudonymous subject IDs and case-derived surveillance facts:

- linked case count;
- linked flagged-case count;
- distinct security count;
- maximum recorded surveillance score across the linked cases;
- latest linked case timestamp;
- immutable case-binding integrity;
- linked case IDs, securities, scores, flags, and current human-review dispositions.

These are triage/aggregation fields only. They are not a conclusion that the account, a person, or a firm committed insider trading, MNPI misuse, or another violation.

No raw account identifier or identity field is rendered.

## Control-plane dashboard

When launched with a private control directory, the authenticated dashboard adds a read-only control-plane view showing:

- overall Step-2 through Step-5 control-plane integrity;
- information-object state counts;
- lineage-artifact count;
- an optional saved G12-G15 assessment;
- optional account-surveillance integrity;
- metadata from an optional recorded Step-6 release-authority token.

A recorded authority token is display evidence only. The dashboard does not treat the file as current cryptographic authorization. The Step-6 execution path still re-verifies the external signer trust, signature, current G1-G15 state, evidence hashes, control-plane integrity, and champion bytes before execution.

The control-plane page exposes no forms or POST actions.

## Existing dashboard protections remain

The Step-9 private dashboard protections remain in force:

- loopback-only bind;
- rejection of non-loopback Host headers;
- single-use per-launch bootstrap authentication;
- separate session token;
- CSRF protection for the existing case-review/export writes;
- request-size, URI-size, rate, concurrent-connection, and socket-timeout limits;
- restrictive CSP/no-cache/frame-denial/no-referrer/browser-permission headers;
- no raw licensed market-data serving;
- no BUY/SELL, expected-return, target-price, position-size, order, or execution output.

Account and control-plane routes are authenticated GET-only surfaces.

## Launch

The existing dashboard can optionally be supplied the Step-7 sources:

```bash
PYTHONPATH=src python src/private_dashboard.py \
  --db private_runtime/cases.sqlite \
  --account-db private_runtime/account_surveillance.sqlite \
  --control-dir private_runtime/control \
  --g12-g15-assessment private_runtime/release/g12_g15_assessment.json \
  --release-authority-token private_runtime/release/release_authority_token.json \
  --host 127.0.0.1 \
  --port 8765
```

The original case-only launch remains valid when those optional paths are omitted.

## Safety boundary

Account aggregation cannot:

- append or change case reviews;
- clear publicity;
- create or change lineage;
- change G1-G15;
- create/sign release authority;
- modify the frozen champion;
- start a challenger evaluation;
- connect to a broker;
- create an order or trading recommendation.

Step 8 remains the adversarial CI and final audit-pack stage.
