Zin AVF Video Player
====================

A high-performance macOS video player with WebSocket timecode synchronization.

SYSTEM REQUIREMENTS
-------------------
- macOS 10.13 or later
- Apple Silicon (M1/M2/M3) or Intel processor
- Network connection for WebSocket features

INSTALLATION
------------
1. Download ZinAVFPlayer-macOS.dmg
2. Double-click the DMG file to open it
3. Drag ZinAVFPlayer.app to your Applications folder
4. Launch from Applications folder

FIRST TIME LAUNCH
-----------------
If macOS shows a security warning:
1. Right-click (or Control-click) on ZinAVFPlayer.app
2. Select "Open" from the menu
3. Click "Open" in the dialog that appears
4. The app will remember this and launch normally afterwards

FEATURES
--------
- Hardware-accelerated video decoding using AVFoundation
- WebSocket timecode synchronization (wss://signcollect.nl/zin_wss)
- Frame-accurate seeking with 30ms debouncing
- Minimal interface - video display only
- Automatic video loading from WebSocket server

USAGE
-----
1. Launch the application
2. You'll see "Awaiting source..." message
3. The player will automatically connect to the WebSocket server
4. When a video source is sent from the server, it will load automatically
5. The player will follow timecode updates from the server

TROUBLESHOOTING
---------------
- If the app won't open: Right-click → Open (see "FIRST TIME LAUNCH" above)
- Check Console.app for error messages if something goes wrong
- Ensure you have network connectivity for WebSocket features

TECHNICAL INFO
--------------
- Built with PyQt5 and AVFoundation
- Supports MP4, MOV, M4V, AVI, MKV formats
- WebSocket URL: wss://signcollect.nl/zin_wss
- Debounce delay: 30ms for smooth timecode updates

For issues or questions, contact the developer.

Version 1.0 - Built November 2025
