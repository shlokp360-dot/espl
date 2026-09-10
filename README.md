# Elegance Skyz — Construction Automation

Internal system for Elegance Skyz Pvt. Ltd. Takes a project from estimate to
purchase order.

| Step | What it does | Status |
|---|---|---|
| 1 | Create a project — name, location, built-up area, floors | Models built |
| 2 | Estimate BOQ at ₹/sqft → Excel + PDF quote | Models built |
| 3 | Bill of Materials | Not started |
| 4 | Purchase order → approval → PDF to vendor on WhatsApp | Not started |
| 5 | Analytics | Not started |

## Stack

Django 5 · PostgreSQL · Docker. Excel via openpyxl, PDF via WeasyPrint.

Chosen over Java/Spring Boot because the system is mostly master-data screens,
which Django generates automatically — roughly a third of the code to maintain,
which matters when the team supporting it is small.

## Getting started

See **SETUP.md**.

## Rules that must not be broken

* **A material code is an identity, not a description.** Auto-generated, never
  reused, never encodes size, grade or brand.
* **A vendor's identity is their phone number, not their name.** Three names in
  the source data covered two different people each.
* **HSN and GST% live on the material** (cement is HSN 2523 at 28% whoever sells
  it). **The GSTIN lives on the vendor**, and is editable only on the vendor record.
* **BOM and PO lines store a copy of the price**, never just a link — otherwise a
  later master change silently rewrites a purchase order already sent.
* **Estimates are not versioned.** They are working documents, edited until right,
  then saved and exported. Purchase orders are the opposite — an edit after
  submission clears the approval.
* **Never auto-merge** `MTA`/`FTA`, `UPVC`/`CPVC`/`PVC`, `RE TEE`/`TEE`, or
  sizes written `1I` / `1II` — these look similar but are different parts.
* **Phone numbers are stored as digits only.** WhatsApp needs `91` + 10 digits.
  1800 numbers are not WhatsApp-capable and are left blank.

## Never commit

Client data, `.env`, spreadsheets, database dumps, API tokens. `.gitignore`
blocks these, but check before you commit — GitHub keeps history forever.
