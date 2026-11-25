# Spec: Store faults

**Status:** partial (covers: behaviour changed since 2026-11-23)
**Reviewed:** 2026-11-23 by Greger Wedel (with the plan)
**Last changed:** 2026-11-25 by thoughts/plans/2026-11-25-attribute-compare-and-delete.md
**ID prefix:** SFT

## Summary

A store fault is a `DbError`: the database backend could not answer. This
partial spec covers how a fault is classified for an application and for
the HTTP answer, the strict mode of the conditional attribute update, and
the conditional attribute compares (JSON value equality, the public
compare-and-delete, values the store refuses).
The rest of the fault contract is in `docs/reference/database-backends.rst`
and `docs/migration/v4.0.rst` ("fault contract") until it is written here.

## Classification

- **SFT-1** — `actingweb.faults.classify_fault()` names a store fault's
  class (retryable, stored, permanent, conflict) and retry delay, follows
  `raise ... from` up to five links, and answers `None` for anything else;
  the integrations' HTTP answers are derived from it. [plan+test]
  `tests/test_public_fault_classifier.py` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-10, AC-11)
- **SFT-2** — `AttributeKeyCollision` is permanent: HTTP 500 without
  `Retry-After`. [plan+test]
  `tests/test_db_fault_http.py::TestFlask::test_a_key_collision_answers_500_without_retry_after`, `::TestFastAPI::test_a_key_collision_answers_500_without_retry_after` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-9)

## Conditional writes

