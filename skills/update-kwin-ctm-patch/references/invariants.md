# CTM patch invariants

- Persist one optional row-major 3×3 matrix per KWin output UUID.
- Use connector names only as transient CLI selectors.
- Apply in SDR only to nonlinear output-encoded RGB.
- Render KWin color management before scanout, then program only the custom
  matrix into the CRTC hardware pipeline. Never fold it into ICC or VCGT ops.
- HDR suspends the matrix; returning to SDR restores it.
- Require DRM/KMS realization for exact mode and preserve direct scanout.
- KWin owns confirmation timeout and restores unconfirmed changes.
- Never restore a persisted matrix automatically during output/session setup.
  It must only ever be (re-)applied through the interactive D-Bus API against
  an already-running session — that path can synchronously test the exact
  hardware CTM and get an immediate pass/fail. Automatic setup cannot: on
  KDE neon's `plasmalogin`, the same compositor process is reused across the
  greeter and the user session, so render-loop signals like "a frame was
  presented" fire continuously regardless of session state and do not
  reliably indicate it is safe to touch the CTM. Reapplying a saved matrix
  after login is a session-level concern. Do not install a global autostart
  hook for it by default; on plasmalogin systems that still runs too early.
- Reject non-finite values, wrong counts, unknown outputs, concurrent tests, and unsupported hardware.
- Existing output configuration remains valid without the optional field.
- Test persistence, reconnect, SDR/HDR, ordering, unsupported hardware, rollback, and D-Bus validation.
