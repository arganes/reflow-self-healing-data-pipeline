# ReFlow — Business Management, AI Reports and Growth Planning

Python 3.10+; standard library only. No pip install or Streamlit required.

## Update an existing installation

1. Stop the running server with Ctrl+C. Back up your existing `data` folder.
2. Copy `app.py`, `healing.py`, `auto_analysis.py`, `report_builder.py`, `business_features.py` and the entire `static` folder from this update into the existing project folder.
3. Keep your existing `data/reflow.sqlite3` and `.env` in that folder. If using REFLOW_DATA, retain the same setting. Existing accounts and reports remain available.
4. Open PowerShell in that folder and run `python app.py`.
5. Open http://127.0.0.1:8502 and press Ctrl+F5. Log in with your existing admin account.

If AI & Self-Healing displays “Not found”, the page is connecting to an older server. Stop that server and restart from the folder containing all updated files. Do not run old and new copies on the same port.

## First installation

Extract the ZIP and open PowerShell inside `reflow_business`:

```powershell
python app.py --create-admin
python app.py
```

Enter your own admin email and password (12 or more characters). There is no default password. Use `py` if your Windows installation provides `py` instead of `python`.

Register a customer in the browser to create a business workspace. Administrators can then upload on behalf of that business. Customers can upload only for their own business.

## Automatic analysis workflow

1. Customer or admin opens Datasets and chooses a CSV or flat JSON file.
2. Click **Upload & auto-analyse**. Every new upload runs the local pipeline automatically, without manual column mapping. The original upload, derived copy and run report are saved atomically.
3. Admin opens **AI & Self-Healing** to see the latest run and graphs. Admin uploads now open Review & publish with an automatically created graph-report draft. For customer uploads, refresh the admin page to see the new run.
4. For older uploads, choose the dataset and click **Auto-analyse & show graphs**. An existing automatic run for the same immutable dataset is reused, preventing duplicate derived copies. Upload a new version for changed records.
5. Review the inferred schema, unresolved issues and graph coverage. Optional manual settings let the administrator override numeric/date selections and rerun.
6. To publish financial analysis, open Datasets → Inspect & analyse, confirm revenue/cost/date/category mappings, then Review & publish. Customers see only their own published reports. Publishing an automatic graph report shares its selected graphs, requirements, findings, approved AI explanation and note; unshared drafts and pipeline run logs stay admin-only.

### Graphs included

- Agent workflow: schema detector → monitor → repair planner → healing executor → validation → graph analyst → version store. Stages represent actual executed local functions, not independent LLMs.
- Quality score before/after, plus before/after issue counts.
- Detected column-type counts and per-column completeness.
- Numeric distributions: up to 6 numeric columns, 8 bins each (one bin for a constant), with minimum, maximum, mean and valid-value coverage.
- Category frequency charts: up to 3 fields, top 12 labels with omitted-record counts disclosed.
- Monthly record-count charts: up to 3 date fields, latest 36 months, with invalid dates and omitted earlier months disclosed.
- Findings, inferred schema evidence, formatting repair log and downloads of the pipeline report and repaired JSON.

Charts use actual uploaded values. A graph appears only when suitable data is present. No financial meaning, currency, live market information or profit improvement is assumed by automatic descriptive analysis. Financial charts still require administrator confirmation.

## Gemini (optional AI-written explanation)

Copy `.env.example` to `.env` beside `app.py`:

```text
GEMINI_API_KEY=your_key
GEMINI_MODEL=your_available_text_generation_model_id
```

Enter a bare model ID available to your key (without `models/`) and restart. Existing environment variables take precedence over `.env`. Never share the key or include `.env`/`data` in a public repository.

Admins can request a Gemini report explanation during upload, or enter requirements in Review & publish and tick its Gemini checkbox. Report generation sends requirements, column/category labels, aggregate chart values and quality summaries to Google; inspect labels for sensitive values before enabling it. It sends no raw source rows or credentials. The separate AI & Self-Healing explanation still sends only aggregate quality counts. Customer uploads never automatically contact Gemini. Generated text cannot execute repairs or code.

