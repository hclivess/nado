# NADO governance — the human layer (addendum to [treasury.md](treasury.md))

> **Status: DRAFT / policy proposal.** [treasury.md](treasury.md) defines the *money* — how treasury funds are
> approved (bonded-stake quorum) and forced out of hoarding (self-burn). This addendum defines the *people* —
> how NADO shows up in the world, engages a community and its influencers, and does so **transparently enough
> that funding growth never becomes the scandal.** Every spend it describes flows through the same quorum +
> milestone-escrow + public-report machinery as any other treasury spend.

## 0. Why this exists — the Bismuth post-mortem (social, not technical)

Bismuth's *technical* substance was sound. What backfired was **social**, and it is worth stating plainly so we
design against it:

- **Founder absence.** The founder did not participate consistently in the community. In crypto, silence is not
  neutral — it is read as *abandonment* or *hiding something*. A project that isn't visibly present looks dead
  or dishonest, regardless of the code.
- **Alienated KOLs.** Influencers / key opinion leaders who were not engaged felt **left out**, and some turned
  publicly hostile (e.g. CryptoMessiah). An ignored influencer is not a neutral party — they become a motivated
  critic, and their audience inherits the grudge.
- **The snap "scam" verdict.** A respected figure (Andreas Antonopoulos) pattern-matched the project to "scam"
  and denounced it publicly — with no relationship, no context, and no legible public record to correct the
  impression. The judgment was arguably inconsistent (the same period saw louder support for far weaker projects
  such as 42coin), but **that is the point**: reputational judgments in this space are fast, sticky, asymmetric,
  and often unfair, and a project with **no relationships and no legible anti-scam dossier has no way to answer
  them.**

The cruel irony: a **fair-launch, no-premine** chain has the *strongest* anti-scam substance that exists and
the *weakest* default distribution — no marketing war chest, no insiders, no relationships, no one whose job is
to show up. So it is uniquely exposed to exactly these failures. The lessons:

1. **Show up.** Founder + team must be visibly, consistently present. Absence is fatal.
2. **Be legible.** Over-communicate the fair-launch substance and make it trivially checkable, so a skeptic can
   verify in minutes instead of guessing "scam."
3. **Build relationships before you need them.** Engage KOLs and respected neutrals as peers/reviewers early —
   an included critic argues with you, an excluded one argues about you.
4. **Fund growth transparently.** The treasury *is* the distribution budget a fair launch otherwise lacks — but
   paying for reach is what got Bismuth *accused*, so it must be on-chain, disclosed, deliverable-based, and
   quorum-approved. Transparent sponsorship is legitimate; covert shilling is the poison.

## 1. Principles

- **Presence over polish.** Consistent, honest, human presence beats occasional slick announcements.
- **Legibility as the anti-scam shield.** The defense against "is this a scam?" is a public, checkable record,
  not indignation.
- **Relationships before transactions.** Engage people as reviewers/collaborators first; money second.
- **Transparency converts shilling into sponsorship.** Every growth dollar is a public, quorum-approved,
  disclosed, deliverable-based proposal. Nothing covert.
- **Inclusion, not in-groups.** Favoritism creates the exact left-out resentment that turned KOLs hostile.
  Publish neutral criteria so no one is arbitrarily excluded.
- **Fund the commons, not favorites.** Recurring, criteria-based programs over one-off backroom deals.

## 2. The KOL / influencer problem (the hard one)

The paradox that sank Bismuth from both sides: you **need** influencers for distribution, but **paying** them
looks like shilling/scam (the accusation), and **ignoring** them makes them feel snubbed and hostile (the other
accusation). The resolution is not to pick a side — it is to change the structure so that engagement is
**transparent, relationship-first, and scrutiny-inviting**:

- **On-chain, disclosed, deliverable-based sponsorship.** Every KOL engagement is a public `treasury_spend`
  proposal (recipient, amount, deliverables, **mandatory disclosure clause**) voted by the bonded lane. It is
  auditable on-chain. It is *sponsorship on the record*, never a secret payment.
