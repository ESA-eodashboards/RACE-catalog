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

collections_files = [
    file for file in changed_files if file.startswith(collections_path)
]
indicator_files = [file for file in changed_files if file.startswith(indicators_path)]

print("changed collections files: ", collections_files)
print("changed indicator files: ", indicator_files)

is_indicator = {file: True for file in collections_files}

# if the changed collection files doesnt exist in an indicator file, add it to the catalog
all_indicators = glob.glob(indicators_path + "*.json")

is_indicator = {file: True for file in collections_files}

for file in all_indicators:
    with open(file, "r") as f:
        indicator = json.load(f)
        if "Collections" not in indicator:
            continue
    for collection in indicator["Collections"]:
        if collection in collections_files:
            is_indicator[collection] = False

with open(catalog_path, "r") as f:
    catalog = json.load(f)
    if not catalog["collections"]:
        catalog["collections"] = []

    for collection_file in is_indicator:
        collection_id = collection_file.split("/")[-1].split(".")[0]
        if (
            is_indicator[collection_file]
            and collection_id not in catalog["collections"]
        ):
            catalog["collections"].append(collection_id)

    for indicator_file in indicator_files:
        indicator_id = file.split("/")[-1].split(".")[0]
        if indicator_id not in catalog["collections"]:
            catalog["collections"].append(indicator_id)

with open(catalog_path, "w") as f:
    print(
        "adding the following as indicators to the catalog: ",
        catalog["collections"],
    )
    json.dump(catalog, f)