The local graphs and repairs work without an API key. Up to three attempts handle network timeouts, 429 and selected 5xx responses; invalid credentials/model errors are reported. Local results remain saved if Gemini fails. Retry after fixing the problem. Quotas and availability depend on the Gemini account.

Official REST reference: https://ai.google.dev/api . AI Studio: https://aistudio.google.com/ . The integration uses generateContent and the x-goog-api-key header.

## Inference, repair and scoring rules

All rows are scanned. Numeric inference uses recognizable measurement names or at least 80% strict decimal values among nonblank cells. ID/code/phone/postal/account/SKU-like column names are excluded. This is a heuristic: numeric identifiers with unusual names may still need manual correction. Currency symbols, separators and scientific notation are not silently converted.

Date inference uses date-like names or at least 90% ISO-compatible nonblank values. A slash format is inferred only with evidence such as a day greater than 12 and no conflicting or mixed ISO evidence. Ambiguous or mixed date formats are left unchanged and flagged. One unambiguous date field is selected for automatic validation/normalization. Multiple date fields trigger a review warning. ISO timestamps retain their time component; slash conversion is for date-only values.

Safe repairs trim outer whitespace and normalize an evidenced date format in a derived copy. All rows and original uploads are retained. Missing values are not invented, identifiers are not coerced to numbers, duplicates are not dropped. Unresolved issues/inference warnings result in `needs_review`. `validated` means selected checks passed, not that every business rule is satisfied.

Score = 100 × (1 − failed checks / total checks). Checks: missing and whitespace per cell, validity per selected numeric/date cell, and a duplicate-candidate check per row. Blanks count as missing, not additionally as invalid numeric/date values. Compare before/after within one run; differing schemas/policies have different denominators. Exact duplicates are candidates for review, not proven errors. The detail log shows at most 500 repairs, but aggregate repair counts are complete.

Analysis runs synchronously when uploading or clicking Auto-analyse. There is no background scheduler, live-market feed, demand forecasting, external ETL restart, or autonomous LLM-driven record correction. Recovery here covers safe formatting, atomic storage and temporary Gemini request failures.

## Demo

Upload `samples/quality_issues.csv`. Automatic inference excludes order_id from numeric checks and selects revenue/total_cost plus DD/MM/YYYY date. Expected: 5 rows retained, 3 whitespace repairs, 4 date normalizations; 1 missing cell, 1 invalid numeric value, 1 invalid date and 1 duplicate candidate remain. Numeric revenue graph contains 3 valid values; January 2026 trend contains 4 records.

Also try retail.csv and services.csv. Files without financial columns still receive quality and descriptive graphs where applicable.

## Validation and limitations

Run `python test_app.py`. Tests cover registration, tenant isolation, CSRF, publication, financial calculations, automatic upload triggers, graph counts, schema inference, ambiguous dates, preserved originals, idempotent automatic runs, failed policy rollback and mocked Gemini success/retries/fallback. JavaScript syntax and generated dashboard HTML are also checked during packaging.

Live Gemini requests have not been tested with your credentials. A browser executable was unavailable during packaging, so visual layout and click-through verification remain to be checked locally.

This localhost prototype uses SQLite, PBKDF2 password hashing, server sessions, CSRF and ownership checks. Data is not encrypted at rest. Public production use needs a production server, HTTPS, operational monitoring and security hardening. One email represents one account, not verified company identity. CSV/flat JSON only; up to 100,000 rows, 150 columns and approximately 10 MB per upload.

## NEW: Review & publish — requirements-based graph analysis

Every new dataset upload now creates a private automatic graph report. Open **Review & publish** to view it. Older datasets can be selected using **Generate / open automatic report**; no re-upload is needed. Existing confirmed financial reports remain available.

