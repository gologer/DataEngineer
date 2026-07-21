"""Step 6: predict land use across the whole bbox and render an interactive map.

Approach: download the Sentinel-2 composite (feature bands) as a local GeoTIFF, run the
trained sklearn RandomForest on the array directly (bbox is small enough, ~20x20 km), then
overlay the classified raster + true-color Sentinel-2 on a folium/geemap map.

Caveat: the Sentinel-2 true-color background layer is an Earth Engine tile layer -- it
needs live internet access to Earth Engine's tile server to render, and the tile token can
expire after a while. The classified overlay (PNG) is embedded in the HTML and always works
offline.
"""

import os

# A system-wide PROJ_LIB (e.g. from a PostgreSQL/PostGIS install) can point rasterio at an
# incompatible proj.db and break EPSG lookups. Force rasterio's own bundled proj data before
# it is imported so the pipeline runs regardless of the machine's global PROJ settings.
import importlib.util as _ilu

_spec = _ilu.find_spec("rasterio")
if _spec and _spec.submodule_search_locations:
    _proj_dir = os.path.join(list(_spec.submodule_search_locations)[0], "proj_data")
    if os.path.exists(os.path.join(_proj_dir, "proj.db")):
        os.environ["PROJ_LIB"] = _proj_dir
        os.environ["PROJ_DATA"] = _proj_dir

import folium
import joblib
import numpy as np
import rasterio
from PIL import Image

import config
from utils import bbox_geometry, get_s2_composite, init_ee

FEATURE_BANDS = config.S2_BANDS + ["NDVI", "EVI", "NDWI", "NDBI"]
PREDICT_SCALE = 20  # meters/pixel; keeps the local array a manageable size


def download_composite_geotiff(composite, out_path):
    import geemap

    geemap.download_ee_image(
        composite.select(FEATURE_BANDS),
        out_path,
        region=bbox_geometry(),
        crs="EPSG:4326",
        scale=PREDICT_SCALE,
    )


def classify_raster(tif_path, model):
    with rasterio.open(tif_path) as src:
        arr = src.read()  # shape: (bands, H, W)
        bounds = src.bounds
        nodata = src.nodata

    bands, h, w = arr.shape
    flat = arr.reshape(bands, -1).T  # (H*W, bands)

    valid_mask = np.isfinite(flat).all(axis=1)
    if nodata is not None:
        valid_mask &= (flat != nodata).all(axis=1)

    preds = np.zeros(flat.shape[0], dtype=np.uint8)
    preds[valid_mask] = model.predict(flat[valid_mask])
    class_map = preds.reshape(h, w)
    return class_map, valid_mask.reshape(h, w), bounds


def colorize(class_map, valid_mask):
    rgba = np.zeros((*class_map.shape, 4), dtype=np.uint8)
    for code, hex_color in config.CLASS_COLORS.items():
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        mask = (class_map == code) & valid_mask
        rgba[mask] = [r, g, b, 255]
    return rgba


def main():
    init_ee()
    composite = get_s2_composite()

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    tif_path = os.path.join(config.OUTPUT_DIR, "s2_composite.tif")
    print(f"Downloading Sentinel-2 composite to {tif_path} (scale={PREDICT_SCALE}m)...")
    download_composite_geotiff(composite, tif_path)

    model_path = os.path.join(config.OUTPUT_DIR, "rf_model.joblib")
    model = joblib.load(model_path)

    print("Classifying raster...")
    class_map, valid_mask, bounds = classify_raster(tif_path, model)
    rgba = colorize(class_map, valid_mask)

    png_path = os.path.join(config.OUTPUT_DIR, "classified_overlay.png")
    Image.fromarray(rgba, mode="RGBA").save(png_path)
    print(f"Classified overlay saved to {png_path}")

    b = config.BBOX
    center = [(b["lat_min"] + b["lat_max"]) / 2, (b["lon_min"] + b["lon_max"]) / 2]
    m = folium.Map(location=center, zoom_start=12, tiles="CartoDB positron")

    try:
        vis_params = {"bands": ["B4", "B3", "B2"], "min": 0.0, "max": 0.3}
        map_id = composite.getMapId(vis_params)
        folium.raster_layers.TileLayer(
            tiles=map_id["tile_fetcher"].url_format,
            attr="Google Earth Engine",
            name="Sentinel-2 True Color",
            overlay=True,
        ).add_to(m)
    except Exception as e:
        print(f"WARNING: could not add live Sentinel-2 tile layer ({e}); "
              "map will only show the classified overlay")

    folium.raster_layers.ImageOverlay(
        image=png_path,
        bounds=[[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
        name="Land Use Classification",
        opacity=0.7,
    ).add_to(m)

    legend_items = "".join(
        f'<i style="background:{config.CLASS_COLORS[c]};width:12px;height:12px;'
        f'display:inline-block;margin-right:6px;"></i>{name}<br>'
        for c, (_, name) in config.CLASSES.items()
    )
    legend_html = f"""
    <div style="position: fixed; bottom: 30px; left: 30px; z-index: 9999;
                background: white; padding: 10px 14px; border: 1px solid #999;
                border-radius: 4px; font-size: 14px;">
      <b>การใช้ที่ดิน</b><br>{legend_items}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    folium.LayerControl().add_to(m)

    html_path = os.path.join(config.OUTPUT_DIR, "classified_map.html")
    m.save(html_path)
    print(f"Interactive map saved to {html_path}")


if __name__ == "__main__":
    main()
