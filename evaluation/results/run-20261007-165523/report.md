# SmartLogix - Evaluation Results

- Run: `run-20261007-165523`  |  Model: `openai/gpt-oss-20b`  |  Commit: `65dcb9f`
- Suites: intake, retrieval, injection, resolution

## 1. Intake Agent - NLU (issue classification + entity extraction)

| Metric | Result |
|---|---|
| Issue-type accuracy | 97.6% (n=42, 95% CI 87.7%-99.6%) |
| Issue-type macro-F1 | 0.981 |
| Order-ID exact match | 100.0% (n=42, 95% CI 91.6%-100.0%) |
| Order-ID hallucination rate (no ID in message) | 0.0% (n=19, 95% CI 0.0%-16.8%) |
| Blocked by sanitizer (all benign) | 0 |
| LLM errors | 0 |

**Per class**

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| damaged | 0.89 | 1.00 | 0.94 | 8 |
| late | 1.00 | 1.00 | 1.00 | 8 |
| lost | 1.00 | 1.00 | 1.00 | 6 |
| wrong_address | 1.00 | 1.00 | 1.00 | 5 |
| policy_question | 1.00 | 0.86 | 0.92 | 7 |
| new_quote | 1.00 | 1.00 | 1.00 | 4 |
| other | 1.00 | 1.00 | 1.00 | 4 |

**Confusion matrix**

| true \ predicted | damaged | late | lost | wrong_address | policy_question | new_quote | other |
|---|---|---|---|---|---|---|---|
| **damaged** | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| **late** | 0 | 8 | 0 | 0 | 0 | 0 | 0 |
| **lost** | 0 | 0 | 6 | 0 | 0 | 0 | 0 |
| **wrong_address** | 0 | 0 | 0 | 5 | 0 | 0 | 0 |
| **policy_question** | 1 | 0 | 0 | 0 | 6 | 0 | 0 |
| **new_quote** | 0 | 0 | 0 | 0 | 0 | 4 | 0 |
| **other** | 0 | 0 | 0 | 0 | 0 | 0 | 4 |

## 2. Policy Agent - Information Retrieval (ChromaDB)

27 labelled queries, 32 indexed chunks; relevance judged at document level.

| k | Precision@k | Recall@k | Hit@k | Heading-only chunks in top-k |
|---|---|---|---|---|
| 1 | 1.000 | 0.926 | 1.000 | 3.7% |
| 3 | 0.778 | 1.000 | 1.000 | 3.7% |
| 5 | 0.622 | 1.000 | 1.000 | 5.2% |

**MRR:** 1.000

## 3. Security - Prompt-injection filter

30 attack prompts, 30 benign prompts (including benign messages that share wording with attacks).

| Metric | Result |
|---|---|
| Block rate (recall on attacks) | 50.0% (n=30, 95% CI 33.2%-66.8%) |
| False-positive rate (benign blocked) | 23.3% (n=30, 95% CI 11.8%-40.9%) |
| Precision | 0.682 |
| F1 | 0.577 |
| TP / FP / TN / FN | 15 / 7 / 23 / 15 |

| Attack category | Block rate |
|---|---|
| code_injection | 66.7% (2/3) |
| direct_override | 80.0% (4/5) |
| embedded | 33.3% (1/3) |
| jailbreak | 100.0% (3/3) |
| multilingual | 0.0% (0/3) |
| obfuscation | 0.0% (0/4) |
| prompt_extraction | 50.0% (2/4) |
| role_play | 60.0% (3/5) |

Missed attacks: A04, A08, A09, A13, A14, A20, A21, A22, A23, A24, A26, A27, A28, A29, A30  
False positives: B03, B04, B05, B06, B07, B08, B09

## 4. Investigation + Resolution Agents - decision quality

28 real orders (stratified by Damaged / Delayed / Lost status). Reference fault labels follow the policy documents and the data generator's causal rules.

| Metric | Result |
|---|---|
| Fault-attribution accuracy | 100.0% (n=28, 95% CI 87.9%-100.0%) |
| Fault macro-F1 | 1.000 |
| Refund-decision accuracy | 100.0% (n=28, 95% CI 87.9%-100.0%) |
| Escalated to human | 32.1% (n=28, 95% CI 17.9%-50.7%) |
| LLM reply consistent with decision (before guard) | 100.0% (n=28, 95% CI 87.9%-100.0%) |
| Final reply consistent with decision (after guard) | 100.0% (n=28, 95% CI 87.9%-100.0%) |
| Template fallback used | 0.0% (n=28, 95% CI 0.0%-12.1%) |
| Late orders blamed on packaging (should be 0) | 0.0% (n=10, 95% CI 0.0%-27.8%) |
| LLM errors (investigation / resolution) | 0 / 0 |

| Issue type | Fault accuracy | Decision accuracy |
|---|---|---|
| damaged | 100.0% (n=10, 95% CI 72.2%-100.0%) | 100.0% (n=10, 95% CI 72.2%-100.0%) |
| late | 100.0% (n=10, 95% CI 72.2%-100.0%) | 100.0% (n=10, 95% CI 72.2%-100.0%) |
| lost | 100.0% (n=8, 95% CI 67.6%-100.0%) | 100.0% (n=8, 95% CI 67.6%-100.0%) |

**Fault confusion matrix**

| true \ predicted | warehouse | courier | weather | customer | unclear |
|---|---|---|---|---|---|
| **warehouse** | 5 | 0 | 0 | 0 | 0 |
| **courier** | 0 | 13 | 0 | 0 | 0 |
| **weather** | 0 | 0 | 1 | 0 | 0 |
| **customer** | 0 | 0 | 0 | 0 | 0 |
| **unclear** | 0 | 0 | 0 | 0 | 9 |

## Notes on validity

- Test sets are small and hand-written by the team; the 95% confidence intervals (Wilson) show how much each number could move.
- All order data is synthetic (data/generate_data.py, fixed seed).
- The injection suite measures the pattern filter only, not how the LLM behaves when an attack gets past it.
