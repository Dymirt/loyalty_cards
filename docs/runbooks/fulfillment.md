# Central print and fulfillment runbook

1. In the print center, verify tenant, quantity, accepted quote and immutable
   proof checksums.
2. Approve or reject with a reason. Allocation is transactional and card codes
   cannot be reused by another request.
3. Let the supervised print worker generate the package. Never run a standalone
   image loop against production paths.
4. Download only through the superuser package view. Verify the recorded ZIP
   size, SHA-256 and manifest before handing it to production.
5. The current safe profile is per-card JPEG/PNG ZIP. Do not invent printer
   imposition, color-profile, crop-mark or duplex rules without the printer's
   written specification.
6. Record printing, packed, dispatched and delivered events in order with safe
   references. Do not put a customer's private delivery details into an alert.
7. Correct a wrong fulfillment record with a compensating event and reason;
   never delete or rewrite the earlier event.

