# MASTER PROMPT v2 — verbatim from user (2026-10-06, second message)

Note from Claude 1: the user referred to "the COMPLETE TECHNICAL GUIDE for my original Cross-Channel Money Mule Detection project". No such document was attached or found under `Documents/Projects`. Two additional source folders were found and are treated as the guide's source of truth:
`Indian Bank Project/CROSS-CHANNEL-MONEY-MULE-DETECTION-streamlit version` and `Indian Bank Project/Indian Bank Project - End half sim - half actual` (latest, Oct 5, Three.js graph).
If the guide exists as a file, place it in `AGENT_HANDOFF/inputs/`.

---

STOP treating the current implementation as the finished UX.
The architecture/backend work you completed is valuable, but I have now provided the COMPLETE TECHNICAL GUIDE for my original Cross-Channel Money Mule Detection project.
READ IT IN FULL.
That project was substantially richer than the subset currently carried into Vigil.
It included:

* continuous early warning
* rule-based detection
* Random Forest
* Graph Attention Network
* RF + Rules + GNN fusion
* SHAP account-level explainability
* behavioural drift
* adaptive thresholds
* fraud/mule role classification
* pattern signature memory
* ten attack patterns
* attack simulation
* live metrics
* precision/recall
* threshold evolution
* model-specific outputs
* detailed account investigation
* a high-impact graph visualisation

I do NOT want a simplistic command centre that looks like an AI-generated admin template.
I want Vigil to look and behave like an institutional-grade financial intelligence and transaction intervention platform.
PRIMA remains the architecture.
Vigil remains the product.
But Vigil must now unify THREE layers:

1. PRE-COMMITMENT PAYMENT PROTECTION
2. MONEY-MULE / NETWORK INTELLIGENCE
3. MODEL / INVESTIGATION / GOVERNANCE INTELLIGENCE

It must feel like ONE coherent financial operating system.
Do not simply bolt the old dashboard into the new application.
Redesign the information architecture professionally.
Before changing anything:
take screenshots of EVERY current page/state.
Create:
docs/UI_CURRENT_STATE.md
For each page state record:

* purpose
* what works
* what is confusing
* information duplicated elsewhere
* what looks generic/template-like
* what does not look institutional
* what should survive
* what should be redesigned

DO NOT blindly rebuild working functionality.
The platform should feel suitable for:

* central fraud intelligence teams
* bank fraud operations
* risk analysts
* investigation teams
* payment-risk decisioning teams

DO NOT copy RBI branding or logo.
The visual impression should be:
institutional
authoritative
high information density
calm
precise
trustworthy
technical
premium
NOT:
neon cyberpunk
generic SaaS
giant gradient cards
glassmorphism everywhere
AI-generated dashboard
random animations
oversized statistics
empty whitespace
student hackathon UI
Use a disciplined financial design system.
Dark/navy institutional shell is acceptable.
Use colour primarily to encode:
NORMAL
WATCH
HIGH RISK
CRITICAL
HELD
CONFIRMED FRAUD
Create/restructure navigation around:

1. OVERVIEW
2. TRANSACTION GUARD
3. NETWORK INTELLIGENCE
4. DETECTION INTELLIGENCE
5. INVESTIGATIONS
6. INTERVENTIONS
7. MODEL & EXPLAINABILITY
8. GOVERNANCE / AUDIT
9. SCENARIO LAB
10. SYSTEM HEALTH

Do not create ten useless pages.
Combine where appropriate, but every major concept must have a natural home.
==================================================

1. OVERVIEW
==================================================

This replaces any generic "Command Centre."
It should answer:
WHAT IS HAPPENING NOW?
WHAT REQUIRES ATTENTION?
WHAT VALUE IS AT RISK?
WHICH NETWORKS ARE EMERGING?
HOW ARE OUR DETECTORS PERFORMING?
WHAT INTERVENTIONS ARE ACTIVE?
Potential components:
live transaction rate
payment intents
Tier 2/3/4 interventions
suspicious accounts
confirmed fraud sources
value currently held
tainted downstream exposure
open investigations
detector agreement
network alerts
attack/pattern feed
system health
Include one compact live network thumbnail if useful.
Do NOT fill the page with meaningless cards.
This is PRIMA's pre-commit experience.
Must clearly show:
Sender
Recipient
Amount
Relationship
Device
Behaviour
Network intelligence
External intelligence
Journey signals
Context signal
Final decision
Before payment:
show the assessment.
After payment:
show provider/ledger outcome.
If challenged:
show the exact intervention.
The user-facing intervention must remain simple.
Bank-facing detail can be expanded underneath.
I want a HIGH-QUALITY 3D financial-network investigation view comparable to or better than my previous money-mule visualization.
Do not dismiss 3D simply because the previous implementation was slow.
ENGINEER IT CORRECTLY.
Requirements:

* WebGL
* stable precomputed/frozen node layout
* no permanently running force physics
* suspicious subgraph by default
* configurable node cap
* one/two-hop expansion
* cached graph payloads
* no graph rebuild on unrelated UI state change
* labels using level-of-detail
* transaction direction obvious
* optional edge particles only for selected/replayed money movement
* node selection investigation drawer
* smooth camera focus
* 2D fallback/toggle if useful

