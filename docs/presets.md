# Generation presets

Presets are named flag bundles for `papertrail generate`. Explicit flags
always win over preset values; anything the preset does not set keeps its
default. Preset definitions live in `generator/src/papertrail/simulate.py`
(`HARD_PRESET`, `BENCH_PRESET`) so library callers can apply them with
`Config(seed=..., **BENCH_PRESET)`.

## `hard`

All four realism screws on, nothing else changed (world size, years, and
question counts stay at their defaults). This is the G3 preset: it exists
to measure retrieval degradation against the same world as a clean run.

| config field          | value  |
|-----------------------|--------|
| `truncate_references` | `true` |
| `quoted_replies`      | `true` |
| `near_dup_invoices`   | `0.15` |
| `format_drift`        | `true` |

Generation command:

```
python -m papertrail generate --seed 42 --preset hard --out corpus-hard/
```

## `bench`

The publication configuration: three years, a larger world, higher trading
volume, all realism screws on, and 55 questions requested per category.
The PO and sales rates are part of the preset definition; they were tuned
so the seed 42 corpus lands near 15k messages.

| config field              | value                              |
|---------------------------|------------------------------------|
| `years`                   | `3` (start year 2024, so 2024-2026)|
| `n_vendors`               | `14`                               |
| `n_customers`             | `10`                               |
| `pos_per_vendor_month`    | `(4, 6)`                           |
| `sales_per_customer_month`| `(3, 4)`                           |
| `truncate_references`     | `true`                             |
| `quoted_replies`          | `true`                             |
| `near_dup_invoices`       | `0.15`                             |
| `format_drift`            | `true`                             |
| `category_counts`         | `55` per category (330 requested)  |

If a category cannot fill its 55 on a given seed, the generator takes what
exists; the manifest records the actual totals.

Generation command:

```
python -m papertrail generate --seed 42 --preset bench --out corpus-bench/
```

`--months` applies to the FINAL year (non-final years always run 12
months), so `--preset bench --months 6` would produce two full years plus
six months.

### Measured stats, `--preset bench --seed 42`

Measured with `time.monotonic()` around build plus write (the env-gated
`test_bench_preset_smoke` in `generator/tests/test_g4.py` re-measures the
build on every gated run and asserts the two-minute budget):

| stat                      | value                                    |
|---------------------------|------------------------------------------|
| messages                  | 15,515                                   |
| documents                 | 8,104                                    |
| events                    | 12,959                                   |
| threads                   | 3,882                                    |
| facts                     | 77                                       |
| parties / people          | 26 / 32                                  |
| questions                 | 326 (cat 1: 55, 2: 55, 3: 55, 4: 55, 5: 51, 6: 55) |
| corpus size on disk       | 90,278,732 bytes (86.1 MiB) across 23,629 files |
| generation wall time      | 11.8 s total (0.7 s simulate+render+questions, the rest EML/attachment writing) |

Category 5 fills 51 of 55 on this seed (the world runs out of unambiguous
person-history questions); the manifest's `counts.questions` records the
actual total, as always.

The gated invariant run (`PAPERTRAIL_BENCH_PRESET=1 pytest` in
`generator/`) executes the entire invariant suite against this exact
corpus via the parametrized `corpus` fixture.

## Determinism notes

- `years = 1` output is byte-identical to the pre-multi-year generator for
  every seed: year 1 executes the exact same draw sequence, and the
  `years` key is omitted from the manifest at its default (the same
  omitted-when-default rule the realism screws use).
- Worlds with more than 22 trading parties draw company names from an
  extended stem pool (`EXTRA_COMPANY_STEMS`); smaller worlds keep sampling
  from the original pool so their bytes do not shift.
