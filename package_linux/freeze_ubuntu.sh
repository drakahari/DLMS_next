#!/bin/sh
set -eu
release=${1:?Release identity required}
source_commit=${2:?Exact source commit required}
source_tree=${3:-}
support=${DLMS_DESKTOP_PREVIEW_SUPPORT:-Private Ubuntu24.04-compatible candidate; Fedora44/Omarchy qualification recorded separately; not publicly cleared}
mkdir -p /work/out/ocr-bundle/bin /work/out/ocr-bundle/tessdata/configs /work/out/ocr-bundle/licenses
cp /opt/ocr/bin/tesseract /work/out/ocr-bundle/bin/
cp /opt/lept/lib/libleptonica.so.6* /work/out/ocr-bundle/bin/
cp -a /work/old-ocr/tessdata/. /work/out/ocr-bundle/tessdata/
cp -a /work/old-ocr/licenses/. /work/out/ocr-bundle/licenses/
# PyInstaller follows these Ubuntu-native dependencies (including TIFF/JBIG).
cp /inputs/resolved-python.txt /inputs/resolved-debian.txt /work/out/
/opt/ocr/bin/tesseract --version > /work/out/ocr-version.txt 2>&1
python -m pip check
set -- --host-platform --output /work/out/normal-build --release "$release" --target 'Linux x86_64 glibc2.39 baseline; host Fontconfig/GBM' --support "$support" --source-commit "$source_commit" --ocr-bundle /work/out/ocr-bundle --notices /work/notices --distribution-kit /work/distribution-kit
if [ -n "$source_tree" ]; then
    set -- "$@" --source-tree-sha256 "$source_tree"
fi
python -m package_appimage.build_payload "$@"
python -m package_fedora.verify_embedded_payload --exe /work/out/normal-build/dist/DLMS-Desktop/DLMS-Desktop --payload /work/out/normal-build/dist/DLMS-Desktop --project /work --build-pyz /work/out/normal-build/work/DLMS-Desktop/PYZ-00.pyz --ocr-bundle /work/out/ocr-bundle --output /work/out/embedded.json
python -m package_linux.abi_inventory --payload /work/out/normal-build/dist/DLMS-Desktop --output /work/out/native-ABI.json --require-ubuntu24
