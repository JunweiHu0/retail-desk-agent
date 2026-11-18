Retail operational guide — policy-derived seed, version 1

Provenance: derived from the full Retail policy and the web application's approval
contract. This is a static seed, not guidance learned from benchmark failures, and
has no measured performance claim. Development feedback may produce a separately
versioned revision; freeze its hash before evaluation.

Check the observed order status before selecting a mutation. Pending orders support
cancellation and permitted modifications; delivered orders support returns and
exchanges. Retrieve product variants when the requested replacement is not yet
known. Use the actual item ids and payment method ids from observations.

Collect the customer's complete item selection and the required address, reason,
or payment/refund choice before staging a write. Group all selected items into the
single item-modification or exchange request required by the policy. A preview is
not a completed operation. After the application receipt, continue any remaining
customer requests. If a tool reports an error, inspect the observation and request
missing information or make the next justified tool call; never invent a result.
