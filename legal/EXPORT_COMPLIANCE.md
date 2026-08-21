# Export-Control and Cryptography Notice

**Last updated: 2026-08-21**

NADO contains and uses cryptographic software:

- **ML-DSA-44** (FIPS 204) post-quantum digital signatures (`signatures.py`,
  `native/mldsa44`, `dilithium-py`)
- **zk-STARK / FRI** proof systems (`execnode/stark`, `native/starkprove`,
  `native/starkcompose`)
- Hash functions (BLAKE2b, SHA-3/Keccak, the project's `alghash2` sponge)
- End-to-end encryption for on-chain messaging and a shielded transfer pool

## United States (EAR)

This is **publicly available** open-source software. Under the U.S. Export Administration
Regulations, publicly available encryption source code (and corresponding object code) is
**not subject to the EAR** once the notification in 15 CFR §742.15(b) has been made, or is
eligible for **License Exception ENC** / classified under **ECCN 5D002** as applicable. The
source code is published at the project's GitHub repository and is therefore "publicly
available" within the meaning of 15 CFR §734.3(b)(3) / §734.7.

*(Maintainers: if you are a U.S. person or the repository is hosted from the U.S., send the
one-time email notification of the repository URL to `crypt@bis.doc.gov` and
`enc@nsa.gov` per §742.15(b), and record the date here.)*

## Other jurisdictions

The import, possession, use and/or re-export of encryption software may be **restricted or
prohibited** in some countries (e.g. under the Wassenaar Arrangement as implemented
locally, or national laws in China, Russia, Iran, and others). **Before downloading, using
or redistributing NADO, check the laws of your country.** See
<https://www.wassenaar.org/> and <https://www.bis.doc.gov/> for more information.

## Sanctions

You may not use, download or redistribute this software if you are, or are acting on behalf
of, a person or entity on a U.S., EU, UK or UN sanctions list, or if you are located in a
comprehensively embargoed territory, where doing so would violate applicable law. The
software is a neutral tool published by its authors; the authors do not control who
downloads it from public mirrors and disclaim responsibility for unlawful use.

## No cryptographic warranty

The cryptography has **not** been independently audited. Implementations may contain bugs
(including side channels) that compromise the security properties claimed in `doc/`. Do not
rely on it to protect information or value of consequence.
