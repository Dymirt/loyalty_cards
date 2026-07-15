import os
import json
import hashlib
import shutil
import subprocess
from uuid import uuid4

BASE_DIR = os.getcwd()
TEMPLATE_DIR = os.path.join(BASE_DIR, 'mypass_template')
OUTPUT_DIR = os.path.join(BASE_DIR, 'media/output_passes')
CROPED_IMG_DIR = os.path.join(BASE_DIR, 'media/cropped_images')

os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_manifest(pass_dir):
    manifest = {}
    for filename in os.listdir(pass_dir):
        if filename in ['manifest.json', 'signature', 'certificate.pem', 'key.pem', 'AppleWWDR.pem']:
            continue
        with open(os.path.join(pass_dir, filename), 'rb') as f:
            sha1 = hashlib.sha1(f.read()).hexdigest()
            manifest[filename] = sha1
    with open(os.path.join(pass_dir, 'manifest.json'), 'w') as mf:
        json.dump(manifest, mf, indent=4)

def sign_manifest(pass_dir):
    subprocess.run([
        "openssl", "smime", "-binary", "-sign",
        "-certfile", os.path.join(TEMPLATE_DIR, "AppleWWDR.pem"),
        "-signer", os.path.join(TEMPLATE_DIR, "certificate.pem"),
        "-inkey", os.path.join(TEMPLATE_DIR, "key.pem"),
        "-in", os.path.join(pass_dir, "manifest.json"),
        "-out", os.path.join(pass_dir, "signature"),
        "-outform", "DER"
    ], check=True)

def build_pass(i):
    pass_dir = os.path.join(OUTPUT_DIR, f"pass_{i}")
    os.makedirs(pass_dir, exist_ok=True)

    # Copy base files
    for file in ['icon.png', 'icon@2x.png', 'logo@2x.png']:
        src = os.path.join(TEMPLATE_DIR, file)
        if os.path.exists(src):
            shutil.copy(src, pass_dir)

    # Copy and rename strip
    strip_src = os.path.join(CROPED_IMG_DIR, f'cropped_image_{i}.jpg')
    if os.path.exists(strip_src):
        shutil.copy(strip_src, os.path.join(pass_dir, 'strip@2x.png'))

    # Create pass.json
    serial = str(uuid4())
    pass_data = {
        "formatVersion": 1,
        "passTypeIdentifier": "pass.club.mbstudio.online",
        "serialNumber": serial,
        "teamIdentifier": "W66MF62243",
        "organizationName": "",
        "description": "",
        "foregroundColor": "rgb(186, 186, 186)",
        "backgroundColor": "rgb(254, 255, 255)",
        "logoText": "",
        "storeCard": {
            "headerFields": [
                {
                    "key": "customerNumber",
                    "label": "NUMER",
                    "value": f"MB-{i}"
                }
                ],
            "secondaryFields": [
                {
                    "key": "website",
                    "label": "WWW.MARTABANASZEK.PL",
                    "value": ""
                },
                {
                    "key": "phone",
                    "label": "+48 519 727 253",
                    "value": "",
                    "textAlignment": "PKTextAlignmentRight"
                }
                ]
        },
        "barcode": {
            "format": "PKBarcodeFormatCode128",
            "message": f"MB-{i}",
            "messageEncoding": "iso-8859-1"
        }
    }

    with open(os.path.join(pass_dir, 'pass.json'), 'w') as f:
        json.dump(pass_data, f, indent=4)

    # Generate manifest and signature
    generate_manifest(pass_dir)
    sign_manifest(pass_dir)

    # Create .pkpass
    pkpass_path = os.path.join(OUTPUT_DIR, f"pass_{i}.pkpass")
    files = os.listdir(pass_dir)
    subprocess.run(['zip', '-j', pkpass_path] + [os.path.join(pass_dir, f) for f in files], check=True)

    shutil.rmtree(pass_dir)  # optional: clean up folder after zipping
    return pkpass_path

for i in range(201, 601):
    build_pass(i)

#print("✅ 100 passes generated in:", OUTPUT_DIR)
