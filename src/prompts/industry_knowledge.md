# Industry Knowledge Pack — Geotechnical Construction Estimating

This document consolidates authoritative industry knowledge gathered by The Lobstermen research crew for use alongside UMA's institutional knowledge pack (`system.md`). It covers five domains: (1) geotechnical design and reporting standards, (2) estimating methods and productivity norms, (3) plans + specs + DOT research, (4) subcontracting business and risk, and (5) geotech construction methods + testing.

This content is authoritative reference material — cite it when justifying a number, flagging a risk, or explaining a methodology to the user. Do not fabricate authorities; if a figure is project-specific, pull it from the bid docs or the web, not from this file.

---

## §1 — Geotechnical Design and Reporting Standards

### 1.1 FHWA Geotechnical Engineering Circulars (GECs)

The Federal Highway Administration publishes the authoritative design manuals for geotechnical construction. Read the specification callouts in the bid package and map them to the correct GEC before estimating — design assumptions drive quantities.

- **GEC-7 (FHWA-NHI-14-007), "Soil Nail Walls"** — design, construction, and testing of soil nail walls. Covers corrosion protection, global stability, internal/external stability, drainage, facing design (temporary shotcrete + permanent cast-in-place or precast), nail testing (proof, verification, creep).
- **GEC-4 (FHWA-IF-99-015, rev. 2018), "Ground Anchors and Anchored Systems"** — permanent and temporary tieback anchors, strand and bar, bond zone design, load testing (performance, proof, creep / extended creep), anchor corrosion protection (Class I encapsulated vs. Class II grout-only).
- **NHI-05-039 (FHWA Micropile Design and Construction Reference Manual)** — the bible for micropile work. Types A/B/C/D grouting classifications, bond zone geometry, steel and grout contributions to capacity, group effects, connection to structure, load testing (ASTM D1143 compression, D3689 tension, D3966 lateral).
- **NHI-16-009 (Design and Construction of Driven Pile Foundations)** — driven steel, timber, and concrete piles. Dynamic analysis (WEAP, CAPWAP), set criteria, freeze/relaxation, PDA testing per ASTM D4945.
- **NHI-15-047 (Drilled Shafts: Construction Procedures and Design Methods)** — drilled shaft (caisson) construction, slurry methods (bentonite, polymer), CSL testing per ASTM D6760, thermal integrity profiling.
- **FHWA-SA-96-069 (Mechanically Stabilized Earth Walls)** — MSE wall design/construction.
- **FHWA-NHI-06-019 (Earth Retaining Structures Reference Manual)** — catalog of retaining systems and when each applies.

### 1.2 AASHTO LRFD Bridge Design Specifications

Section 10 governs foundations for all bridge work and many public retaining structures.

- **Resistance factors (φ)** typically range 0.45–0.70 depending on method and testing:
  - Static analysis of driven piles: φ ≈ 0.45–0.55
  - Dynamic testing (PDA) with signal matching: φ ≈ 0.65
  - Static load test: φ ≈ 0.75–0.80
  - Drilled shafts (side + tip): φ ≈ 0.45–0.70 depending on method
  - Micropiles: φ ≈ 0.55–0.70 (verification testing pushes higher)
- **Load factors (γ)** for Strength I, Strength II, Extreme Event I/II, Service I/II govern combinations.
- Group efficiency, downdrag (negative skin friction), scour, and seismic demands must be checked.

### 1.3 Geotechnical Reports — How to Read Them

A geotechnical investigation report (a.k.a. "geotech report," "soils report," GBR, or GDR) is the single most important document for estimating subsurface work. Look for:

- **Boring logs** — SPT N-values (standard penetration test, ASTM D1586), depth to refusal, water table depth, rock quality where applicable. Blow counts give a fast feel for drillability and soil stiffness: N<4 very soft/loose, 4–10 soft/loose, 10–30 medium, 30–50 stiff/dense, 50+ very stiff/very dense, >100 or refusal = rock or boulders.
- **Rock characterization** — RQD (Rock Quality Designation, %), unconfined compressive strength (UCS, psi or MPa), core recovery. RQD <25% = very poor rock (drill slow, high rate of bit wear); RQD >90% = excellent rock (clean core).
- **Soil classification** — USCS symbols (SP, SM, SC, ML, CL, CH, OL, OH, Pt). Unified system is the default; AASHTO M145 classification (A-1 through A-7) appears on DOT work.
- **Atterberg limits** — LL, PL, PI. PI >20 = high plasticity (sensitive clays, potential for squeezing in casing).
- **CPT logs (cone penetration test)** — tip resistance qc, sleeve friction fs, pore pressure u2. Better continuous data than SPT where soft soils dominate.
- **Groundwater** — multiple readings at different times matter. Seasonal high water level drives dewatering scope and grouting methodology. Artesian conditions are a red flag — special methods required.
- **Lab results** — consolidation, triaxial, direct shear, grain size, moisture content, unit weight. Use these to sanity-check design assumptions when the design engineer's bearing/bond values seem aggressive.

