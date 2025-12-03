#!/usr/bin/env python3

"""
ZIN Video Player with VLC GUI and WebSocket Timecode Control

This Python script connects to the ZIN WebSocket server and uses VLC
with a tkinter GUI for video playback with accurate timecode seeking.

Usage:
    python zin_video_player_vlc_gui.py

Dependencies:
    pip install websockets python-vlc

Controls:
    - Timecode controlled via WebSocket
    - Close window or press Ctrl+C to quit
"""

import asyncio
import json
import sys
import threading
import tkinter as tk
from datetime import datetime
from typing import Optional

try:
    import websockets
except ImportError:
    print("Error: websockets library not found.")
    print("Install with: pip install websockets")
    sys.exit(1)

try:
    import vlc
except ImportError:
    print("Error: python-vlc library not found.")
    print("Install with: pip install python-vlc")
    sys.exit(1)

# Configuration
WS_URL = 'wss://signcollect.nl/zin_wss'

# Global state
websocket_connection: Optional[object] = None
should_reconnect = True
should_exit = False
current_video_info = {}

# VLC player state
vlc_instance = None
vlc_player = None
vlc_lock = threading.Lock()
target_time = 0.0
seek_threshold = 0.05  # Only seek if difference is > 50ms

# GUI
root = None
video_panel = None
status_label = None