Graph modes:
MONEY FLOW
RISK
TAINT
MULE ROLES
GNN SCORE
RULE SCORE
ML SCORE
Visual distinction for:
victim
normal account
suspected mule
collector
distributor
coordinator
entry node
exit node
confirmed fraud source
held account/transaction context
Support a TIME / ATTACK REPLAY mode.
The graph should visually tell the story.
Bring back the analytical richness of the old project.
For selected account/attack show:
RULE ENGINE
RF MODEL
GNN MODEL
BEHAVIOURAL DRIFT
EARLY WARNING
PATTERN MEMORY
TRAIL SCORE
CONTEXT
EXTERNAL INTELLIGENCE
Then show:
DETECTOR CONSENSUS
Example:
Rules 0.72
Random Forest 0.81
GNN 0.91
Drift HIGH
TrailScore 0.87
External Intel MEDIUM
5 independent signal families agree.
Do NOT call every value a probability unless mathematically valid.
Do NOT simply put the old RF/GNN back into operational authorization if they are not scientifically credible.
However:
DO NOT DELETE THEM.
Audit and repair their evaluation.
Investigate:

* data leakage
* generator leakage
* labels leaking into features
* same simulation appearing across train/test
* scaling leakage
* graph leakage
* attack-window shortcuts
* unrealistic class balance