### 1.4 Geotechnical Baseline Reports (GBR) vs Geotechnical Data Reports (GDR)

On larger public works and tunneling jobs, owners sometimes issue a **GBR** (contractually binding baseline description of ground conditions) separately from a **GDR** (raw data). When a GBR is in the contract, it defines the contractor's basis of bid — anything worse than the GBR description is a Differing Site Condition (DSC) claim; anything consistent with the GBR is the contractor's risk. Read any GBR line-by-line and flag discrepancies in the estimate's "clarifications."

### 1.5 State DOT Geotechnical Specifications

- **VDOT Road & Bridge Specifications** — Section 414 (Earth Retaining Systems), Section 415 (Drilled Shafts), Section 407 (Driven Piles). VDOT iPM (Plans and Proposal Management) is the public-facing letting portal.
- **NCDOT Standard Specifications** — current edition typically dated by year; Sections 410–455 cover geotechnical work. NCDOT project searches use "Contract ID" (letters + digits like "DN12200752") and the Letting Services portal.
- **SCDOT Standard Specifications** — Section 700 series governs structures and foundations.
- **FDOT Standard Specifications** — Sections 455 (Structures Foundations) and 548 (Retaining Wall Systems) are the micropile/anchor/MSE core.

Always confirm the specification version cited in the bid package matches the current published edition — changes to test acceptance criteria or corrosion-protection requirements between editions can materially change cost.

---

## §2 — Estimating Methods and Productivity Norms

### 2.1 AACE Estimate Classes

The Association for the Advancement of Cost Engineering (AACE) publishes Recommended Practice 18R-97, defining five estimate classes by maturity and purpose.

| Class | Maturity | Typical Use | Accuracy Range (low–high) | Contingency |
|---|---|---|---|---|
| 5 | 0–2% | Concept screening | −30% to +50% | 25–50% |
| 4 | 1–15% | Feasibility | −20% to +30% | 20–30% |
| 3 | 10–40% | Budget authorization | −15% to +20% | 15–25% |
| 2 | 30–75% | Control / bid | −10% to +15% | 10–15% |
| 1 | 65–100% | Check / final bid | −5% to +10% | 5–10% |

Most UMA hard-bid geotechnical work is Class 2 or better. "Conceptual" or "budgetary" pricing for an owner's feasibility study is Class 3–4.

### 2.2 Productivity Benchmarks (Published Industry Norms)

These are starting points from RSMeans, Richardson, and Walker's Building Estimator's Reference. UMA's institutional productivity (in §2 of `system.md`) takes precedence where the two conflict, because UMA data is project-specific and calibrated to UMA crews and equipment.

- **Micropile production (7"–9.625" diameter)**: 40–80 LF per crew-day in reasonable ground; 20–40 LF in boulders/mixed face; 80–120 LF in clean soil.
- **Soil nail installation**: 10–20 nails per crew-day (self-drilling hollow bar); 6–12 nails per day for drilled-and-grouted with temporary casing.
- **Shotcrete application**: 150–400 SF per hour per nozzleman on a prepped face, wet mix; rebound losses 15–30% dry mix, 5–15% wet mix.
- **Drilled shafts (36"–72")**: 30–80 LF per day in soil, much slower in rock; expect rock sockets at 5–15 LF/day per rig.
- **Tieback anchor installation**: 2–6 anchors per crew-day depending on length and drilling method.

### 2.3 Labor Burden (Public Bidding on Federal + State Jobs)

Labor burden is bare wage × a multiplier that captures fringes, insurance, taxes, and overhead allocation.

