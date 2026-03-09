# Execuitive — Lindsey exec data uploader

Parses company executive donation data from Lindsey's spreadsheets, aggregates by **election cycle** and **party** (Republican / Democratic), and uploads to **Firebase Realtime Database**.

## Firebase structure (Realtime Database only)

The uploader writes **only** to Firebase Realtime Database (not Firestore). The path format is:

```
companies -> company_id -> records -> year -> exec
```

Where:
- **companies** is the root key (config: `firebase.companies_collection`, default `"companies"`).
- **company_id** is the key for each company (from bootstrap or your existing data).
- **records** is a fixed segment; under it, each **year** (e.g. `"2024"`) holds that cycle’s data.
- **exec** is an object with **rep** (Republican total, number) and **dem** (Democratic total, number).

So each company has `companies/<company_id>/records/<year>/exec` with Republican and Democratic totals.

## Setup

1. **Python 3.9+** and a virtualenv (recommended):

   ```bash
   cd Execuitive
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Config**

   - Copy `config.example.json` to `config.json`.
   - Set `spreadsheet_path` to the path of Lindsey's file (`.xlsx`, `.xls`, or `.csv`).
   - Set `firebase.credentials_path` to your Firebase service account JSON path.
   - Set `firebase.database_url` to your Realtime Database URL (e.g. `https://your-project.firebaseio.com`).
   - Adjust `column_mapping` to match the spreadsheet column names for:
     - **Company name** (or **contributor name** if using the crosswalk)
     - Election year (e.g. `"Year"`)
     - Republican total (e.g. `"Republican"`)
     - Democratic total (e.g. `"Democratic"`)
   - If your spreadsheet has contributor names instead of company names, set `contributor_crosswalk_path` to `contributor_company_crosswalk.csv` (or your crosswalk file) and map the column to `contributor_name` in `column_mapping`. The uploader will resolve each contributor to a company before aggregating.

3. **Firebase**

   - Use a **Realtime Database** project. Set `firebase.database_url` in config (e.g. `https://your-project.firebaseio.com`).
   - Ensure `companies` exists in the Realtime Database with nodes whose **names** can be fuzzy-matched to the spreadsheet. Each company key (or `company_id_field` if set) is used as `company_id` in the path above.

## Bootstrap companies (first time)

If your Realtime Database has no `companies` node (or it's empty), create company nodes from the crosswalk once:

```bash
python bootstrap_companies.py --dry-run   # preview
python bootstrap_companies.py             # create companies in Firebase
```

This reads unique company names from `contributor_crosswalk_path` and writes one node per company under `companies` with a `name` field. Then run the exec uploader to match and write records.

## Running

- **Dry run** (no writes):

  ```bash
  python upload_exec_data.py --dry-run
  ```

- **Run for real** (uses `config.json`):

  ```bash
  python upload_exec_data.py
  ```

- **Custom config file**:

  ```bash
  python upload_exec_data.py path/to/my_config.json
  ```

## Contributor crosswalk

If Lindsey's spreadsheet has **contributor-level** data (person names) instead of company names, use `contributor_crosswalk_path` pointing to a CSV with `contributor_name` and `company_name` columns (e.g. `contributor_company_crosswalk.csv`). The uploader will resolve each contributor to a company and then aggregate by company and election year. Rows whose contributor is not in the crosswalk are dropped.

## Fuzzy matching

Spreadsheet company names (from the sheet or from the crosswalk) are matched to Firebase company names with **rapidfuzz** (ratio scorer). The threshold is set in config as `fuzzy_match_threshold` (default `0.75`). Rows whose company name does not match any Firebase company above that threshold are **skipped** and reported in the log.

## Config options

| Option | Description |
|--------|-------------|
| `spreadsheet_path` | Path to the spreadsheet (required). |
| `spreadsheet_sheet` | Sheet name or 0-based index for Excel; `null` = first sheet. |
| `contributor_crosswalk_path` | Optional. Path to CSV with `contributor_name` and `company_name` to resolve contributors to companies. |
| `column_mapping` | Maps internal keys to spreadsheet column headers: `company_name` or `contributor_name`, `election_year`, `rep_amount`, `dem_amount`. |
| `firebase.credentials_path` | Path to Firebase service account JSON. |
| `firebase.database_url` | Realtime Database URL (e.g. `https://your-project.firebaseio.com`). |
| `firebase.companies_collection` | Key for companies in Realtime DB (default `companies`). |
| `firebase.company_name_field` | Field in each company node for the display name (e.g. `name`). |
| `firebase.company_id_field` | Optional: use this field as `company_id` instead of the node key. |
| `fuzzy_match_threshold` | Min similarity 0–1 for accepting a match (default `0.75`). |
| `dry_run` | If `true`, no Firebase writes (same as `--dry-run`). |
