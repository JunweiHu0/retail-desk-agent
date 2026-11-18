# Retail guide selection

The `guide` and `enhanced` variants load `retail_seed.md` by default. It is a
policy-derived static seed, not a learned guide or evidence of improved results.

Set `AGENT_GUIDE_PATH` to select a separately versioned guide file. Absolute paths
are accepted; relative paths resolve from the repository root. For example:

```bash
export AGENT_GUIDE_PATH=/vePFS/han/retail-desk/guides/dev-feedback-v1.md
```

The episode manifest records the selected file's name, SHA-256, source and
provenance label. Custom files are labelled operator-selected with unverified
learning provenance; selecting a file does not establish that it was learned or
that it improves performance. Record development evidence separately, then freeze
the selected file and its hash before evaluation. Other variants do not read the
guide.