def log(message: str, level: str = 'INFO'):
    """Log a message with timestamp"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f'[{timestamp}] [{level}] {message}')


def update_status(message: str):
    """Update status label in GUI"""
    if status_label:
        status_label.config(text=message)


def init_vlc():
    """Initialize VLC player"""
    global vlc_instance, vlc_player

    with vlc_lock:
        vlc_instance = vlc.Instance()
        vlc_player = vlc_instance.media_player_new()
        log("VLC player initialized")


def load_video(url: str) -> bool:
    """Load a video file or URL"""
    global vlc_player

    with vlc_lock:
        if vlc_player is None:
            log("VLC player not initialized", 'ERROR')
            return False

        try:
            media = vlc_instance.media_new(url)
            vlc_player.set_media(media)

            # Set the window handle for video output
            if sys.platform.startswith('darwin'):  # macOS
                vlc_player.set_nsobject(int(video_panel.winfo_id()))
            elif sys.platform.startswith('win'):  # Windows
                vlc_player.set_hwnd(video_panel.winfo_id())
            else:  # Linux
                vlc_player.set_xwindow(video_panel.winfo_id())

            # Start paused
            vlc_player.play()
            # Give it a moment to start
            import time
            time.sleep(0.1)
            vlc_player.pause()

            log(f"Loaded video: {url}")
            root.after(0, lambda: update_status(f"Loaded: {url}"))
            return True
        except Exception as e:
            log(f"Failed to load video: {e}", 'ERROR')
            return False


def seek_video(time_seconds: float):
    """Seek to a specific time in the video"""
    global target_time

    with vlc_lock:
        if vlc_player is None:
            return

        target_time = time_seconds

        # Only seek if the difference is significant (reduces overhead)
        current_time = vlc_player.get_time() / 1000.0 if vlc_player.get_time() >= 0 else 0
        time_diff = abs(current_time - time_seconds)

        if time_diff > seek_threshold:
            vlc_player.set_time(int(time_seconds * 1000))


def set_playing(playing: bool):
    """Set playback state"""
    with vlc_lock:
        if vlc_player is None:
            return

        if playing:
            if not vlc_player.is_playing():
                vlc_player.play()
                log("Started playback")
        else:
            if vlc_player.is_playing():
                vlc_player.pause()
                log("Paused playback")


async def handle_timecode_message(data: dict):
    """Handle timecode update messages"""
    current_time = data.get('currentTime', 0)
    duration = data.get('duration', 0)
    fps = data.get('fps', 60)
    filename = data.get('filename', 'unknown')

    # Seek video to the received timecode
    seek_video(current_time)

    # Log timecode
    hours = int(current_time // 3600)
    minutes = int((current_time % 3600) // 60)
    seconds = int(current_time % 60)
    milliseconds = int((current_time % 1) * 1000)

    timecode_str = f'{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}'

    # Print on same line (overwrite)
    status_text = f'{filename} | {timecode_str} / {duration:.2f}s @ {fps}fps'
    print(f'\r[TIMECODE] {status_text}', end='', flush=True)

    # Update GUI status
    root.after(0, lambda: update_status(status_text))


async def handle_video_info_message(data: dict):
    """Handle video information messages"""
    global current_video_info

    current_video_info = {
        'filename': data.get('filename', 'unknown'),
        'duration': data.get('duration', 0),
        'fps': data.get('fps', 60)
    }

    print()  # New line after timecode updates
    log(f"Video Info: {current_video_info['filename']}")
    log(f"  Duration: {current_video_info['duration']:.2f}s")
    log(f"  FPS: {current_video_info['fps']}")

    # Load the video file if path is provided
    video_path = data.get('videoPath') or data.get('filename')
    if video_path:
        # Convert filename to full URL if needed
        if not video_path.startswith('http'):
            # Extract base filename and change extension to .mp4
            import os
            base_name = os.path.splitext(video_path)[0]
            video_path = f'https://media.signcollect.nl/{base_name}.mp4'
            log(f"Converted to URL: {video_path}")

        load_video(video_path)


async def handle_play_message(data: dict):
    """Handle play command"""
    set_playing(True)


async def handle_pause_message(data: dict):
    """Handle pause command"""
    set_playing(False)


async def handle_message(message: str):
    """Handle incoming WebSocket messages"""
    try:
        data = json.loads(message)
        message_type = data.get('type', 'unknown')

        if message_type == 'connection':
            log(f"Server: {data.get('message', '')}")

        elif message_type == 'registered':
            log(f"Registered as: {data.get('clientType', 'unknown')}")

        elif message_type == 'timecode':
            await handle_timecode_message(data)

        elif message_type == 'video_info':
            await handle_video_info_message(data)

        elif message_type == 'play':
            await handle_play_message(data)

        elif message_type == 'pause':
            await handle_pause_message(data)

        elif message_type == 'pong':
            pass  # Ignore pong messages (heartbeat)

        else:
            log(f"Unknown message type: {message_type}", 'WARN')

    except json.JSONDecodeError as e:
        log(f"Error parsing JSON: {e}", 'ERROR')
    except Exception as e:
        log(f"Error handling message: {e}", 'ERROR')


async def send_register_message(websocket):
    """Register this client as a Python video player"""
    register_msg = json.dumps({
        'type': 'register',
        'clientType': 'python'
    })
    await websocket.send(register_msg)
    log('Sent registration message')


async def websocket_client():
    """Main WebSocket client loop"""
    global websocket_connection, should_reconnect, should_exit

    retry_delay = 3  # seconds

    while should_reconnect and not should_exit:
        try:
            log(f'Connecting to WebSocket server: {WS_URL}')

            async with websockets.connect(WS_URL, ssl=True) as websocket:
                websocket_connection = websocket
                log('Connected successfully!')

                # Register as Python video player client
                await send_register_message(websocket)

                # Listen for messages
                async for message in websocket:
                    if should_exit:
                        break
                    await handle_message(message)

        except websockets.exceptions.ConnectionClosed:
            log('Connection closed by server', 'WARN')
            websocket_connection = None

        except ConnectionRefusedError:
            log(f'Connection refused. Is the server running at {WS_URL}?', 'ERROR')
            websocket_connection = None

        except Exception as e:
            log(f'Connection error: {e}', 'ERROR')
            websocket_connection = None

        if should_reconnect and not should_exit:
            log(f'Reconnecting in {retry_delay} seconds...')
            await asyncio.sleep(retry_delay)


def websocket_thread_func():
    """Run WebSocket client in a separate thread"""
    asyncio.run(websocket_client())


def on_closing():
    """Handle window close"""
    global should_reconnect, should_exit

    log("Closing application...")
    should_reconnect = False
    should_exit = True

    # Stop VLC player
    with vlc_lock:
        if vlc_player:
            vlc_player.stop()
            vlc_player.release()
        if vlc_instance:
            vlc_instance.release()

    root.destroy()


def create_gui():
    """Create the GUI window"""
    global root, video_panel, status_label

    root = tk.Tk()
    root.title("ZIN Video Player (VLC)")
    root.geometry("1280x720")
    root.protocol("WM_DELETE_WINDOW", on_closing)

    # Video panel
    video_panel = tk.Frame(root, bg='black')
    video_panel.pack(fill=tk.BOTH, expand=True)

    # Status bar
    status_frame = tk.Frame(root, bg='#2c3e50', height=30)
    status_frame.pack(fill=tk.X, side=tk.BOTTOM)

    status_label = tk.Label(
        status_frame,
        text="Waiting for video...",
        fg='white',
        bg='#2c3e50',
        font=('Arial', 10),
        anchor='w',
        padx=10
    )
    status_label.pack(fill=tk.X)

    return root


def main():
    """Main entry point"""
    global should_reconnect, should_exit

    print('=' * 60)
    print('ZIN Video Player (VLC + GUI) with WebSocket Control')
    print('=' * 60)
    log(f'Server URL: {WS_URL}')
    log('Close window to exit')
    print('=' * 60)

    # Initialize VLC
    init_vlc()

    # Create GUI
    create_gui()

    # Start WebSocket in a separate thread
    ws_thread = threading.Thread(target=websocket_thread_func, daemon=True)
    ws_thread.start()

    # Run GUI main loop (must be in main thread)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_closing()

    log('Exited', 'INFO')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log('Exiting...', 'INFO')
        sys.exit(0)
