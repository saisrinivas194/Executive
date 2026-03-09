# Execuitive — Full explanation

## What this project does

We take **company executive donation data** (from Lindsey’s spreadsheets or from a crosswalk file), **add it up by company and election year** for Republican and Democratic amounts, and **write the result to Firebase Realtime Database**. The app then reads this data to show how much each company’s execs gave to each party per election cycle.

---

## Project files (what each one is for)

| File | Purpose |
|------|--------|
| **upload_exec_data.py** | Main script. Reads the spreadsheet (or crosswalk), aggregates by company + year, matches company names to Firebase, and uploads `rep`/`dem` amounts. |
| **bootstrap_companies.py** | One-time script. Creates company nodes in Firebase from the crosswalk CSV so the uploader has something to match against. |
| **clear_exec_records.py** | Deletes all uploaded exec records (the `records` node under each company). Leaves company nodes; use when you want to re-upload from scratch. |
| **config.json** | Your real config: paths to spreadsheet, credentials, Firebase URL, column names. You create this from the example; it is gitignored so secrets stay local. |
| **config.example.json** | Template for config. Shows every option; copy to `config.json` and fill in your paths and `database_url`. |
| **contributor_company_crosswalk.csv** | Maps **person name** (contributor) → **company name**. Used when the spreadsheet has people instead of companies, or when the sheet is empty (we use unique companies from here). |
| **DonorPull Dec15 version.xlsm** | Example spreadsheet from Lindsey. Has columns like NAME, COMPANY, JOB TITLE (and optionally Year, Republican, Democratic). |
| **requirements.txt** | Python dependencies: pandas, openpyxl, firebase-admin, rapidfuzz. |
| **.gitignore** | Keeps `config.json`, `.venv`, and similar out of git. |
| **README.md** | Short setup and usage guide. |

---

## Firebase Realtime Database: where data lives

We use **Realtime Database**, not Firestore. The structure is a JSON tree:

```
companies
  └── [company_id]          ← one key per company (e.g. hash of company name from bootstrap)
        ├── name          ← display name (e.g. "3M")
        └── records       ← exec data by year
              └── [year]  ← e.g. "2024"
                    └── exec
                          ├── rep   ← number (total $ to Republicans)
                          └── dem   ← number (total $ to Democrats)
```

