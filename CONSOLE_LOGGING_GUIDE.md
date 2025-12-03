# Console Logging Guide - AVFoundation Video Player

## Overview

The AVFoundation video player now has comprehensive console logging to help you see exactly what's happening with WebSocket messages and video playback.

## Logging Features

### 1. **Real-Time Timecode Display**

When receiving timecode updates, you'll see:

```
[TIMECODE] Time: 16.680s | Frame: 1000 | 00:00:16.680 | M20250522_8341.mp4
```

**Shows**:
- **Time**: Current time in seconds (3 decimal places)
- **Frame**: Calculated frame number (time × fps)
- **Timecode**: HH:MM:SS.mmm format
- **Filename**: Video filename

**Updates**: Live on the same line (overwrites itself for clean output)

### 2. **Video Info Messages**

When a new video is loaded via WebSocket:

```
======================================================================
VIDEO INFO RECEIVED:
  Filename: M20250522_8341.mp4
  Duration: 113.09s (1.9 minutes)
  FPS: 59.94
  Original path: M20250522_8341.mp4
  Converted to URL: https://media.signcollect.nl/M20250522_8341.mp4
  Loading video...
======================================================================
```

**Shows**:
- Filename
- Duration (seconds and minutes)
- Frame rate
- Original path from message
- Converted URL (if applicable)
- Loading status

### 3. **Raw WebSocket Messages** (Debug Mode)

When `DEBUG_WS_MESSAGES = True`:

```
[2025-11-17 15:30:00.123] [INFO] [WS RECV] Type: video_info
[2025-11-17 15:30:00.124] [INFO] [WS RECV] Raw data: {
  "type": "video_info",
  "filename": "M20250522_8341.mp4",
  "videoPath": "https://media.signcollect.nl/M20250522_8341.mp4",
  "duration": 113.09,
  "fps": 59.94
}
```

**Shows**:
- Complete raw JSON data
- All fields in the message
- Pretty-printed for readability

**Note**: Timecode and pong messages are excluded (too frequent)

### 4. **Connection Events**

WebSocket connection status:

```
[2025-11-17 15:30:00.000] [INFO] Starting WebSocket client...
[2025-11-17 15:30:00.100] [INFO] Connecting to WebSocket server: wss://signcollect.nl/zin_wss
[2025-11-17 15:30:01.200] [INFO] WebSocket connected successfully!
[2025-11-17 15:30:01.300] [INFO] Sent registration message (AVF Player)
[2025-11-17 15:30:01.400] [INFO] Server: Connected to ZIN WebSocket Server
[2025-11-17 15:30:01.500] [INFO] Registered as: python
```

### 5. **URL Loading**

When loading videos from URLs:

```
[2025-11-17 15:30:02.000] [INFO] Loading video from URL: https://media.signcollect.nl/M20250522_8341.mp4
Loading video from URL: https://media.signcollect.nl/M20250522_8341.mp4
AVF Video loaded: 1594x1386, 59.94 fps, 6780 frames
Image format: 8 bpc, 32 bpp, 6400 bytes/row, alpha=True
```

### 6. **Errors and Warnings**

Clear error messages:

```
[2025-11-17 15:30:05.000] [ERROR] Failed to load video: Video file not found
[2025-11-17 15:30:10.000] [WARN] WebSocket connection closed by server
```

## Configuration

### Enable/Disable Raw Message Debug

Edit `zin_avf_video_player.py`:

```python
# Near the top of the file (line ~51)
DEBUG_WS_MESSAGES = True   # Show raw messages
DEBUG_WS_MESSAGES = False  # Hide raw messages (cleaner output)
```

**When to enable**:
- ✅ Debugging WebSocket issues
- ✅ Seeing what data server sends
- ✅ Verifying message format

**When to disable**:
- ✅ Production use (cleaner logs)
- ✅ Only care about timecode
- ✅ Too much output

## Example Console Output

### Full Session Example

