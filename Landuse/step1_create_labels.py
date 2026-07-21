"""Step 1: build stratified label points (Y) from OpenStreetMap via BigQuery.

Classes (must match config.CLASSES):
  1 = water        -> natural=water OR any waterway tag
  2 = urban        -> landuse in (residential, commercial, industrial) OR place in (city, town)
  3 = agriculture  -> landuse in (farmland, orchard, farm)
  4 = forest       -> landuse=forest OR natural=wood

NOTE: this queries `bigquery-public-data.geo_openstreetmap.planet_features`, using its
documented `all_tags` ARRAY<STRUCT<key, value>> column. Google occasionally reshapes this
public dataset -- if the query fails with a "column not found" error, run
`python step0_check_osm_schema.py` first to confirm the current table/column names.

BigQuery has no seedable RAND(); reproducible sampling is done with FARM_FINGERPRINT(id + seed)
as the ORDER BY key, ranked per class with ROW_NUMBER().
"""

import os

import config
from utils import get_bq_client

BBOX_WKT = (
    "POLYGON(({lon_min} {lat_min}, {lon_max} {lat_min}, "
    "{lon_max} {lat_max}, {lon_min} {lat_max}, {lon_min} {lat_min}))"
).format(**config.BBOX)

QUERY = """
WITH tagged AS (
  SELECT
    -- multipolygon features carry their id in osm_way_id, not osm_id, so coalesce both
    COALESCE(osm_id, osm_way_id) AS osm_ref,
    geometry,
    (SELECT value FROM UNNEST(all_tags) WHERE key = 'natural') AS tag_natural,
    (SELECT value FROM UNNEST(all_tags) WHERE key = 'landuse') AS tag_landuse,
    (SELECT value FROM UNNEST(all_tags) WHERE key = 'place') AS tag_place,
    (SELECT value FROM UNNEST(all_tags) WHERE key = 'waterway') AS tag_waterway
  FROM `bigquery-public-data.geo_openstreetmap.planet_features`
  WHERE feature_type IN ('points', 'multipolygons')
    AND ST_INTERSECTS(geometry, ST_GEOGFROMTEXT(@bbox_wkt))
),
classified AS (
  SELECT
    osm_ref,
    CASE
      WHEN tag_natural = 'water' OR tag_waterway IS NOT NULL THEN 1
      WHEN tag_landuse IN ('residential', 'commercial', 'industrial')
           OR tag_place IN ('city', 'town') THEN 2
      WHEN tag_landuse IN ('farmland', 'orchard', 'farm') THEN 3
      WHEN tag_landuse = 'forest' OR tag_natural = 'wood' THEN 4
      ELSE NULL
    END AS class_code,
    ST_CENTROID(geometry) AS pt
  FROM tagged
),
labeled AS (
  SELECT
    osm_ref,
    class_code,
    ST_X(pt) AS lon,
    ST_Y(pt) AS lat,
    -- deterministic, never-null key: the centroid coordinates as text
    ST_ASTEXT(pt) AS pt_wkt
  FROM classified
  WHERE class_code IS NOT NULL
),
ranked AS (
  SELECT
    -- point_id: real OSM id when present, else a stable hash of the centroid
    COALESCE(osm_ref, FARM_FINGERPRINT(pt_wkt)) AS point_id,
    class_code,
    lon,
    lat,
    ROW_NUMBER() OVER (
      PARTITION BY class_code
      ORDER BY FARM_FINGERPRINT(CONCAT(pt_wkt, @seed_suffix))
    ) AS rn
  FROM labeled
)
SELECT point_id, class_code, lon, lat
FROM ranked
WHERE rn <= @points_per_class
ORDER BY class_code, rn
"""


def main():
    from google.cloud import bigquery

    client = get_bq_client()

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("bbox_wkt", "STRING", BBOX_WKT),
            bigquery.ScalarQueryParameter("seed_suffix", "STRING", f"_{config.SEED}"),
            bigquery.ScalarQueryParameter("points_per_class", "INT64", config.POINTS_PER_CLASS),
        ]
    )
    df = client.query(QUERY, job_config=job_config).to_dataframe()

    if df.empty:
        raise RuntimeError(
            "Query returned 0 rows -- check the OSM tag filters and bbox, or verify the "
            "planet_features schema with step0_check_osm_schema.py"
        )

    counts = df["class_code"].value_counts().to_dict()
    print("Points per class:", counts)
    for code in config.CLASSES:
        if counts.get(code, 0) < config.POINTS_PER_CLASS:
            print(
                f"  WARNING: class {code} ({config.CLASSES[code][1]}) only has "
                f"{counts.get(code, 0)}/{config.POINTS_PER_CLASS} points in this bbox"
            )

    df["class_name"] = df["class_code"].map(lambda c: config.CLASSES[c][0])

    dataset_ref = f"{config.GCP_PROJECT}.{config.BQ_DATASET}"
    client.create_dataset(dataset_ref, exists_ok=True)
    table_ref = f"{dataset_ref}.{config.BQ_LABELS_TABLE}"
    client.load_table_from_dataframe(
        df,
        table_ref,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()
    print(f"Wrote {len(df)} rows to {table_ref}")

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(config.OUTPUT_DIR, "labels_points.csv")
    df.to_csv(csv_path, index=False)
    print(f"Backup saved to {csv_path}")


if __name__ == "__main__":
    main()