1. Select the automatic graph report for the required business/dataset.
2. Enter requirements, for example: “Show monthly sales trend, sales by category and missing data.”
3. Tick **Use Gemini** for AI graph selection and an AI-written explanation. This shares the stated aggregate evidence with Google. Without Gemini, local keyword matching chooses from the computed graph catalogue.
4. Click **Generate graphs & analysis as new draft**. Review the selected graphs, data coverage, unresolved issues, explanation and limitations.
5. Optionally open **Choose specific graphs yourself**, select 1–12 graphs, then save a new draft.
6. Add your administrator note and click **Publish to customer**. The customer sees these selected graphs and analysis under Business reports. **Save as private draft** hides the selected report from the customer.

Each regeneration creates a NEW private report version. It never rewrites an already published report. Older published versions remain visible until the admin explicitly returns them to draft.

Graph values are calculated on the server from the derived dataset. Gemini may only select existing chart IDs and return explanatory text; invalid selections fall back to local chart matching. AI cannot supply chart values or execute code. Its prose is advisory and should be checked against the charts. API failure keeps the locally selected graphs available.

Available graphs include completeness, before/after quality, numeric histograms, category record counts, monthly record counts, and numeric means grouped by detected categories/months. Revenue/cost/quantity-like fields also have explicitly labeled SUM graphs. Sums are descriptive and have unconfirmed units/business meaning until an administrator reviews them; do not sum unit prices, mixed currencies, balances or overlapping records. Profit and forecasts are not invented from arbitrary columns. Use the existing mapping-confirmed financial reports for revenue-minus-cost analysis; forecasting requires a separate validated model.

Coverage notes identify excluded missing/invalid values, top-group limits and observed months. Line charts connect observed months; absent periods are not estimated. The catalogue uses the same limits as automatic profiling (up to 6 numeric, 3 categorical and 3 date fields). AI prompt evidence includes at most 15 displayed points per candidate chart and flags truncation; the report renders all computed points within chart limits.

Validation additions: new draft creation after upload; report regeneration without changing published versions; customer isolation for selected graphs/AI explanations; unknown Gemini chart-ID rejection; aggregate totals checked against sample data; SVG/HTML rendering checks for admin and customer views, including zero-valued charts. Live Gemini and visual browser verification remain untested in this environment.

## NEW: Customer business management and admin access

The new menu provides **Business profile**, **Staff & salary**, **Growth & AI coach**, and **Settings**. Administrators see **Manage customers** and a customer selector in each business-management page. Admin actions execute under the admin identity and are audited; no password retrieval or silent login impersonation is used.

### Profile and dashboard images

Edit business/shop name, sector, owner/contact name, login email, phone, address, city, website, opening hours, description, revenue target, currency and improvement goal. Targets are user-entered planning goals, not predictions. Changing email changes the next login email. Shop images accept public HTTPS links or PNG/JPEG/WebP uploads below 1 MB. Use your own image or an image you have permission to display.

Settings lets each account change its own dashboard banner and password. Changing a password signs out that account's sessions. Uploaded images remain local in SQLite; public linked images are requested by the browser with no referrer. The server does not fetch arbitrary remote image URLs. Broken external image links need replacing or removing. Default illustrations are included and work offline:

- Admin image link: http://127.0.0.1:8502/admin-banner.svg
- Customer image link: http://127.0.0.1:8502/shop-banner.svg

The Settings page and dashboard banner include clickable image links. These URLs work while this local app is running; they are not public hosted images. The included SVG illustrations were created for this project.

### Staff and monthly salary records

Add/edit staff name, role, joining date, monthly salary and active status. The planned monthly total includes active staff only. Record a salary amount and paid/pending status for each staff member and month. Re-saving the same month updates that record. This is recordkeeping only: no money is sent and no statutory/tax payroll is calculated. Staff deletion removes associated salary history after confirmation. Salary currency comes from the business profile and is locked while staff records exist to avoid relabeling amounts without conversion.

### Customer account administration

Admins can view and edit all registered customer profiles, staff records, salary history, growth plans and datasets/reports. Under Manage customers, an admin can set a replacement customer password or enable/disable customer login after entering their own administrator password. Account changes revoke that customer's active sessions. Disabling login retains business records. Existing customer passwords are never shown. Own-account password changes are in Settings.