```bash
$ python3 zin_avf_video_player.py

[2025-11-17 15:30:00.000] [INFO] Starting WebSocket client...
[2025-11-17 15:30:00.100] [INFO] Connecting to WebSocket server: wss://signcollect.nl/zin_wss
[2025-11-17 15:30:01.200] [INFO] WebSocket connected successfully!
[2025-11-17 15:30:01.300] [INFO] Sent registration message (AVF Player)
[2025-11-17 15:30:01.400] [INFO] Server: Connected to ZIN WebSocket Server

[2025-11-17 15:30:01.500] [INFO] [WS RECV] Type: registered
[2025-11-17 15:30:01.501] [INFO] [WS RECV] Raw data: {
  "type": "registered",
  "clientType": "python"
}
[2025-11-17 15:30:01.600] [INFO] Registered as: python

======================================================================
VIDEO INFO RECEIVED:
  Filename: M20250522_8341.mp4
  Duration: 113.09s (1.9 minutes)
  FPS: 59.94
  Original path: M20250522_8341.mp4
  Converted to URL: https://media.signcollect.nl/M20250522_8341.mp4
  Loading video...
======================================================================
[2025-11-17 15:30:02.000] [INFO] Loading video from URL: https://media.signcollect.nl/M20250522_8341.mp4
Loading video from URL: https://media.signcollect.nl/M20250522_8341.mp4
AVF Video loaded: 1594x1386, 59.94 fps, 6780 frames
Image format: 8 bpc, 32 bpp, 6400 bytes/row, alpha=True

[TIMECODE] Time: 0.000s | Frame: 0 | 00:00:00.000 | M20250522_8341.mp4
[TIMECODE] Time: 0.033s | Frame: 2 | 00:00:00.033 | M20250522_8341.mp4
[TIMECODE] Time: 0.067s | Frame: 4 | 00:00:00.067 | M20250522_8341.mp4
[TIMECODE] Time: 16.680s | Frame: 1000 | 00:00:16.680 | M20250522_8341.mp4
[TIMECODE] Time: 16.714s | Frame: 1002 | 00:00:16.714 | M20250522_8341.mp4
...
```

## Interpreting the Logs

### Timecode Line Breakdown

```
[TIMECODE] Time: 16.680s | Frame: 1000 | 00:00:16.680 | M20250522_8341.mp4
           ^^^^^^^^^^^^     ^^^^^^^^^^^   ^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^
           Seconds          Frame number  HH:MM:SS.mmm    Filename
```

### Understanding Updates

**Fast updates** (timecode every ~16ms at 60fps):
- Line overwrites itself
- Clean, single-line output
- See current position in real-time

**Slow updates** (video_info, connection):
- New lines for each message
- Separated with ======== bars
- Easy to see major events

## Troubleshooting with Logs

### Problem: No timecode showing

**Look for**:
```
[2025-11-17 15:30:01.600] [INFO] Registered as: python
```
✅ If you see this, connection is good

**Check**:
- Is video loaded? (see "AVF Video loaded" message)
- Is server sending timecode? (should see updates)

### Problem: Wrong frame numbers

**Check timecode line**:
```
[TIMECODE] Time: 16.680s | Frame: 1000 | 00:00:16.680 | M20250522_8341.mp4
                                  ^^^^
```

**Calculation**:
- Frame = Time × FPS
- Example: 16.680 × 59.94 ≈ 1000

### Problem: Video not loading

**Look for**:
```
[2025-11-17 15:30:02.000] [ERROR] Failed to load video: ...
```

**Common causes**:
- ❌ URL not accessible
- ❌ Network timeout
- ❌ Unsupported format
- ❌ File not found

### Problem: Connection drops

**Look for**:
```
[2025-11-17 15:30:10.000] [WARN] WebSocket connection closed by server
[2025-11-17 15:30:13.000] [INFO] Reconnecting in 3 seconds...
```

✅ Auto-reconnect should handle this

## Performance Monitoring

### Seek Times

While timecode updates occur, you can see seek performance in the GUI:

```
Frame: 1000 / 6779 | 00:00:16.68 / 01:53.09 | Seek: 35.2ms
                                                     ^^^^^^^^
                                                     Seek time!
```

**Good seek times**:
- ✅ 20-50ms (local files)
- ✅ 50-150ms (URLs, good network)
- ⚠️ 150-300ms (URLs, slow network)
- ❌ 300ms+ (network issues or PyAV fallback)

## Log Files

### Redirect to File

Save logs to file:

```bash
python3 zin_avf_video_player.py 2>&1 | tee avf_player.log
```

**Benefits**:
- ✅ Keep history of all messages
- ✅ Analyze later
- ✅ Share for debugging

### Filter Specific Messages

Show only timecode:
```bash
python3 zin_avf_video_player.py 2>&1 | grep TIMECODE
```

Show only errors:
```bash
python3 zin_avf_video_player.py 2>&1 | grep ERROR
```

Show WebSocket messages:
```bash
python3 zin_avf_video_player.py 2>&1 | grep "WS RECV"
```

## Summary

✅ **Real-time timecode** - See exact time/frame values
✅ **Video info** - Clear indication when videos load
✅ **Raw messages** - Debug WebSocket data (optional)
✅ **Connection status** - Track WebSocket lifecycle
✅ **Error messages** - Clear problem indication

**Now you can see exactly what your player is receiving and doing!** 🔍