- **company_id**: The key under `companies`. From bootstrap it’s a stable hash of the company name so the same name always gets the same id.
- **year**: Election cycle (e.g. `"2024"`, `"2022"").
- **rep** / **dem**: Dollar amounts (numbers). We only write these two under `exec`.

So for each company we have one node; under that, `records/[year]/exec` holds that year’s rep and dem totals.

---

## Config options (what each one does)

**Spreadsheet**
- **spreadsheet_path** — Path to the Excel or CSV file (e.g. `DonorPull Dec15 version.xlsm`).
- **spreadsheet_sheet** — Which sheet to read (name or 0-based index). `null` = first sheet.
- **column_mapping** — Maps **our internal names** to **the column headers in the file**:
  - `company_name` → column that has the company (e.g. `"COMPANY"`).
  - Or `contributor_name` → column that has the person; we then use the crosswalk to get company.
  - `election_year` → column with the year (e.g. `"Year"`).
  - `rep_amount` → column with Republican total (e.g. `"Republican"`).
  - `dem_amount` → column with Democratic total (e.g. `"Democratic"`).
  If the file has no year or amount columns, we use a default year and 0 for rep/dem.

**Crosswalk**
- **contributor_crosswalk_path** — Path to the CSV that has `contributor_name` and `company_name`. Used to turn contributor names into company names, and (if the spreadsheet has no rows) to get the list of companies for upload.

**Firebase**
- **credentials_path** — Path to the Firebase service account JSON (from Project settings → Service accounts → Generate new private key).
- **database_url** — Realtime Database URL (e.g. `https://your-project-id.firebaseio.com`). **Required**; we do not use Firestore.
- **companies_collection** — Key in the Realtime DB where companies live. Default `"companies"`.
- **company_name_field** — Field inside each company node that holds the display name (e.g. `"name"`). We use this for fuzzy matching.
- **company_id_field** — Optional. If set, we use this field as the company id for writing records instead of the node key.

**Matching**
- **fuzzy_match_threshold** — Number from 0 to 1. We only match a spreadsheet company name to a Firebase company if the similarity score is at least this (default 0.75). Lower = more matches but more wrong matches.

**Other**
- **default_election_year** — Year we use when the spreadsheet has no year column (e.g. `2024`).
- **dry_run** — If `true`, we don’t write to Firebase (same as passing `--dry-run` on the command line).

---

## How the upload flow works (step by step)

1. **Load config** — Read `config.json` (or the path you pass).
2. **Load crosswalk** — If `contributor_crosswalk_path` is set, read the CSV and build a map: contributor name → company name.
3. **Read spreadsheet** — Open the file (Excel or CSV), pick the sheet, and rename columns using `column_mapping`.
4. **Resolve contributors** — If the sheet has a contributor column (and we have a crosswalk), replace it with company name using the crosswalk. Drop rows that don’t match any company.
5. **Fill missing columns** — If there’s no year or rep/dem columns, add default year and 0 for rep and dem.
6. **Aggregate** — Group by company name and election year; sum rep amounts and dem amounts. Result: one row per (company, year) with total rep and total dem.
7. **Empty-sheet fallback** — If after aggregation there are no rows but we have a crosswalk, build a list of unique company names from the crosswalk and create rows with default year and rep=0, dem=0.
8. **Connect to Firebase** — Use credentials and `database_url` to connect to the Realtime Database.
9. **Load companies from Firebase** — Read the `companies` node; get for each company its key (or `company_id_field`) and the value of `company_name_field`. We get a list of (company_id, company_name).
10. **Fuzzy match** — For each company name from the spreadsheet (or crosswalk), find the best-matching Firebase company name above the threshold. Build a map: spreadsheet company name → company_id.
11. **Write records** — For each aggregated row, look up company_id. If found, write to `companies/<company_id>/records/<year>` with `{ "exec": { "rep": ..., "dem": ... } }`. If not found, skip and count as skipped. Progress is printed every 100 rows.

So: spreadsheet/crosswalk → normalize columns → aggregate by company + year → match to Firebase companies → write rep/dem under each company’s `records/<year>/exec`.

---

## Bootstrap: why and when

The uploader only **writes under existing company nodes**. It does not create companies. If your Realtime Database has no `companies` (or it’s empty), you run **bootstrap_companies.py** once:

- It reads the crosswalk CSV and collects all unique company names.
- For each name it computes a stable id (hash) and writes a node under `companies` with that id and a `name` field.
- After that, the uploader can match spreadsheet names to these nodes and write records.

So: bootstrap = “create the company nodes”; upload = “fill in records/exec data.”

---

## Clear script: when to use it

**clear_exec_records.py** deletes only the **records** under each company (all years). It does **not** delete the company nodes or the `name` field. Use it when you want to wipe exec data and re-upload (e.g. after fixing the spreadsheet or config). Then run the uploader again.

---

## Commands summary

```bash
# One-time: create company nodes from crosswalk
python bootstrap_companies.py --dry-run   # see what would be created
python bootstrap_companies.py            # do it

# Upload exec data
python upload_exec_data.py --dry-run     # see what would be written, no writes
python upload_exec_data.py               # upload for real

# Optional: wipe exec data and re-upload
python clear_exec_records.py --dry-run   # see what would be deleted
python clear_exec_records.py             # delete all records under companies
python upload_exec_data.py               # upload again
```

---

## Where to see the data in Firebase

1. Open [Firebase Console](https://console.firebase.google.com) → your project.
2. Go to **Realtime Database**.
3. You’ll see a tree. Open **companies** → pick a company key → **records** → a year (e.g. **2024**) → **exec**. There you see **rep** and **dem** numbers.

---

## Lindsey’s files

When Lindsey uploads new files, put them in this folder (or point `spreadsheet_path` to them). If the new file has different column names, update `column_mapping` in `config.json` to match. Then run the uploader again; it will overwrite or add to the same `companies/.../records/<year>/exec` structure.
