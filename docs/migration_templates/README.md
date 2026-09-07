# DECSI data migration templates

Fill these Excel files from the **live queue / admin system** or with **new** lists, then import them into Loan Hub.

## Files

| File | What to put in it |
|------|-------------------|
| `DECSI_Migration_Pack.xlsx` | All sheets in one workbook (preferred) |
| `01_Regions.xlsx` … `16_Funding_Windows.xlsx` | Same columns, one file per import command |

Yellow rows are examples. Overwrite or delete them before import. Do not rename sheet tabs or header row 1.

## Import order

Geography for unit prices: **Regions → Zones → Cities (woredas)**  
Operations: **Districts → Branches**  
Then: **Departments → Loan categories → Funding windows → Collateral types → Document types → Category document packs → Users → Committee levels → Committee members → Construction catalog → Loan requests**

The live DECSI queue system’s “zone” is usually an **operational district**. Put those names on **04_Districts**, not on geographic **02_Zones**.

## Commands

```bash
# Whole pack
docker compose exec web python manage.py import_migration_pack docs/migration_templates/DECSI_Migration_Pack.xlsx --default-password "ChangeMeNow!"

# Or one sheet at a time
docker compose exec web python manage.py import_regions path/to/01_Regions.xlsx
docker compose exec web python manage.py import_zones path/to/02_Zones.xlsx
docker compose exec web python manage.py import_cities path/to/03_Cities.xlsx
docker compose exec web python manage.py import_districts path/to/04_Districts.xlsx
docker compose exec web python manage.py import_branches path/to/05_Branches.xlsx
docker compose exec web python manage.py import_departments path/to/06_Departments.xlsx
docker compose exec web python manage.py import_loan_categories path/to/07_Loan_Categories.xlsx
docker compose exec web python manage.py import_financing_funds path/to/16_Funding_Windows.xlsx
docker compose exec web python manage.py import_collateral_types path/to/08_Collateral_Types.xlsx
docker compose exec web python manage.py import_document_types path/to/09_Document_Types.xlsx
docker compose exec web python manage.py import_category_documents path/to/10_Category_Documents.xlsx
docker compose exec web python manage.py import_users path/to/11_Users.xlsx --default-password "ChangeMeNow!"
docker compose exec web python manage.py import_committee_levels path/to/12_Committee_Levels.xlsx
docker compose exec web python manage.py import_committee_members path/to/13_Committee_Members.xlsx
docker compose exec web python manage.py import_construction_catalog path/to/14_Construction_Catalog.xlsx
docker compose exec web python manage.py import_loan_requests path/to/15_Loan_Requests.xlsx
```

Useful flags: `--dry-run` (no save), `--update` (change existing rows matched by name / username / key / loan_request_id).

Regenerate empty templates:

```bash
python manage.py generate_migration_templates
```

## Tips

- Format **phone** and **customer_number** columns as Text so Excel keeps leading zeros.
- Head-office users (credit head, CEO, finance, board) may leave **branch** blank.
- Existing queue IDs go in `loan_request_id` (max 22 characters). Leave blank to auto-assign `HK-#########`.
- Document scans, GPS photos, and appraisal sheets are not imported here — staff capture those in the hub after go-live.