- **Mandatory disclosure, enforced.** The recipient must disclose the sponsorship (clear "#ad / sponsored by
  the NADO treasury, proposal #N"). Non-disclosure → clawback + blacklist. Disclosed sponsorship is legitimate;
  hidden paid hype is the toxic thing that gets projects branded scams.
- **Fund review, not just hype.** Prefer engagements that ask a KOL to *genuinely evaluate* NADO — even
  critically — over pure promotion. "We paid a skeptic to test our phone-mining + PQ + shielded pool and say
  what they really think" is credible *because* it invites scrutiny; a paid hype video is not. An honest,
  disclosed critique is worth more than ten shill posts.
- **Engage before asking.** Give access, answer the hard questions, invite KOLs and respected neutrals to test
  the actual product early — make them feel like early reviewers/insiders, not afterthoughts. This is the direct
  fix for the "left out → hostile" failure.
- **Tiered programs:** micro-grants for genuine content, bounties for tutorials/integrations/tools, and a small
  number of standing **ambassador** roles (regional/by-language — ties to the interface's 16 languages).

### 2.1 Preempting the snap "scam" verdict

You cannot stop a respected figure from a fast judgment, but you can make the judgment easy to get *right* and
easy to *correct*:

- **Keep a public "why this isn't a scam" dossier** — one page, always current: no premine (`TREASURY_GENESIS =
  0`, verifiable on-chain), open-source code, treasury on-chain and quorum-governed, team identifiable and
  reachable, no paid pumping, no fake volume. Substance a skeptic can check in five minutes.
- **Proactively brief respected neutrals** — offer a walkthrough and verification *before* asking for anything.
  A relationship (even a skeptical one) is what lets you answer a wrong "scam" label; Bismuth had none.
- **Never look like you're hiding.** No anonymous accounts pumping, no wash trading, no astroturf. The instant a
  fair-launch project *behaves* like a scam to buy short-term attention, it forfeits its one real advantage.
- **Answer criticism with substance and humility, never with attacks.** Getting defensive is what converts a
  skeptic into an enemy — the pattern to break.

## 3. Conventions, conferences & standards (paid legitimacy channels)

Reputable industry events and standards/interop venues are legitimate, relationship-building, credibility-buying
channels — and NADO has a genuinely strong, non-hype angle to bring: **post-quantum, fair-launch, phone-mineable,
private.** Fund (transparently, via quorum, ROI-throttled):

- **Founder/team physical presence** at reputable conferences — being in the room, talking to people, is exactly
  the participation whose *absence* hurt Bismuth.
- **Sponsorship of credible events** (selective — reputable venues, not pay-to-play scam-adjacent ones).
- **Engagement with PQ-crypto / interop communities** where NADO's ML-DSA-44 substance is real and checkable —
  the strongest possible counter to "scam," because it is a technical claim experts can verify.

## 4. Founder & team participation (the direct fix)

- **Be present, consistently.** Regular public updates, open AMAs, reachable channels, visible responsiveness to
  criticism. This is non-negotiable — it is the single biggest Bismuth lesson.
- **Distribute the voice.** Don't make NADO a one-person show — it is a single point of failure, a burnout risk,
  and a "cult of founder" optics problem. Build a team + ambassadors with real, named roles.
- **Model the culture.** Humility, transparency, and engaging critics in good faith set the community's tone.

## 5. Community structure & roles

- **Venues:** the public forum + chat (Discord today), with **transparent decision records** (proposals,
  tallies, outcomes — much of it already on-chain via the Quorum tab).
- **Roles:** core team; contributors (paid via treasury proposals, Monero-CCS milestone escrow); ambassadors
  (regional/by-language); moderators; an optional **advisory grants/community committee** (vetting + surfacing
  proposals — advisory only; the bonded-stake vote is always the authority).
- **Onboarding is the product.** The phone-mineable interface *is* the funnel: open a link → you're a
  participant → you share it. The growth model is the interface's shareability, not paid acquisition.
- **Code of conduct + neutrality.** Published, enforced, and explicitly anti-favoritism (the left-out-resentment
  guard).

## 6. How the human layer ties to the treasury quorum

Everything above spends money, so it all runs through the machinery in [treasury.md](treasury.md):

- Each community / KOL / event / marketing spend is a **`treasury_spend` proposal → bonded-stake quorum vote →
  milestone escrow → public completion report.** Same rails as core dev.
- That governance *is* the safety: a KOL payment that a stake quorum approved in public, with disclosure and
  deliverables, is structurally not a backroom shill deal — which is precisely what makes it credible instead of
  scandalous.
- For recurring work (an ambassador program, ongoing community/KOL outreach), use a **standing bounty**: the
  quorum approves a capped lump once and delegates payouts to an accountable **curator** under public reporting
  (Polkadot's parent/child-bounty pattern), so governance isn't voting on every micro-grant.

## 7. Accountability & anti-capture (social)

- **Disclosure** required and enforced (KOL sponsorships labeled; non-disclosure → clawback + blacklist).
- **Deliverable-based, nothing upfront** (Monero-CCS escrow) — no pay for vapor.
- **Clawback + blacklist** for non-disclosure, non-delivery, or fraud.
- **Public reporting** — who was paid, for what, and did it deliver: a neutral "Community Watch" (Dash had the
  idea as Dash Watch; Dash's failure was that it had no teeth — give ours teeth via on-chain clawback).
- **Neutral, published criteria** for who gets funded, so exclusion is never arbitrary (the resentment guard).

## 8. What "working" looks like (measure honestly)

Track *real* engagement, not vanity metrics, and ROI-throttle spend against it (per [treasury.md](treasury.md)
§3.4): active/retained miners, genuine (disclosed) content and its attributable reach, integrations shipped,
respected-neutral sentiment, and turnout in the Quorum tab. Scale marketing/KOL spend only *after* attribution
shows return — the guard against the Polkadot "$37M for ~1.5% coverage" outcome.

## 9. Open decisions for the owner

- **Community/KOL/events allocation:** what share of deployed treasury goes here vs core dev (a starting target
  lives in [treasury.md](treasury.md) §3.1 — Growth 20% + Community 5%).
- **KOL vetting:** reputation + disclosure-history criteria; whether to require prior disclosed-sponsorship track
  records.
- **Ambassador program:** stand one up from day one, or wait until turnout/community depth justifies it.
- **The founder's own presence plan:** the most important and least delegable item — a concrete, sustainable
  cadence of showing up, because this is the lesson Bismuth paid for.
