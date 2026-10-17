# Audit log

`artifacts/audit/decisions.jsonl` (override with `AUDIT_LOG`) is an append-only, hash-chained record of what the
AI recommended and why: replayed forecasts, catalogue screens, briefs and the operator's accept / reject / defer.
The console's Audit panel and `GET /api/audit` show the head hash and verify the chain. Each line stores the payload, its sha256 and
`record_hash = sha256(prev_hash + canonical JSON of the record)`, so editing or deleting any earlier line
breaks the chain. Check with `python -m orbitguard.audit verify`. Operators need an accountable, tamper-evident trail.
Limitation: dropping the newest lines is only detectable if the head hash is stored elsewhere.

On IBM Z the production path would pair this with hardware-backed integrity (pervasive encryption, Secure
Execution). That is a design note, not a claim that it ran there.
