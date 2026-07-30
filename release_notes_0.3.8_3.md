## v0.3.8_3 - Diagnostic build (no player-facing changes)

Adds timing instrumentation to the GPU flat map's per-frame update: any frame that takes longer than 20ms writes a per-step breakdown to `flatgl_timing.log` next to the exe. Needed to track down a reported stutter that doesn't reproduce on dev hardware (GPU usage stays near 0% during it, and the globe -- same underlying GL plumbing -- shows none of it, so it's CPU-bound and specific to the flat map's own per-frame Python work). No changelog entry; this build exists to collect that log.