- Federal-aid projects (Davis-Bacon) require payment of **Prevailing Wages** per the Wage Determination (WD) in the contract. State-aid projects follow state "little Davis-Bacon" acts where applicable (Virginia's Little Davis-Bacon was enacted 2020; North Carolina has none at state level).
- **Fringe benefits** on DB/WD jobs can be paid as cash or bona-fide fringe contributions; the WD lists both rates.
- **Payroll taxes**: Federal FICA (7.65% of gross to the SS wage base), FUTA (0.6% net), SUTA (varies by state and experience, typically 1–6% on a wage base).
- **Workers' comp** is classified by NCCI code — geotechnical/foundation work often 6217 (excavation, NOC), 5403 (carpentry, structural), 6220 (pier drilling), with rates commonly in the $5–$15 per $100 wages range depending on EMR.
- **General liability, auto, umbrella**: typically 3–5% of payroll combined.
- **Typical all-in burden multiplier** on open-shop geotech work runs **1.45×–1.70×** bare wage; union work runs **1.60×–2.00×**.

### 2.4 Equipment Costing

- **Ownership cost** = depreciation + interest + property tax + insurance + storage. Blue Book (EquipmentWatch) is the industry reference; many DOTs publish their own equipment rental rates (Virginia's VDOT Equipment Rental Rate, FHWA Force Account rates).
- **Operating cost** = fuel, filters, oil, grease, tires/undercarriage, repair reserve. Typical diesel consumption 2.5–4.5 gal/hr for a 150–250 HP rotary rig.
- **Rental** — add 20–30% to blue-book rental for insurance, delivery, and contingency unless already included.

### 2.5 Markups — Overhead, Profit, Bond, Tax

- **Job overhead (indirect)** — project-specific costs (project manager, superintendent attributable to this job, mobilization, bonds, small tools, temp office, dumpsters, QA/QC, testing that's the contractor's responsibility). Typically budgeted as a line-item list, NOT a percentage, on any job over $500K.
- **General overhead (home-office G&A)** — rent, accounting, executives, estimating. Typical 6–12% of revenue for a mid-sized specialty subcontractor; UMA uses **80%** applied to labor (see `system.md` §2) which is a labor-only markup equivalent.
- **Profit** — 5–12% on specialty work, driven by risk and competitive climate. UMA default **10%**.
- **Bond** — Payment & Performance bond on public work runs **0.6%–1.5%** of bid price depending on contractor's bonding program. Lower volume = higher rate. UMA default **3%** is conservative and safe.
- **Sales tax / use tax** — varies by state; applies to materials, not labor. Virginia 5.3–7.0%, North Carolina 4.75%+local, South Carolina 6.0%+local, DC 6.0%. UMA default **7.25%**.

### 2.6 Unit vs Lump Sum Contracting

- **Unit price bids** — quantities are estimated by the owner and contractor is paid on actual quantities installed × bid unit price. Standard on all state DOT work. Risk: the contractor eats small price errors on quantity; owner eats overruns. Watch for **unbalanced bidding** traps — loading front-loaded items for cash flow is common but the owner may reject the bid or adjust quantities.
- **Lump sum bids** — single price for the entire scope. Contractor bears all quantity risk. Common on design-build and private work.
- **GMP (Guaranteed Maximum Price)** and **T&M (Time and Materials)** — less common on specialty sub work but appear in change-order pricing.

### 2.7 CSI MasterFormat Division 31 Codes (Geotech-Relevant)

- 31 00 00 — Earthwork
- 31 23 00 — Excavation and Fill
- 31 32 00 — Slope Protection
- 31 32 19 — Soil Nailing
- 31 41 00 — Shoring
- 31 48 00 — Underpinning
- 31 62 13 — Driven Concrete Piles (13.13 steel, 13.16 cast-in-place, 13.19 H-piles, etc.)
- 31 62 16 — Steel Piles
- 31 62 19 — Timber Piles
- 31 63 00 — Bored Piles (Drilled Shafts / Caissons)
- 31 63 33 — Drilled Micropiles
- 31 66 00 — Special Foundations (helical piles, compaction grouting, jet grouting)
- 31 68 00 — Foundation Anchors (ground anchors / tiebacks)

Division 32 — Exterior Improvements picks up shotcrete in 32 05 23 (cement and concrete for exterior improvements) or MEB drains; landscape retaining walls live in 32 32.

### 2.8 Public Bidding Process

- **ITB (Invitation to Bid) / IFB (Invitation for Bids)** — the owner's formal solicitation. Documents include bid form, spec book, plans, geotechnical report, prevailing wage decision, and any addenda.
- **Pre-bid meeting** — frequently mandatory on public work. Sign-in sheet becomes the prospective bidders list for many owners. Questions raised in the meeting are typically answered in a formal addendum.
- **Addenda** — the ONLY way the bid documents can be modified between issue and bid opening. Acknowledge every addendum on the bid form or the bid is nonresponsive.
- **Bid bond / bid security** — typically 5% of bid price (sometimes 10%) in bond, cashier's check, or LOC. Forfeited if the low bidder fails to execute the contract.
- **Subcontractor listing** — many owners require prime bidders to list major subs with the bid (California PCCA, New Jersey, Virginia public works). This creates a binding relationship that the prime cannot substitute without cause.

---

## §3 — Plans, Specifications, and DOT Research

### 3.1 Drawing Types and How They Stack

A full bid drawing set is organized by discipline, each with its own prefix and numbering:

- **G — General** — cover sheet, index, location map, abbreviations, legend, general notes.
- **C — Civil** — site plans, grading, drainage, utilities, erosion control.
- **S — Structural** — foundation plans, framing plans, sections, details, schedules.
- **F — Foundation** (or S-0xx when no F-series) — footing plans, pile/pier/micropile layout, load schedules, pier details.
- **GE — Geotechnical** (not all sets have this) — boring location plans, subsurface profiles, temporary shoring / retaining wall plans.
- **A — Architectural**, **M — Mechanical**, **P — Plumbing**, **E — Electrical**, **FP — Fire Protection** — other disciplines.
- **H — Highway/Horizontal** — on DOT drawings, roadway plans, profiles, cross-sections.
- **B — Bridge** — on DOT bridge plans, general plan & elevation, deck, substructure, superstructure.

### 3.2 Drawing Scales (Imperial and Metric)

- Site / civil: 1"=10', 1"=20', 1"=30', 1"=50'; metric 1:100, 1:200.
- Foundation plans: 1/8"=1'-0" (1:96) or 1/4"=1'-0" (1:48).
- Details: 3/4"=1'-0", 1"=1'-0", 1½"=1'-0", 3"=1'-0".
- Sections: typically 1/4"=1'-0" or larger.
- DOT plan & profile: 1"=50' horizontal, 1"=5' vertical (10:1 vertical exaggeration).

Always confirm scale on each sheet — scale varies per sheet. When in doubt, measure a dimensioned element and back-calculate.

### 3.3 CSI 3-Part Specification Format

Every technical specification section follows the same three-part structure (MasterFormat 2004+ format):

- **Part 1 — General**: summary, related sections, submittals, references, quality assurance, delivery/storage/handling, project conditions, sequencing, warranty.
- **Part 2 — Products**: manufacturers, materials, equipment, fabrication, source quality control.
- **Part 3 — Execution**: examination, preparation, installation, field quality control, cleaning, protection, schedules.

Critical estimating reads:
- Part 1 **Submittals** — working drawings, design calculations, mix designs, product data, QC plan. These are deliverable costs.
- Part 1 **Quality Assurance** — who tests what, who pays. "Contractor shall retain an independent testing agency" = the contractor's money.
- Part 3 **Field Quality Control** — load test counts and types, frequency of QA sampling, acceptance criteria. This is the biggest variable in testing cost.

### 3.4 General Conditions — Read These First

AIA A201 or ConsensusDocs 200 family General Conditions set the prime–owner relationship, but subs are bound by flow-down. Key articles:

- **Differing Site Conditions (Type I: physically different from contract; Type II: unusual nature)** — notice requirements are typically 14 or 21 days. Miss the notice, lose the claim.
- **Changes in the Work** — how change orders are priced (lump sum, unit price, T&M, cost+markup). Markup caps are frequently 15% on self-performed, 5% on sub-tier work.
- **Time** — liquidated damages, float ownership (usually owner owns, sometimes shared), weather day allowances.
- **Payment** — schedule of values, retainage percentage, net payment terms, final payment requirements.

### 3.5 RFIs and Addenda

- **Request for Information (RFI)** — contractor's formal question to the design team during construction (or during bid as a "bid question"). Bid-period questions must be converted to addenda to bind all bidders.
- **Addenda** — numbered modifications to the bid documents. Each addendum typically includes a list of changes, revised drawings, revised spec sections, and clarifying responses to bidder questions.
- **Bulletins / Supplemental Instructions** — during construction, design team clarifications that do not change cost or time.
- **Construction Change Directives (CCDs)** — owner instruction to proceed with a change before cost/time is agreed; contractor must track costs.

### 3.6 CPM Scheduling Basics

- **Critical path** — longest path of dependent activities through the network; delay any critical activity and the project finishes later.
- **Float (slack)** — total float = how much an activity can be delayed without delaying project completion. Free float = delay without affecting successor.
- **Logic** — Finish-Start (FS) is default; Start-Start (SS), Finish-Finish (FF), Start-Finish (SF) available with lag/lead. Overuse of SS/FF is a red flag for unrealistic schedules.
- **Baseline schedule** vs **as-built schedule** — TIA (Time Impact Analysis) compares baseline to actual for delay claims.
- Most geotechnical activities are on or near the critical path of a building foundation or bridge substructure — schedule impact dominates any cost impact of a delay.

### 3.7 State DOT Research Portals

- **VDOT**: [vdot.virginia.gov](https://www.vdot.virginia.gov) — iPM Plans & Proposal Management for lettings and plan-holder lists; Business Center for prequalification.
- **NCDOT**: [ncdot.gov](https://www.ncdot.gov) → Doing Business → Letting Services for bid lettings, plan-holders, and specs; Connect NCDOT for prequalification.
- **SCDOT**: [scdot.org](https://www.scdot.org) → Business Center → Bidding Opportunities.
- **FDOT**: [fdot.gov](https://www.fdot.gov) — Letting Information System (LIS) and Project Solicitation Notices.
- **Federal**: [SAM.gov](https://sam.gov) consolidates federal procurement (formerly FedBizOpps).
- **Regional plan rooms**: iSqFt, BidClerk, Dodge Data, ConstructConnect, and local plan rooms (Virginia Plan Room, NCAGC Plan Room, AGC of the Carolinas). Plan rooms publish the plan-holders list, which is the most reliable source for prospective bidders on private and many public jobs.

### 3.8 Geotechnical Investigation Documents in a Bid Package

Expect to find (some or all of):
- Boring location plan
- Boring logs (individual sheets or a boring log sheet)
- Subsurface profile sections
- Lab test summary
- Narrative report discussing geology, recommendations for foundations, retaining walls, pavement, seismic design
- Seismic site class determination
- Sometimes a standalone "Geotechnical Baseline Report" for tunneling or major civil works

---

## §4 — Subcontracting Business and Risk

### 4.1 Standard Subcontract Forms

- **AIA A401 — Standard Form of Agreement Between Contractor and Subcontractor** — the most widely used prime-sub contract in commercial construction. Incorporates A201 General Conditions by reference and flows them down to the sub.
- **ConsensusDocs 750 — Standard Short Form Agreement Between Constructor and Subcontractor** — increasingly used; considered more balanced between GC and sub than AIA in some provisions (pay-if-paid, indemnity).
- **DBIA-580 — Subcontract for Design-Build** — where the project is design-build and sub is doing some design work.
- **Contractor-drafted forms** — most large GCs have proprietary subcontract forms. These vary wildly; read them.

### 4.2 Flow-Down Clauses

A flow-down clause makes the subcontractor responsible for the same obligations the GC owes the owner under the prime contract, to the extent applicable to the sub's work. Read the prime General Conditions — they govern your sub by reference.

### 4.3 Pay-if-Paid vs Pay-When-Paid

- **Pay-when-paid**: GC has a reasonable time to pay sub after receiving payment from owner. If owner never pays, GC still owes sub eventually. Timing clause only.
- **Pay-if-paid**: GC owes sub ONLY IF owner pays GC. Owner non-payment = sub non-payment, forever. Condition-precedent clause.
- **State-by-state enforceability** (critical for UMA's multi-state footprint):
  - **North Carolina**: pay-if-paid clauses are **VOID and UNENFORCEABLE** (N.C.G.S. §22C-2).
  - **South Carolina**: pay-if-paid clauses are **VOID and UNENFORCEABLE** (S.C. Code §29-6-230).
  - **Virginia**: SB 550 (effective Jan 1, 2023) **voids pay-if-paid clauses** on most private and public construction contracts; payment must be made within certain timeframes.
  - **Maryland, New York, Illinois, California (limited), Wisconsin, Delaware**: pay-if-paid is void or limited.
  - **Most other states**: enforceable if clearly written as condition precedent.
- When reviewing a contract: note the state, note the clause language ("condition precedent" vs "reasonable time"), and price accordingly.

### 4.4 Bonds and Insurance

- **Bid Bond** — 5–10% of bid, forfeit on contract refusal. Issued in the bid.
- **Performance Bond** — 100% of contract value, guarantees completion. Typically required on public work ≥$100K (Miller Act federal, state equivalents).
- **Payment Bond** — 100% of contract value, protects subs and suppliers. Often issued together with performance as a combined 100% bond or 100%/100%.
- **Maintenance/Warranty Bond** — typically 1 year, covers defects after completion.
- **Insurance typical minimums on commercial subcontracts**:
  - Commercial General Liability (CGL): $1M per occurrence / $2M aggregate / $2M products-completed ops
  - Auto: $1M combined single limit
  - Workers' Comp: statutory + $1M Employers Liability
  - Umbrella: $5M–$25M per project risk
  - Professional Liability (if design responsibility): $1M–$5M
  - Pollution Liability (often required on geotech work): $1M–$5M
- **Additional Insured endorsements** — CG 20 10 (ongoing ops), CG 20 37 (products-completed ops), CG 20 38 (automatic AI for contractors).

### 4.5 Payment Terms and Retainage

- **Progress billings** — typically monthly on a schedule of values (SOV). AIA G702/G703 is the format.
- **Retainage** — 5% or 10% typical; reduces at 50% completion in some states; released at final payment.
- **Net payment terms** — AIA default 30 days from payment application. GC's back-to-back is often 10–15 days after GC receives owner payment.
- **Mechanic's lien rights** — strict deadlines (120 days from last work in most states for perfection, 90 days in some). Preserve lien rights by sending preliminary notices where required.
- **Prompt Payment Acts** — federal Prompt Payment Act (31 U.S.C. §3903) and state equivalents impose statutory interest on late payments from public owners.

### 4.6 Change Orders

- **Documentation trail**: RFI → written direction (CCD or signed CO) → Cost & Time proposal → signed change order. No written direction = no pay.
- **Pricing methods**: lump sum, unit price extension, T&M with NTE, cost + fixed fee.
- **Markup** on self-performed work is commonly capped at 15–20% O&P combined; on sub-tier work 5–10% O on the lower-tier sub's cost.
- **Cumulative impact claims** — when many changes collectively disrupt productivity beyond the sum of their individual costs. Documented via measured mile or industry-accepted disruption studies.

### 4.7 Liquidated Damages

- Pre-agreed daily amount for late completion. Must be a reasonable forecast of actual damages, not a penalty, to be enforceable.
- Typical: $500/day small jobs; $2,000–$10,000/day mid-size; $25K+ on highway and bridge work.
- Watch for **consequential damages waivers** — AIA A201 mutual waiver of consequentials is standard; removal is a red flag.

### 4.8 Differing Site Conditions (DSC)

- **Type I** — subsurface or latent physical conditions at the site differing materially from those indicated in the contract documents.
- **Type II** — unknown physical conditions of an unusual nature differing materially from those ordinarily encountered.
- **Federal standard FAR 52.236-2** is the model clause; AIA A201 §3.7.4 is the commercial version.
- **Notice requirements** — typically within 14 or 21 days of discovery. Written notice before disturbing the condition.
- For geotechnical subs, DSC claims usually turn on the **GBR** (if any) and the **geotechnical report** as baseline. A GBR that describes "rock at 25 ft" is a binding baseline; actual rock at 8 ft is a DSC.

### 4.9 Bid Process — Plan Rooms and Prequalification

- **Private plan rooms**: iSqFt, BidClerk, Dodge, ConstructConnect, Blue Book Network. Subscription-based. Post project documents and allow GCs/subs to download and signal interest.
- **Public plan rooms**: state DOT portals, local AGC plan rooms, municipal procurement pages.
- **Prequalification** — most public owners (and many private ones) require annual submittal of financial statements, safety records (EMR, DART rate), project experience, bonding capacity, and workforce. DOT prequalification is usually by work category ("Category 410 — Pile Driving", etc.) and is a go/no-go to bid.
- **MBE/WBE/DBE certification** — federal DBE (Disadvantaged Business Enterprise) is Unified Certification Program state-by-state; USDOT goals flow to state DOTs. MBE/WBE (Minority/Women-owned) are state and municipal certifications. Goals typically 5–15% of contract value.

### 4.10 Safety Metrics that Impact Work

- **EMR (Experience Modification Rate)** — actuarial comparison of a contractor's workers' comp claims to industry average. 1.00 = average; >1.00 = worse than average (higher premiums, often disqualified from bidding). <0.80 is excellent. Many GCs have a hard cutoff at 1.00 or 1.20.
- **DART rate** (Days Away, Restricted, or Transferred) — OSHA metric. Geotechnical/heavy construction industry average 2.0–3.5 per 100 FTE per year.
- **TRIR (Total Recordable Incident Rate)** — industry average ~3.5 for heavy construction.
- **Site-specific safety plans, Job Hazard Analyses (JHAs), pre-task plans**, OSHA 30-hour training for supervisors and 10-hour for laborers are table-stakes on most commercial work.

### 4.11 Claims and Dispute Resolution

- **Notice of claim** — every subcontract has a claim notice deadline (often 7, 14, or 21 days from the event). Miss it, waive the claim.
- **Continuing claims** — for ongoing impacts, supplement initial notice periodically.
- **Dispute resolution ladder** — typically: direct negotiation → mediation → arbitration (AAA Construction Industry Rules) OR litigation (forum selection clause governs).
- **Pass-through claims** — sub's claim against owner flows through GC under Severin doctrine limitations; liquidating agreement may be required.

---

## §5 — Geotechnical Construction Methods and Testing

### 5.1 Micropiles — Types and Grouting Classifications

Per NHI-05-039, micropiles are classified by grouting method. Classification drives design bond stress, installation cost, and testing protocol.

- **Type A** — gravity grouting only. Low bond capacity. Rare on new work.
- **Type B** — pressure grouting (typically 50–150 psi) during casing extraction. Most common for non-critical work.
- **Type C** — primary grout placed, then secondary grout injected ("postgrouted") at pressure through a separate tube before primary set. Used where high bond stress is required.
- **Type D** — multi-stage postgrouting through manchette sleeves (sleeved tubes à manchettes). Highest bond capacity; most expensive.

### 5.2 Micropile Drilling Methods

- **Rotary duplex** with air or water flush — casing and rod advanced together. Universal method for mixed ground.
- **Down-the-hole (DTH) hammer** — percussive drilling for rock. Fast in competent rock, slow in overburden.
- **Self-drilling hollow bar systems** — bar + sacrificial bit + grout flush; most common for soil nails and small micropiles in soil/weak rock. UMA uses GR80 hollow bar (T40/20, T52/26 from IDE and similar sources).
- **Auger / hollow-stem auger** — less common for micropiles but used for helicals and some underpinning.

### 5.3 Soil Nails — Types and Installation

- **Drilled-and-grouted (DG) nail** — casing advanced, bar inserted, grout tremied, casing withdrawn. Larger diameter (6"–12"), higher capacity per nail.
- **Self-drilling nail (SDN)** — hollow bar with sacrificial bit drilled to depth with grout flushing; bar stays in place. Faster, smaller diameter (2"–4"), lower per-nail capacity but often competitive on shorter installations.
- **Driven nail** — percussive, non-grouted or grouted after driving. Uncommon in current US practice.
- **Jet-grouted nail** — specialty application in soft clays.

Design per GEC-7: bar size, bond zone length, inclination (typically 15–20° below horizontal), spacing, facing. Centralizers required to maintain cover. Corrosion protection (epoxy, double corrosion protection) based on aggressivity classification (pH, chlorides, sulfates, resistivity).

### 5.4 Shotcrete — Wet vs Dry Mix

- **Wet mix** (pre-mixed, pumped, and sprayed) — better quality control, lower rebound (5–15%), preferred for structural shotcrete. ACI 506 and ACI 506R governs.
- **Dry mix** (gunite — dry materials conveyed pneumatically, water added at nozzle) — higher rebound (15–30%), but good for small patches and remote work.
- **Testing** — compressive strength cores per ASTM C1140, flexural strength beams, boiled absorption, rebound test panels, thickness probes, rebar cover survey.
- **Reinforcement** — welded wire fabric (WWF), rebar, or steel fibers (ASTM A820). Fiber-reinforced shotcrete is increasingly common.

### 5.5 Load Testing (ASTM Standards)

- **ASTM D1143 / D1143M** — Axial Compressive Load for Deep Foundations. Kentledge (dead weight), reaction pile, or anchored reaction frame. Quick test, slow test, constant rate of penetration. Design load typically 200% for proof, 100% for service.
- **ASTM D3689** — Axial Tensile Load. Hydraulic ram pulling against a frame on reaction piles or cribbing.
- **ASTM D3966** — Lateral Load. Jack between two piles or pile + deadman, dial gauges at top.
- **ASTM D4945** — High-Strain Dynamic Testing (PDA, Pile Driving Analyzer). Strain gauges and accelerometers on pile top, CAPWAP signal matching for capacity.
- **ASTM D5882** — Low-Strain Integrity Testing (PIT, Pile Integrity Test). Hand-held hammer taps pile top; accelerometer records reflection wave to detect defects.
- **ASTM D7949** — Thermal Integrity Profiling (TIP) for drilled shafts. Temperature sensors cast into reinforcing cage record hydration heat profile.
- **ASTM D6760** — Crosshole Sonic Logging (CSL) for drilled shafts. Ultrasonic pulse between access tubes detects defects.

### 5.6 Anchor Testing (Post-Tensioning Institute and FHWA GEC-4)

- **Performance Test** — on 1 of first 3 anchors + 2% of production; load in increments to 133% design load, record creep movement at each load.
- **Proof Test** — on all production anchors; single load cycle to 133% design load, creep at maximum load (10 min log).
- **Extended Creep Test** — at full test load, measure creep over 300–1000 minutes; apparent creep rate must be below threshold.
- **Lift-Off Test** — after lock-off, verify residual load.
- Acceptance criteria: elastic movement between theoretical min (tendon only) and max (tendon + 50% free length equivalent), total creep below limit (typically 1 mm in last log cycle).

### 5.7 Grout Quality Assurance

- **Mix design** — Portland cement + water + admixtures (sometimes fly ash, silica fume). w/c ratio 0.40–0.55 typical for structural grout. Neat cement grout common on micropiles.
- **Compressive strength** — ASTM C109 (2" cubes) or C942 (grout cylinders). Typical specs 4000–5000 psi at 28 days; 3000 psi at 7 days for proof testing.
- **Fluid properties** — flow cone (ASTM C939 or ASTM C1437), density (mud balance), bleed (ASTM C940).
- **Cube sampling frequency** — typical 1 set per 50 cubic yards or 1 per day minimum, 4 cubes per set (2 at 7 day, 2 at 28 day).

### 5.8 Polyurethane / Geopolymer Grouting

- **Polyurethane foam injection** (URETEK, Rhinoprobe) — for soil stabilization, slab lifting, void filling. Fast expansion, hydrophobic/hydrophilic variants.
- **Geopolymer resins** — similar application, higher strength than most polyurethane. Used for compaction and soil densification under foundations.
- **Chemical grouting** (sodium silicate, acrylamide — now rare) — permeation grouting of sands for water control and strength.

### 5.9 Ground Improvement (Common Alternatives to Piles)

- **Stone columns** — vibro-replacement with gravel; densifies and drains loose soils.
- **Deep Soil Mixing (DSM)** — in-situ blending of cement or binder with soil; creates columns or panels for excavation support and foundation improvement.
- **Jet grouting** — high-pressure grout jet erodes and mixes soil to create columns. Used under existing structures, water stops.
- **Vibro-compaction** — densification of clean sands via large depth vibrator.
- **Dynamic compaction** — drop-weight densification of loose granular fills.
- **Compaction grouting** — limited-mobility grout displaces and densifies soil.
- **Wick drains / PVDs (prefabricated vertical drains)** — accelerate consolidation of soft compressible soils.

### 5.10 Failure Modes and Field Warning Signs

- **Micropile**: debonding at steel–grout or grout–soil interface (load test creep failure), casing stuck at depth (drilling issue), grout loss into voids (karst, coarse fill).
- **Soil nail wall**: global instability (inadequate nail length/spacing/geometry), facing failure (undersized shotcrete/reinforcement), drainage failure (hydrostatic buildup behind face), progressive collapse from adjacent excavation.
- **Anchor**: bond zone creep, tendon failure at threads or couplers, freezing of extended creep test (exceed criteria = reject anchor, install replacement).
- **Shotcrete**: rebound pockets, laminations between lifts, inadequate rebar cover, cold joints.
- **Drilled shaft**: CSL anomalies (grout contamination, soft bottom, necking from squeezing clay), bottom sediment, slurry mismanagement.

### 5.11 Vendor and Material Notes

- **Steel bar** — GR80 (80 ksi) common for hollow bar; GR75 / GR150 for solid bars and tie rods. Source: IDE, DYWIDAG, Williams Form, Titan, Con-Tech. Lead time 2–6 weeks depending on size and grade.
- **Casing** — API 5L, flush-joint or threaded casing. Starter lengths 10'–20'. Common diameters 7", 7⅝", 9⅝" for micropiles; 4.5"–7" for soil nail drilling.
- **Cement** — Type I/II most common; Type III for high-early; Type V for high-sulfate soils. Bagged (94 lb) for small jobs, bulk for larger.
- **Admixtures** — non-shrink agents (intraplast N, aluminum powder), superplasticizers, accelerators, retarders.
- **Corrosion protection** — epoxy coating (ASTM A775 for rebar, A934 for fabricated), galvanizing (ASTM A123), double corrosion protection (DCP) encapsulation for critical anchors.

---

## §6 — Using This Knowledge in Estimates

When you deploy this knowledge in an estimate or analysis:

1. **Cite when it matters** — if the user's bid specs an unfamiliar standard, cite the FHWA GEC, ASTM, or AASHTO reference in the assumptions. This builds credibility and flags what design intent you're pricing.
2. **Defer to UMA's institutional numbers** — when UMA's `system.md` has a specific vendor, productivity, or pricing benchmark, that wins over generic industry data.
3. **Use generic data to sanity-check** — if UMA's productivity number looks way off industry norm, flag it for Tony's review. Don't silently "correct" UMA data.
4. **Never fabricate a citation** — if you're unsure which standard governs, say so and recommend Tony verify.
5. **State-specific risk** — always check state law for pay-if-paid, licensing, lien, and prevailing wage before closing an estimate. The states UMA operates in (VA, NC, SC, MD, DC, FL) have meaningfully different rules.
6. **The bid docs are authoritative** — if the specs conflict with anything in this knowledge pack, the specs win for that bid. Flag the conflict in clarifications.
