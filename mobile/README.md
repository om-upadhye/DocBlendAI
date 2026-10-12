# DocBlendAI Android app

A native React Native app for the DocBlendAI server: upload a PDF, photo, Word, PowerPoint, or
text file (or take a photo of notes), see the document, and ask questions. Every answer shows
its reliability label (Certain / Moderate / Uncertain / Unreadable) and where it was found.

All reading (OCR / handwriting) and answering happens on the server
(`SERVER_URL` in [src/config.ts](src/config.ts), currently `https://docblendai.onrender.com`).
The Gemini key stays on the server; the app contains no secrets.

## Screens

| Tab | What it does |
|---|---|
| Documents | Choose files or take a photo, pick the kind of writing, tick which documents to ask about, view or remove them |
| Preview | The document's pages, or **What I read**: each recognised line with its confidence (scans/handwriting) or paragraphs/tables (typed) |
| Ask | Chat with reliability labels, suggested questions, and "Where I found this" with match and legibility scores |

The header shows visitors and questions today (same counters as the website). Documents are
private to the app session and the server deletes them a few minutes after the app is closed.

## Installing the APK on a phone

1. Send `DocBlendAI.apk` over WhatsApp, Drive, email, or USB.
2. On the phone, tap the file. Android asks to allow installs from that app (WhatsApp, Files, ...):
   tap **Settings → Allow from this source**, go back, and tap **Install**.
3. If Play Protect warns about an unknown app, tap **More details → Install anyway**
   (it is just not from the Play Store).

The first start can take up to a minute: the free Render server sleeps when nobody uses it.

## Building the APK (Windows)

Needs Node 22+, Android Studio (its bundled JDK 17, the Android SDK, and NDK 27.1.12297006 from
Android Studio → Settings → Android SDK → SDK Tools).

Windows limits file paths to 260 characters, and the native build's paths get too long inside
a deep folder like `OneDrive\Documents\Desktop\...` ("Filename longer than 260 characters").
Build from a short folder instead, e.g. copy `mobile` to `C:\dba` (don't exclude folders named
`build`: some libraries in `node_modules` need theirs):

```bash
robocopy mobile C:\dba /E /XD .cxx .gradle
cd C:\dba
npm install
cd android
set JAVA_HOME=C:\Program Files\Android\Android Studio\jbr
gradlew.bat assembleRelease
```

The APK is `android/app/build/outputs/apk/release/app-release.apk`.

`android/local.properties` must point at the SDK (`sdk.dir=C\:\\Users\\<you>\\AppData\\Local\\Android\\Sdk`);
Android Studio creates it when you open the `android` folder once.

## Signing key (keep it safe)

Release builds are signed with `android/app/docblendai-release.keystore`, whose passwords are in
`android/keystore.properties`. Both are git-ignored. **Back them up privately** (e.g. a private
Drive folder): a new APK installs as an update over the old one only if it is signed with the same
key. Without `keystore.properties` the build falls back to the debug key.

To make a new key: `keytool -genkeypair -v -storetype PKCS12 -keystore app/docblendai-release.keystore
-alias docblendai -keyalg RSA -keysize 2048 -validity 10000`, then fill in `keystore.properties`
(`storeFile`, `storePassword`, `keyAlias`, `keyPassword`).

## Changing the server

Edit `SERVER_URL` in `src/config.ts` and build again. When testing against a server on your own PC
from the Android emulator, use `http://10.0.2.2:8000` (plain http also needs
`usesCleartextTraffic` enabled for release builds).
