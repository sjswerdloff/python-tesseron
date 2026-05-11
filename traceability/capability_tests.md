# Capability Negotiation Test Specifications

Source: Spec §12 Capability Negotiation, §5 Handshake, §19 Acceptance Scenario

## Capability Intersection Tests (§12.1-12.2)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| CP-01 | App declares capabilities in tesseron/hello | Verify hello params include capabilities object |
| CP-02 | Gateway returns intersection in welcome.capabilities | App requests {sampling, streaming}, gateway supports {streaming}, welcome has {streaming: true, sampling: false} |
| CP-03 | Handler MUST trust intersection, not app-declared capabilities | App declares sampling, gateway doesn't support it, verify ctx.agent_capabilities.sampling is False |
| CP-04 | All four capabilities independently negotiable | Test each: streaming, subscriptions, sampling, elicitation |

## Capability Update Tests (§12.3, Acceptance Scenario 19)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| CP-05 | tesseron/claimed updates agentCapabilities | Welcome has sampling=false, claimed has agentCapabilities.sampling=true, verify update |
| CP-06 | Handlers invoked after claimed see updated capabilities | Invoke action after claimed, verify ctx.agent_capabilities reflects claimed values |
| CP-07 | Capabilities before claimed reflect welcome values | Invoke action before claimed (if possible), verify welcome capabilities |

## Capability Gating Tests (Acceptance Scenario 12)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| CP-08 | ctx.agent_capabilities.sampling queryable before calling ctx.sample() | Check capability, take fallback path, no error |
| CP-09 | ctx.agent_capabilities.elicitation queryable before calling ctx.elicit() | Check capability, take fallback path, no error |
| CP-10 | Fallback path works when capability absent | Handler checks, takes fallback, returns valid result |
| CP-11 | Happy path works when capability present | Handler checks, uses ctx.sample(), returns result |

## Sampling Depth Tests (§9)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| CP-12 | maxSamplingDepth defaults to 3 if not specified | Verify default |
| CP-13 | Exceeding maxSamplingDepth returns -32008 | Chain 4 sampling calls, verify error on 4th |
