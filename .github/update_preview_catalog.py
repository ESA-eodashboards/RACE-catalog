import os
import json
import glob

collections_path = "collections/"
indicators_path = "indicators/"
catalog_path = "catalogs/race.json"

ALL_CHANGED_FILES = os.environ.get("ALL_CHANGED_FILES")
if not ALL_CHANGED_FILES:
    print("No changed files detected.")
    exit(0)

changed_files = ALL_CHANGED_FILES.split(" ")
print("ALL_CHANGED_FILES: ", changed_files)

indicator_ids = [
    file.split("/")[-1].split(".")[0]
    for file in changed_files
    if file.startswith(indicators_path)
]
collection_ids = [
    file.split("/")[-1].split(".")[0]
    for file in changed_files
    if file.startswith(collections_path)
]
all_indicator_files = glob.glob(indicators_path + "*.json")
print("changed collections files: ", collection_ids)
print("changed indicator files: ", indicator_ids)

is_indicator = {collection: True for collection in collection_ids}

# Check if changed collection files are referenced in indicator files
for file in all_indicator_files:
    with open(file, "r") as f:
        indicator = json.load(f)
        if "Collections" not in indicator:
            continue
        for collection in indicator["Collections"]:
            if collection in collection_ids:
                is_indicator[collection] = False

# Load existing catalog
with open(catalog_path, "r") as f:
    catalog = json.load(f)

# Reset collections list
catalog["collections"] = []

# Add standalone collections
for collection_id in is_indicator:
    if is_indicator[collection_id]:
        catalog["collections"].append(collection_id)

# Add changed indicators
catalog["collections"].extend(indicator_ids)

# Write updated catalog
with open(catalog_path, "w") as f:
    print(
        "Adding the following to the catalog: ",
        catalog["collections"],
    )
    json.dump(catalog, f)
