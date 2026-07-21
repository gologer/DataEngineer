"""One-off helper: confirm the current schema of the BigQuery public OSM dataset
before relying on step1_create_labels.py. Google reshapes this dataset occasionally,
so run this once to sanity-check the `planet_features` table (or find its replacement).
"""

from utils import get_bq_client


def main():
    client = get_bq_client()

    print("Tables in bigquery-public-data.geo_openstreetmap:")
    for table in client.list_tables("bigquery-public-data.geo_openstreetmap"):
        print(" -", table.table_id)

    print("\nSchema of planet_features:")
    table = client.get_table("bigquery-public-data.geo_openstreetmap.planet_features")
    for field in table.schema:
        print(f" - {field.name}: {field.field_type} ({field.mode})")


if __name__ == "__main__":
    main()
