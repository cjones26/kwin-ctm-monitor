# CTM patch invariants

- Persist one optional row-major 3×3 matrix per KWin output UUID.
- Use connector names only as transient CLI selectors.
- Apply in SDR only, last in nonlinear output-encoded RGB after ICC and VCGT.
- HDR suspends the matrix; returning to SDR restores it.
- Require DRM/KMS realization for exact mode and preserve direct scanout.
- KWin owns confirmation timeout and restores unconfirmed changes.
- Reject non-finite values, wrong counts, unknown outputs, concurrent tests, and unsupported hardware.
- Existing output configuration remains valid without the optional field.
- Test persistence, reconnect, SDR/HDR, ordering, unsupported hardware, rollback, and D-Bus validation.
