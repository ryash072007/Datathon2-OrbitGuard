# Console behavior

Visual identity: [DESIGN.md](DESIGN.md). Domain/API source: [CONTRACTS.md](CONTRACTS.md).

## Canonical UI map

| Capability | Owner | Contract | Verification |
| --- | --- | --- | --- |
| Navigation | App hash sections | Encounters is default; original three tabs retain order; optional How it works is last; brand returns to Encounters | browser smoke |
| Table selection | Native row buttons in App | Single current encounter/policy, exposed through aria-pressed | browser smoke |
| Select/Listbox | Native scenario select | Platform-owned popup and keyboard behavior accepted | browser smoke |
| Scrollbar | Global style.css baseline | Visible themed scrollbars and stable document gutter; forced colors defer to OS | computed browser styles |
| Async state | useAsync in ui.tsx | Clear prior response on resource change; ignore superseded responses; loading, empty and inline retry states | fixture browser checks |
| Feedback | Loading, Empty, Notice, Status | Loading is announced; errors persist inline and offer recovery | fixture browser checks |
| Evidence export | EvidenceDownload in App | Download exact currently displayed API JSON using a browser Blob; no external write | browser download check |

## Flow ledger

Optional How it works content explains the two independent evidence streams. Historical forecasts use only messages at least two days before TCA; labels are retrospective comparison only. Planning is synthetic and does not derive geometry from anonymised ESA messages. These constraints come from CONTRACTS.md evaluation invariants and service contracts.

Encounter selection clears previous detail and forecast. Search applies only to the bounded API list, offers immediate clear, and does not request remote search. Normal selection/search are transient inspection state. Accuracy-audit links use an explicit `?event=ID#encounters` deep link, which may open an event outside the bounded list. Section navigation is shareable by hash.

Screening prevents duplicate submits, polls bounded server jobs, and announces failed or timed-out observation. Leaving planning invalidates outstanding local callbacks. A timeout does not imply server cancellation; preserve a job status link for checking completion. Results and downloads belong to that job.

All counts, metrics, confidence intervals and provenance come from `/api/evidence`; missing values display unavailable rather than invented zero. Point-forecast loss and raw review ranking remain separate. Threshold confusion counts describe high-risk labels, not actual collisions.

## Scope and accessibility

Historical playback now invokes server-selected prefixes through `/api/replay/update`. A compact timeline shows the last five inspected message positions, alert transitions and measured server/round-trip timings. Playback waits for each response and pauses on failure; retry reprocesses the same prefix. Scrubbing compares adjacent historical prefixes, not the previous scrub position. Switching encounters clears the timeline. Orbital illustrations use the selected prefix's latest message. Synthetic planning stays separate and no replay event starts a burn or screening job.

English operator/judge interface with explicit scientific units. No authentication, billing, deletion, spacecraft command, or private-data editing exists in this console. All actions use native links/buttons and visible keyboard focus. Native selects and replay sliders retain keyboard controls. Document scrolling remains available on mobile and reduced motion is respected.