### Delete unwanted datasets

In **Datasets**, both admins and owners have **Download JSON** and **Delete** buttons. An owner can act only on their own datasets; admins can act on all businesses.

Deletion previews the affected dataset plus its descendant repaired copies, attached reports (including published reports), pipeline runs and saved growth plans. Type DELETE to confirm. A fresh, account-bound confirmation expires in 10 minutes and is consumed after deletion. If the dependency list changes, preview again. No automatic expiry or deletion occurs after analysis: choose Delete when you no longer need the upload. Deleting a repaired copy does not delete its original parent. Reports bound to an unaffected parent may remain as saved snapshots. Deleting an original removes its descendant datasets and their related records. Profile/staff records and unrelated uploads are unaffected. Audit records retain action and target IDs, not deleted dataset contents. Previously exported files, backups and copies outside the app are not deleted. SQLite removal is not secure physical erasure; keep backups protected.

### Business growth prediction and Gemini guidance

1. Add/update your business profile and goal; optionally add staff salaries.
2. Upload a revenue CSV or JSON dataset. Choose **Growth & AI coach** and select one dataset belonging to that business.
3. Confirm its transaction-date and row-level total-revenue columns, source date format, common currency, complete calendar-month coverage and duplicate review. Never use unit prices as revenue. Choose a single source or repaired version, not overlapping files.
4. Create a growth plan. The app saves monthly revenue history, an experimental 3-month estimate when eligible, error evidence and practical local suggestions.
5. Optionally tick Gemini consent to get an AI-written plan for changes to test and metrics to track. Only sector, goal, monthly/forecast aggregates and aggregate planned staff salaries are sent, without staff names, contact details, shop images or raw source records. Profile goal text is included: avoid sensitive details there when using Gemini.
6. Saved plans appear immediately to the customer and admin; they are personal planning results and do not require report publication. View the last 10 plans or download a displayed plan as JSON.

Forecasts require at least six complete consecutive months and no missing/invalid revenue or date rows. Current and future calendar months are excluded using the server's local date. The app cannot verify that uploaded months contain every transaction: completeness is a user confirmation. Gaps block forecasting; confirmed zero-sales months need explicit zero-revenue rows. It uses up to 36 latest observed months and retains duplicate candidates with a warning rather than guessing whether to remove them.

The model compares linear trend and a last-month baseline using rolling, one-step holdouts (up to three months, at least five months of training). The method with lower mean absolute error is refit to all eligible history to project three months. For nonnegative history, negative projections are clipped to zero. Next-month growth percentage is unavailable if the latest actual revenue is zero or negative. Ranges are estimate plus/minus twice the historical one-step error, not calibrated confidence intervals; zero historical error does not imply future certainty. If history is stale, projections start after its final month and are labeled accordingly. No seasonal or market model is included; six months is a minimum for this demo, not proof of forecast reliability.

Guidance suggests experiments such as monitoring repeat orders, reviewing category margins and aligning staff schedules with busy periods. It does not promise improved income or prescribe salary cuts. Planned salary totals are a separate reference, not deducted from dataset costs, which avoids double counting. Forecasts concern revenue, not profit or company valuation. All guidance requires business-owner review.

Try `samples/business_growth_demo.csv`: 16 synthetic records across January–August 2026, representing complete monthly revenue totals split between Store and Online. Choose revenue and date, ISO format, INR. This sample is illustrative, not real business evidence. If running before all those months have finished, fewer months are eligible; if running later, a stale-history warning may appear.

### Verification for this update

Run both `python test_app.py` and `python test_business.py`. New tests cover owner/admin permissions, cross-business denial, image validation, profile changes, salary updates, account disabling/session revocation, password reset, download ownership, preview-confirmed recursive deletion, stale confirmation rejection, remaining foreign-key integrity, insufficient/gapped history and held-out forecast evaluation. Gemini is mocked in tests. UI rendering checks cover customer/admin page structure and graph output. Live Gemini and full visual browser interaction have not been verified in this build environment.
