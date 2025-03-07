import os

# 1. get the changed files
ALL_CHANGED_FILES = os.environ.get("ALL_CHANGED_FILES")
print(ALL_CHANGED_FILES)
# 2. check changes in the indicator and changes in the collections
# 3. if the changed collection files doesnt exist in an indicator file, add it to the catalog
# 4. add the indicator files to the catalog
# 5. update the catalog