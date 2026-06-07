#!/bin/bash
# ─────────────────────────────────────────────
# 니콘 친게 음원 감별사 — macOS 빌드 스크립트
# 실행: bash build_mac.sh
# ─────────────────────────────────────────────
set -e

APP_NAME="니콘 친게 음원 감별사"
BUNDLE_NAME="니콘_친게_음원_감별사"
VERSION="1.0.0"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  $APP_NAME v$VERSION macOS 빌드"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. 의존성 설치
echo ""
echo "▶ 1/4  의존성 설치..."
pip3 install --upgrade pip --quiet
pip3 install -r requirements.txt --quiet
pip3 install pyinstaller --quiet

# 2. PyInstaller 빌드
echo "▶ 2/4  PyInstaller 빌드..."
rm -rf build dist
pyinstaller nikon-chinge-analyzer-py.spec --noconfirm

APP_PATH="dist/${APP_NAME}.app"
if [ ! -d "$APP_PATH" ]; then
    echo "❌ 빌드 실패: $APP_PATH 없음"
    exit 1
fi
echo "   ✓ .app 생성: $APP_PATH"

# 3. DMG 생성
echo "▶ 3/4  DMG 생성..."

# create-dmg 설치 확인
if ! command -v create-dmg &> /dev/null; then
    echo "   create-dmg 설치 중... (brew install create-dmg)"
    if ! command -v brew &> /dev/null; then
        echo "   hdiutil 로 fallback..."
        hdiutil create -volname "$APP_NAME" \
            -srcfolder "dist/${APP_NAME}.app" \
            -ov -format UDZO \
            "dist/${APP_NAME}-${VERSION}.dmg"
        echo "   ✓ DMG: dist/${APP_NAME}-${VERSION}.dmg"
    else
        brew install create-dmg --quiet
        _build_with_create_dmg
    fi
else
    _build_with_create_dmg() {
        create-dmg \
            --volname "$APP_NAME" \
            --volicon "/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/GenericApplicationIcon.icns" \
            --window-pos 200 120 \
            --window-size 600 400 \
            --icon-size 100 \
            --icon "${APP_NAME}.app" 150 185 \
            --hide-extension "${APP_NAME}.app" \
            --app-drop-link 450 185 \
            --background-color "#07070f" \
            "dist/${APP_NAME}-${VERSION}.dmg" \
            "dist/${APP_NAME}.app" || true
    }
    _build_with_create_dmg
fi

echo "▶ 4/4  완료!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ 빌드 성공"
echo "  📁 위치: $(pwd)/dist/"
ls -lh dist/*.dmg 2>/dev/null || ls -lh "dist/${APP_NAME}.app"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