- **SFT-3** — `conditional_update_attr` answers `False` on a fault by
  default. With `strict=True` a store fault raises `DbError` chained to the
  backend's exception, and `False` means the condition did not hold: the
  row holds something other than `old_data` by JSON value equality (a
  stored `true` is not `1`; the same value another writer wrote included),
  there is no row, or another bucket holds the key. In
  neither mode does `False` prove the write did not land. [plan+test]
  `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-16 to AC-18, AC-28, AC-29)
- **SFT-4** — With `strict=True`, a caller's value that JSON cannot order
  or encode, a non-finite number included, raises `TypeError` or `ValueError` before the store is touched;
  an exception inside the backend is a `DbError` whatever its type.
  [plan+test] `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate::test_a_value_that_cannot_be_compared_is_not_an_outage`, `::test_a_store_side_value_error_is_still_a_fault` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-33); `::test_a_non_finite_old_value_is_not_an_outage` (plans/2026-11-25-attribute-compare-and-delete.md, AC-27)
- **SFT-5** — `Attributes.delete_attr_if_data_equals(name, expected)`
  deletes the row only while it holds `expected`. True: this call deleted
  it. False: the row holds something else, there is no row, or another
  bucket holds the key. A store fault raises `DbError` chained to the
  backend's exception, never False. As with SFT-3, a False does not prove
  the delete did not land. [plan+test] `tests/test_attribute_compare_and_delete.py::TestPublicCompareAndDelete` (plans/2026-11-25-attribute-compare-and-delete.md, AC-1, AC-5 to AC-8, AC-12, AC-17)
- **SFT-6** — Before the store is touched, an `expected` JSON cannot
  encode (a circular value and a non-finite number included) raises
  `UnserialisableValue`, and a missing name raises `ValueError`. [plan+test]
  `::test_a_value_json_cannot_encode_is_refused`, `::test_a_non_finite_number_is_refused`, `::test_a_missing_name_is_refused`, `::TestIterationThree::test_a_circular_value_is_refused_as_unserialisable` (plans/2026-11-25-attribute-compare-and-delete.md, AC-10, AC-11, AC-19, AC-37)
- **SFT-7** — On an `Attributes` instance whose bucket is loaded,
  `delete_attr_if_data_equals` leaves no stale entry: after True,
  `get_attr(name)` answers absent; after False or a raise, the next
  `get_attr(name)` reads the store. [plan+test] `::test_a_deleted_row_is_absent_on_a_loaded_instance`, `::test_a_fault_unloads_the_cached_entry`, `::test_a_loss_unloads_the_cached_entry` (plans/2026-11-25-attribute-compare-and-delete.md, AC-2, AC-9, AC-18)
- **SFT-8** — Every conditional attribute compare (`conditional_update_attr`,
  `create_attr_if_absent`'s read-back, `delete_attr_if_data_equals`,
  `set_attr_if_data_equals`) uses JSON value equality on both backends:
  key order and number spelling do not matter, an int and a float compare
  as the decimals their JSON text names, and booleans, numbers, strings
  and null are distinct. [plan+test] `::test_key_order_does_not_matter`, `::test_a_float_matches_an_equal_integer`, `::test_true_is_not_one`, `::TestBackendCompare`, `::TestIterationThree::test_large_numbers_compare_as_jsonb_does`, `tests/test_conditional_update_attr.py::TestConditionalUpdateAttrJSONComparison::test_true_is_not_one` (plans/2026-11-25-attribute-compare-and-delete.md, AC-3, AC-4, AC-13, AC-15, AC-16, AC-22 to AC-24, AC-36)
- **SFT-9** — A row that stores null matches `None` in every conditional
  attribute compare, on both backends. [plan+test] `::test_a_null_row_matches_none`, `tests/test_conditional_update_attr.py::TestConditionalUpdateAttrJSONComparison::test_a_null_row_matches_none` (plans/2026-11-25-attribute-compare-and-delete.md, AC-17, AC-25)
- **SFT-10** — A value in `expected` or `old_data` is compared as its JSON
  encoding: a tuple is a list and an int key is its string. [plan+test] `::test_a_tuple_and_an_int_key_match`, `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate::test_strict_compares_as_the_backend_does` (plans/2026-11-25-attribute-compare-and-delete.md, AC-20)
- **SFT-11** — A lone surrogate in `expected` is replaced before the
  compare, as it is before a write. [plan+test] `::test_a_surrogate_in_expected_is_not_a_fault` (plans/2026-11-25-attribute-compare-and-delete.md, AC-21)
- **SFT-12** — Every attribute write whose data holds a non-finite number
  raises `UnserialisableValue` before the store is touched, on both
  backends. List items are not covered: a list stores each item as a
  string. [plan+test] `tests/test_unserialisable_value.py::test_a_non_finite_number_is_refused_before_the_store`, `::test_a_list_item_is_not_attribute_data` (plans/2026-11-25-attribute-compare-and-delete.md, AC-26)
- **SFT-13** — A `conditional_update_attr` whose row is deleted before its
  write answers False and creates no row; a conditional write never
  matches a row at its key whose `name` differs. [plan+test] `tests/test_conditional_update_attr.py::TestConditionalUpdateAttrJSONComparison::test_a_null_row_deleted_before_the_write_stays_gone`, `tests/test_attribute_compare_and_delete.py::TestIterationThree::test_a_row_under_another_name_is_not_deleted` (plans/2026-11-25-attribute-compare-and-delete.md, AC-28, AC-38)
- **SFT-14** — A value whose one key is a DynamoDB type name (`{"S": "x"}`)
  is compared and stored like any other value. [plan+test] `::TestValuesNamedLikeDynamoDBTypes` (plans/2026-11-25-attribute-compare-and-delete.md, AC-32)
- **SFT-15** — On DynamoDB, the deletes read only a row's keys, so a row
  whose data cannot be read back can be deleted. [plan+test] `::TestRowsTheOldUpdateCorrupted` (plans/2026-11-25-attribute-compare-and-delete.md, AC-40)

## Replica values the store refuses

- **SFT-16** — A replica deletes a key whose new value it cannot store (a
  peer's non-finite value). The key answers `refused`, the rest of the
  callback or baseline is applied, the key is not marked out of step, and
  it does not keep a rebuild owed. [plan+test] `tests/test_remote_storage_non_finite.py::test_a_non_finite_scalar_is_skipped_and_the_rest_applied`, `::test_a_non_finite_scalar_in_a_baseline_does_not_keep_a_rebuild_owed`, `::test_a_refused_value_does_not_leave_the_old_one`, `::test_a_list_replaced_by_a_refused_scalar_is_gone` (plans/2026-11-25-attribute-compare-and-delete.md, AC-29, AC-30, AC-33, AC-34)
- **SFT-17** — At a resource path, a refused value deletes only that path,
  where it exists, and creates or replaces no parent; the property's other
  paths stay. A stored property JSON cannot hold (written before the
  refusal) is replaced by the next resource write, and deleted by a refused
  one. [plan+test] `::test_a_refused_resource_value_drops_only_its_path`, `::test_a_refused_resource_value_creates_and_replaces_nothing`, `::test_a_resource_write_into_a_legacy_nan_property_replaces_it` (plans/2026-11-25-attribute-compare-and-delete.md, AC-35, AC-39, AC-41)
- **SFT-18** — A revocation whose rewrite of a scalar cannot be stored
  deletes that name whole. [plan+test] `::test_a_rewrite_that_cannot_be_stored_deletes_the_name` (plans/2026-11-25-attribute-compare-and-delete.md, AC-31)

## Decisions in force

- **SFT-D1** — The default of `conditional_update_attr` does not raise.
  (plans/2026-11-01-single-mode-and-consumer-primitives.md, D10)
- **SFT-D2** — `actor.store` folds a failed read; `loaded` is its signal.
  (plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md)
- **SFT-D3** — Strict is the backends' to decide, not a re-read above them:
  only the backend knows why its write did not happen. (plans/2026-11-23-emm-4-0-rc2-production-observations.md, iteration 1)
- **SFT-D4** — On DynamoDB, a compare by value is a consistent read, then a
  write conditioned on the stored data; a string `expected` keeps a single
  conditional write, so list storage pays no extra read. (plans/2026-11-25-attribute-compare-and-delete.md)
- **SFT-D5** — The public compare-and-delete has no folding mode: like
  `create_attr_if_absent`, a fault always raises. (plans/2026-11-25-attribute-compare-and-delete.md)
- **SFT-D6** — A custom attribute backend must compare `*_if_data_equals`
  by JSON value; the docs state it and no parity test enforces it. (plans/2026-11-25-attribute-compare-and-delete.md)
- **SFT-D7** — `\u0000` in `expected` is not refused: PostgreSQL raises
  `DbError` for it, DynamoDB stores and matches it. The replica fails
  closed on a value it cannot store (owner, 2026-11-25). (plans/2026-11-25-attribute-compare-and-delete.md)

## Untested

- SFT-3: a write that landed and whose answer was lost (`False` or a
  `DbError` for a write that is stored) is documented, not tested;
  `todo/conditional-write-ambiguous-after-sdk-retry.md`.
