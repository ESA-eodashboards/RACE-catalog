import os
import json
import glob

collections_path = "collections/"

indicators_path = "indicators/"

catalog_path = "catalogs/race.json"

ALL_CHANGED_FILES = os.environ.get("ALL_CHANGED_FILES")
DELETED_FILES = os.environ.get("DELETED_FILES")

if not ALL_CHANGED_FILES and not DELETED_FILES:
    print("No changed or deleted files detected.")
    exit(0)

changed_files = ALL_CHANGED_FILES.split(" ") if ALL_CHANGED_FILES else []
deleted_files = DELETED_FILES.split(" ") if DELETED_FILES else []

changed_collections_ids = [
    file.split("/")[-1].split(".")[0]
    for file in changed_files
    if file.startswith(collections_path)
]
changed_indicator_ids = [
    file.split("/")[-1].split(".")[0]
    for file in changed_files
    if file.startswith(indicators_path)
]

deleted_collections_files = [
    file for file in deleted_files if file.startswith(collections_path)
]
deleted_indicator_files = [
    file for file in deleted_files if file.startswith(indicators_path)
]
deleted_collections_ids = [
    file.split("/")[-1].split(".")[0] for file in deleted_collections_files
]
deleted_indicator_ids = [
    file.split("/")[-1].split(".")[0] for file in deleted_indicator_files
]

print("changed collections: ", changed_collections_ids)
print("changed indicator files: ", changed_indicator_ids)
if (
    not changed_collections_ids
    and not changed_indicator_ids
    and not deleted_collections_ids
    and not deleted_indicator_ids
):
    print("No collections or indicators files changed.")
    exit(0)

# if the changed collection files doesnt exist in an indicator file, add it to the catalog
all_indicators = glob.glob(indicators_path + "*.json")

is_indicator = {collection: True for collection in changed_collections_ids}

for file in all_indicators:
    removed_collection = False
    with open(file, "r") as f:
        indicator = json.load(f)
    if "Collections" not in indicator:
        continue
    for collection in list(indicator["Collections"]):
        if collection in changed_collections_ids:
            is_indicator[collection] = False
        if collection in deleted_collections_ids:
            indicator["Collections"].remove(collection)
            removed_collection = True
    if removed_collection:
        with open(file, "w") as f:
            json.dump(indicator, f)


with open(catalog_path, "r") as f:
    catalog = json.load(f)
    if not catalog.get("collections", []):
        catalog["collections"] = []

    for collection_id in is_indicator:
        if is_indicator[collection_id] and collection_id not in catalog["collections"]:
            catalog["collections"].append(collection_id)

    for indicator_id in changed_indicator_ids:
        if indicator_id not in catalog["collections"]:
            catalog["collections"].append(indicator_id)

    for deleted_file in deleted_collections_ids + deleted_indicator_ids:
        if deleted_file in catalog["collections"]:
            catalog["collections"].remove(deleted_file)


with open(catalog_path, "w") as f:
    print(
         "Final catalog collections: ",
        catalog["collections"],
    )
    json.dump(catalog, f)
