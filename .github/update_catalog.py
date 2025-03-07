import os
import yaml
import subprocess

collections_path = "collections"
indicators_path = "indicators"
catalog_path = "catalogs/race.yaml"

ALL_CHANGED_FILES = os.environ.get("ALL_CHANGED_FILES")
changed_files = ALL_CHANGED_FILES.split(" ")
print("ALL_CHANGED_FILES: ", changed_files)

collections_files = [ file for file in changed_files if file.startswith(collections_path) ]
indicator_files = [ file for file in changed_files if file.startswith(indicators_path) ]

print("changed collections files: ", collections_files)

is_indicator = {file: False for file in collections_files}

print("changed indicator files: ", indicator_files)
# 3. if the changed collection files doesnt exist in an indicator file, add it to the catalog
for file in indicator_files:
    with open(file, "r") as f:
        indicator = yaml.load(f)
    ind_collections = indicator.get("Collections", [])
    for collection in ind_collections:
        if collection in collections_files:
            is_indicator[collection] = True
with os.open(catalog_path, "r") as f:
    catalog = yaml.load(f)      
    catalog["collections"] = []      
    for key in is_indicator:
        if not is_indicator[key]:
            catalog["collections"].append(key)
    catalog["collections"].append(file for file in indicator_files)
    yaml.dump(catalog, f)
