#!/bin/sh
# Builds "Radio Bridge.app" in this folder. Needs the Xcode Command Line Tools (swiftc).
set -e
cd "$(dirname "$0")"
APP="Radio Bridge.app"
mkdir -p "$APP/Contents/MacOS"
cp app/Info.plist "$APP/Contents/Info.plist"
swiftc -O app/main.swift -o "$APP/Contents/MacOS/RadioBridge"
codesign --force -s - "$APP"
echo "Built $APP"
