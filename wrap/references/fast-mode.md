# Fast-mode per-phase defaults

How each interactive gate resolves when wrap runs as `/wrap --fast`. The two hard invariants (no questions; safe, additive actions only) and the over-share posture are in SKILL.md; this table is the per-phase resolution.

Chain mode behaves the same with `--fast`: launching the successor is a safe, additive action using this session's explicit permission mode; the handoff, stop rules and confirmation in `chain.md` still apply.

The "interactive default" column is what an unmappable answer resolves to in a normal run (SKILL.md principle 8), not merely what fast mode does. The two columns agree on purpose: fast mode is the interactive default with the asking removed. If you change one, change the other.

| Phase | Interactive default | Fast-mode action |
|-------|--------------------|------------------|
| 0 - outstanding asks | ask f / w / d; default **w** (handoff) | **handoff**: externalize every unfinished ask to a memory entry or handoff plan; never exit early, never silently drop |
| 1 - scope | confirm repo list; default the detected list | use the detected list (recall + dirty-scan) as-is |
| 2a - session memory | numbered list; default **save all** | write every drafted item automatically |
| 2b - background processes | approve batch | harvest each one's output into memory first, then terminate |
| 3a - per-repo memory | (folded into Phase 3 batch) | write every drafted item automatically |
| 3b - plans sweep | approve archive / delete | extract loose threads to memory; **leave every plan file in place**; list would-be archives in the summary |
| 3c - hygiene | approve deletes / junk clear | extract loose threads to memory; **delete nothing** (junk default is keep anyway); list findings in the summary |
| 3d - wrap's own commit (#1) | automatic | unchanged: auto-commit wrap's own writes per repo (still no push) |
| 3d - user work (#2) | prompt p/c/s/l/b; default **l** (leave as-is) | **leave as-is**: never auto-commit or push pre-existing user changes; report them as leftovers |
| 4 - summary | always runs | always runs; state that `--fast` ran and enumerate every deferred destructive action plus the untouched user work |
