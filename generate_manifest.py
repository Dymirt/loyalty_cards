import hashlib
import json
import os

files = [f for f in os.listdir('.') if f not in ['manifest.json', 'signature', 'certificate.pem', 'key.pem', 'AppleWWDR.pem']]
manifest = {}

for f in files:
    with open(f, 'rb') as file:
        manifest[f] = hashlib.sha1(file.read()).hexdigest()

with open('manifest.json', 'w') as mf:
    json.dump(manifest, mf, indent=4)
