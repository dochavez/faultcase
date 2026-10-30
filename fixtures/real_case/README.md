# Real case (anonymized)

Lenovo laptop with an NVIDIA GPU, purchased in January 2026. Data gathered by hand with Event Viewer and WinDbg on October 27, 2026.

- `events_41.json`: the 6 Kernel-Power 41 events with their parameters.
- `windbg/*.txt`: `!analyze -v` and `lmvm nvlddmkm` output for the 4 minidumps.
- `expected.json`: conclusions the system must reach (golden test).

To add: `failures.evtx` exported with `filters/device-diagnostics.xml` (tests the real parser and powers demo mode). Before pushing it to GitHub, confirm it contains nothing you don't want to publish.
