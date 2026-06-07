# Property Investment Research Spec

## Goal

Investment research must read like underwriting, not generic commentary.

## Required sections

- purchase price
- expected rent
- gross yield
- net yield estimate
- operating cost sensitivity
- vacancy assumption
- renovation and capex risk
- liquidity and resale risk
- regulatory risk
- auction or legal risk
- comparable evidence
- missing documents
- bid or no-bid recommendation

## Claim structure

Every investment claim should carry:

- value
- confidence
- source
- assumption
- sensitivity

## Required output pattern

Example structure:

```text
Investment read
Recommendation: investigate further
Confidence: medium

Base case
- Purchase price
- Expected rent
- Gross yield
- Net yield range

Sensitive assumptions
- operating costs
- regulation
- capex
- liquidity

Next action
- ask for documents
- confirm missing facts
- decide whether to continue
```

## Decision-loop integration

Investment research must connect back into the main property loop:

- `No` because yield is weak -> preference and suppression signal
- `Maybe` because operating costs are unclear -> follow-up task
- `Ask agent` should produce concrete underwriting questions

## Testing

Required tests should cover:

- underwriting sections present in packet
- provenance/confidence visible
- missing-document prompts visible
- browser path from shortlist to investment packet
- contract coverage for the current recommendation and next action
