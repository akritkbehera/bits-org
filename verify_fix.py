import os

# Mock buildEnvironment as a list of tuples with potential duplicates
buildEnvironment = [
    ("ARCHITECTURE", "amd64"),
    ("BUILD_REQUIRES", "package1 package2"),
    ("CACHED_TARBALL", "path/to/tarball"),
    ("DUPLICATE_KEY", "value1"),
    ("DUPLICATE_KEY", "value2"),
]

print("Original buildEnvironment:", buildEnvironment)

# Simulate the fixed code path
# 1. Create a dictionary for os.environ update (this will naturally deduplicate keys, taking the last one)
buildEnvironmentDict = {
    key: (val if isinstance(val, str) else "_".join(val))
    for key, val in buildEnvironment
}
print("\nDictionary for os.environ:", buildEnvironmentDict)

# 2. Update os.environ (mocking it)
# os.environ.update(buildEnvironmentDict)

# 3. Generate benv string using the ORIGINAL buildEnvironment list
benv = ""
for val in buildEnvironment:
    benv += val[0] + "='" + val[1] + "' "

print("\nGenerated benv string:", benv)

# Verification
expected_benv = "ARCHITECTURE='amd64' BUILD_REQUIRES='package1 package2' CACHED_TARBALL='path/to/tarball' DUPLICATE_KEY='value1' DUPLICATE_KEY='value2' "
if benv == expected_benv:
    print("\nSUCCESS: benv string matches expected output.")
else:
    print("\nFAILURE: benv string does NOT match expected output.")
    print("Expected:", expected_benv)
    print("Actual:  ", benv)
