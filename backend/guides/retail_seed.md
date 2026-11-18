Retail operational guide — policy/application-derived seed, version 2

Provenance: public Retail policy and the application's approval contract, with
clarifications from UI integration checks. No target DB, reference action, task
identifier or task-specific answer is included. This is a human-written static
seed, not an automatically learned guide and not evidence of improved results.
Freeze this file's hash before a comparison.

Check the observed order status before selecting a mutation. Pending orders
support permitted modifications; delivered orders support returns and exchanges.
Retrieve product variants when the requested replacement is not known. Use actual
item ids and payment method ids from observations; never silently replace them.

Translate policy confirmation to this application's confirmation card. Once the
customer's desired operation and all required arguments are known, call the write
tool to create its preview. Do not demand a separate chat "yes" before creating a
preview: it does not execute anything. The card's explicit approve/reject decision
is the execution authorization. Never bypass that decision or infer approval.

Collect the complete item selection and address/reason/payment choices; group
items as required by policy. If the customer asks for information needed to make
a decision (refund amount, eligible items or payment choices), answer that question
using observations or tools before repeating procedural explanations.

Keep every unfinished request, including distinct account and order changes.
After an executed receipt, that exact action is complete: do not ask for its
approval again. Continue the remaining requests. A rejected receipt is not
execution or permission to repeat the same proposal.

When a requested operation violates policy, explain the permitted choices. If the
customer insists on an unsupported operation or asks for a human, use the actual
human-transfer tool rather than repeating the same confirmation question.
