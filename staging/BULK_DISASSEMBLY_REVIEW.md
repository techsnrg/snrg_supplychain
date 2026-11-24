# Bulk Disassembly — staging review, 24 November 2026

Implemented in Supply Chain with separate Bulk Disassembly / Bulk Disassembly Item records, BDIS naming, page `bulk-disassembly-entry` and unique Stock Entry trace links.

Uses native ERPNext `Disassemble`, active submitted default BOM, stocked components only. Source defaults to station finished warehouse, target to station input warehouse; both editable per draft. Expanded stations are rejected because dismantling moulded assemblies does not recover polymer. Full BOM recovery only; losses, serial/batch, quality, operations and secondary outputs require the detailed workflow. Original manufacture selection and partial recovery are not included in this version.

Same autosave, mobile settings, status pill, compact desktop table, grouped review blockers, stale review token and per-row resumable posting as Bulk Production. CSS, input IDs, route options and page lifecycle are isolated to avoid collisions when both screens are open. No negative source stock or zero-cost bypass.

Validation:
- 12 disassembly backend unit regressions; 10 disassembly UI regressions.
- Existing 10 production backend + 10 UI regressions pass.
- Native staging acceptance: BDIS-2026-00001 created MAT-STE-2026-00180 and 00181. Finished stock reduced; components increased; Stock Ledger values and GL balance; repeat processing created no duplicates.
- BDIS-2026-00002 shortage blocked before queue or entry creation; edited review token rejected.
- BDIS-2026-00006 shows genuine missing cost for new QA-only finished item. Unauthorized review rejected. BDIS-2026-00007 worker stock guard failed safely with no orphan entries.
- Actual browser review/post BDIS-2026-00003 completed via long queue, created MAT-STE-2026-00182 and 00183, displayed Posted with links.
- Staging worker was stopped; started existing bench worker without container/volume recreation.
- Desktop 1440×900, mobile 375×812, landscape 812×375 visually inspected; review footer remains reachable.
- History Add opens the custom blank screen. New UI draft BDIS-2026-00008 saved and survived reload; left ready for use.
- Workspace Supply Chain shortcut added on staging, preserving existing shortcuts.

No production writes, cloud deployment, app data deletion or volume deletion. Not pushed. Dark mode and 60-row tests were previously performed for the production screen; they were not separately rerun for this new module.