Retrain if it can be done tonight.
Use deterministic seeds.
Prefer split-by-run / split-by-scenario rather than random row split.
If possible perform an attack-generalisation experiment.
Record:
precision
recall
F1
ROC-AUC if appropriate
PR-AUC if appropriate
confusion matrix
calibration
per-attack detection
Clearly label:
SYNTHETIC VALIDATION
Never present this as real-bank accuracy.
Operational intervention can use the transparent validated engine while the ML/GNN outputs remain corroborating/model evidence.
Restore SHAP where the RF model is genuinely being run.
Selected account should show:
raw model prediction
top positive contributors
top negative contributors
human-readable categories
Examples:
Velocity Risk
Shared Device Risk
Ring Participation
Channel Risk
Retention Risk
Also retain deterministic ReasonLine separately.
SHAP explains the MODEL.
ReasonLine explains the OPERATIONAL DECISION.
Do not confuse them.
Restore/improve the original behavioural-drift concept.
Show:
historical baseline
current behaviour
drift score
top changing features
Example:
transaction_count
2 → 19
counterparties
1 → 8
retention
0.81 → 0.09
Make it visually useful.
If implementation is already mostly available, restore this.
Show:
CURRENT NETWORK SIGNATURE
versus:
KNOWN SIGNATURES
Example:
89% similarity — Rapid Fan-In/Pass-Through
71% — Smurfing Cluster
23% — Circular Ring
Label it appropriately as structural similarity, not criminal attribution.
Restore role analysis.
Roles:
Coordinator
Collector
Distributor
Entry
Exit
Unclassified
Show this both:
on investigation page
and
inside graph mode.
Implement if feasible.
For any high-risk transaction:
REPLAY DECISION
Timeline reconstructs the state leading to intervention.
Example:
10:31:02 login from new device
10:33:17 payee added
10:36:41 limit increased
10:38:09 suspicious context captured
10:39:24 ₹561,600 transfer attempted
10:39:24 external/network risk evaluated
10:39:25 Tier 4 generated
10:39:25 scoped hold created
10:39:25 trusted-contact alert dispatched
Allow timeline playback.
As each event occurs:
risk/subscores should visibly evolve.
This is one of the primary WOW features.
For each intervention answer:
WHY DID THIS HAPPEN?
AND:
WHAT WOULD NEED TO BE DIFFERENT FOR A LOWER TIER?
Example:
Current Tier: 4
Without the new-device + recent-payee sequence:
Tier 3
With an established recipient:
Tier 2
With established recipient + historically normal amount:
Tier 0/1
Generate this deterministically from the policy engine where feasible.
Do not use an LLM to invent the explanation.
Every material risk signal should expose:
SOURCE
VALUE
OBSERVED AT
FRESHNESS
RULE/MODEL VERSION
CONFIDENCE / STATUS
This is essential for institutional trust.
Add a product mode if feasible:
SHADOW MODE
Vigil evaluates but does not intervene.
Show:
BANK/BASE DECISION
VIGIL RECOMMENDATION
This provides a realistic adoption story:
first deploy in shadow,
measure false challenges/catch rate,
then enable intervention tiers.
ACTIVE MODE remains the demo mode.
For selected account/payment:
plot risk over time.
Markers should show WHY it changed.
Do not present a meaningless line chart.
Example:
0.08 Normal
0.18 New device
0.31 New payee
0.47 Limit raised
0.62 Network evidence
0.87 Transfer intent + corroboration
This should feel extremely strong.
Every decision record:
decision ID
transaction intent
timestamp
signals available
data provenance
model versions
policy version
subscores
thresholds
reason codes
chosen action
operator/customer action
payment result
Allow:
VIEW RAW RECORD
REPLAY DECISION
Do not allow UI text to imply it is actual RBI data.
Restore all useful attack simulations from the older money-mule project.
Fan-In
Fan-Out
Circular Ring
Velocity Chain
Cross-Channel Burst
Shared Device Cluster
Behavioural Drift
Early Volume Spike
Smurfing
Dormant Activation
Also:
Normal Transaction
High-Value Legitimate Control
Coercion/Digital-Arrest Scenario
Risky Recipient
For each scenario:
START
PAUSE
RESET
REPLAY
COMPARE DETECTORS
No randomness should destroy a live demonstration.
YOU ARE CLAUDE 1 / LEAD.
First write:
docs/FINAL_PARALLEL_PLAN.md
Freeze shared interfaces before others edit.
Own:
backend contracts
database
transaction lifecycle
fusion policy
interventions
Decision Replay backend
Counterfactual engine
Evidence Provenance
Shadow Mode
final integration
merge ownership
DO NOT waste time doing CSS.
Give Claude 2 ownership of isolated ML/intelligence modules.
Tasks:
audit old RF
audit GNN
repair training/evaluation where possible
retrain
generate metrics
SHAP
behaviour drift
pattern memory
role classification
detector consensus API
Do not allow Claude 2 to change payment authorization contracts.
It must create:
docs/ML_VALIDATION_REPORT.md
with honest synthetic-data limitations.
Give Claude 3 ownership of frontend visual redesign.
Tasks:
institutional design system
Overview
Transaction Guard
Network Intelligence
3D graph
investigation
model intelligence visualization
Decision Replay UI
Governance UI
responsive layout
micro-interactions
Do not permit backend architecture changes.
The final UI must NOT look like a template generated by AI.
Before implementation Claude 3 should inspect my old frontend if available and identify which visual ideas were strong enough to preserve.
Give Codex isolated engineering tasks:
optimized graph endpoint
graph caching
layout precomputation
benchmark 3D payload
scenario reset testing
concurrency tests
risk decision integration tests
WebSocket/realtime reliability
Razorpay test harness
ML inference timing
Decision Replay fixtures
Do not let Codex redesign shared application architecture.
Use Cursor only for:
responsive CSS
alignment
spacing
labels
icons
loading states
empty states
tooltips
accessibility
formatting
dead imports
component cleanup
minor visual bugs
No database.
No risk logic.
No model logic.
No transaction lifecycle.
I specifically need a COMPLETE RECORD of what every AI agent was asked and what it returned.
We already have an AGENT_HANDOFF concept.
Make it systematic.
Create:
AGENT_HANDOFF/
STATE.md
MASTER_PROMPT.md
AGENT_LEDGER.md
runs/
<timestamp>claude1<task>.md
<timestamp>claude2<task>.md
<timestamp>claude3<task>.md
<timestamp>codex<task>.md
<timestamp>cursor<task>.md
Every run file MUST contain:
Agent
Timestamp
Objective
Exact Prompt
Agent Output / Summary
Files Changed
Tests Run
Test Results
Screenshots/Artifacts
Problems Found
Decisions Made
Remaining Work
Git Commit / Diff Reference if available
Status
AGENT_LEDGER.md must have one row per run:
time | agent | task | status | files | tests | run-record
Whenever an agent returns:
SAVE THE RESULT BEFORE SENDING THE NEXT PROMPT.
This is mandatory.
If Git exists:
each agent should work on a dedicated branch or isolated change set where feasible.
Lead Claude reviews before merge.
Do not let parallel agents overwrite the same core files.
Maintain:
docs/CHANGELOG.md
P0:
professional unified UI
transaction flow
3D network investigation
old mule intelligence restored visibly
RF/GNN/Rules display
explainability
all core scenarios
Decision Replay
reliable reset
fast performance
trusted-contact path
audit/governance
P1:
improved ML retraining
SHAP
drift
pattern memory
role analysis
counterfactual
shadow mode
risk evolution
P2 only if time remains:
extra decorative visualizations
advanced animation
nonessential modelling experiments
DO NOT remove functioning features merely to simplify the architecture.
DO NOT keep weak functionality merely because it existed before.
DO NOT add sophistication just for buzzwords.
Every visible component must answer one of:
WHAT HAPPENED?
WHY IS IT RISKY?
WHAT DID EACH DETECTOR SEE?
HOW IS MONEY MOVING?
WHAT ACTION DID VIGIL TAKE?
WHY THAT ACTION?
WHAT WOULD MAKE IT SAFE?
WHAT WOULD AN INVESTIGATOR DO NEXT?
HOW WOULD A BANK GOVERN THIS SYSTEM?
The finished product should feel like a serious financial intelligence platform that happens to be an MVP — not a hackathon dashboard disguised with dark CSS.
Start the other agents as soon as contracts/file ownership are determined.
Do not wait until you finish your own work.
END GOAL:
I should be able to open this tomorrow and feel that the original money-mule project and PRIMA were both prototypes of something much larger:
VIGIL.
