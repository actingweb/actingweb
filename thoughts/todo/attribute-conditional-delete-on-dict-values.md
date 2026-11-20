# `delete_attr_if_data_equals` on a dict value

**Filed:** 2026-11-19, by `thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md` (the consumer's A10).

The DynamoDB backend compares the stored value as a string
(`db/dynamodb/attribute.py`, `delete_attr_if_data_equals`); whether a dict
value compares canonically (key order, the JSON normalisation `normalize_json`
applies on write) is unverified on both backends. A consumer's comments
feature wants a conditional delete of a dict attribute. First: a test of a
dict written and conditionally deleted with its keys in another order, on
both backends; then a canonical compare if it fails.
