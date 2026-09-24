# How to build LaptopControl.apk with Android Studio

This project is ready to open â€” no code changes needed.

## 1. Install Android Studio
1. Run the installer you downloaded.
2. Keep the default components (Android Studio + Android SDK + Android Virtual Device).
3. First launch: choose **Standard** setup and let it download the SDK (~1 GB).

## 2. Open this project
1. Android Studio â†’ **Open** (or File â†’ Open).
2. Select the folder:
   `<path-to-repo>\android-app`
3. Wait for **Gradle Sync** to finish (bottom bar). First sync downloads
   dependencies â€” a few minutes. If it asks to install a missing SDK /
   build-tools version, click the blue **Install** link it offers.

## 3. Build the APK
Menu â†’ **Build â†’ Build App Bundle(s)/APK(s) â†’ Build APK(s)**.

When it finishes, click **"locate"** in the notification. The file is at:

```
android-app\app\build\outputs\apk\debug\app-debug.apk
```

Rename it to `LaptopControl.apk` if you like.

## 4. Get it on your phone (pick one)
- **USB cable**: copy `app-debug.apk` to the phone, tap it in Files â†’
  **Install** (allow "Install from unknown sources" if asked).
- **WhatsApp/Telegram/Drive**: send the APK to yourself, download, install.
- **Direct from Android Studio** (needs USB debugging on the phone):
  Settings â†’ About phone â†’ tap "Build number" 7Ã— â†’ Developer options â†’
  USB debugging ON â†’ plug in â†’ press the â–¶ Run button. Android Studio
  installs and launches it automatically.

## 5. Use it
1. On the laptop: `python server.py`
2. In the app: type the address the server prints
   (e.g. `192.168.1.10:8080` on Wi-Fi, or your Tailscale `100.x.x.x:8080`
   from anywhere) â†’ **Connect**.
3. The address is remembered for next time.

## Troubleshooting
| Problem | Fix |
|---|---|
| "SDK location not found" | Create `android-app\local.properties` with: `sdk.dir=C:\\Users\\<you>\\AppData\\Local\\Android\\Sdk` |
| Gradle JDK error | Settings â†’ Build Tools â†’ Gradle â†’ Gradle JDK â†’ pick "Embedded JDK 17" |
| Sync fails on plugin version | Android Studio shows a quick-fix link â€” click it and let it adjust |
| App installs but won't connect | Check laptop firewall (allow Python), same Wi-Fi/Tailscale, and that server.py is running |
