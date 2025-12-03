#!/usr/bin/env python3

"""
ZIN Video Player with VLC and WebSocket Timecode Control

This Python script connects to the ZIN WebSocket server and uses VLC
for high-performance video playback with accurate timecode seeking.

Usage:
    python zin_video_player_vlc.py

Dependencies:
    pip install websockets python-vlc

Controls:
    - Timecode controlled via WebSocket
    - Press Ctrl+C to quit
"""

import asyncio
import json
import signal
import sys
import threading
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
last_seek_time = 0.0
seek_threshold = 0.1  # Only seek if difference is > 100ms


def log(message: str, level: str = 'INFO'):
    """Log a message with timestamp"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f'[{timestamp}] [{level}] {message}')


def init_vlc():
    """Initialize VLC player"""
    global vlc_instance, vlc_player

    with vlc_lock:
        vlc_instance = vlc.Instance('--no-xlib')
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

            # Start paused
            vlc_player.play()
            vlc_player.pause()

            log(f"Loaded video: {url}")
            return True
        except Exception as e:
            log(f"Failed to load video: {e}", 'ERROR')
            return False


def seek_video(time_seconds: float):
    """Seek to a specific time in the video"""
    global target_time, last_seek_time

    with vlc_lock:
        if vlc_player is None:
            return

        target_time = time_seconds

        # Only seek if the difference is significant (reduces overhead)
        current_time = vlc_player.get_time() / 1000.0
        time_diff = abs(current_time - time_seconds)

        if time_diff > seek_threshold:
            vlc_player.set_time(int(time_seconds * 1000))
            last_seek_time = time_seconds


def set_playing(playing: bool):
    """Set playback state"""
    with vlc_lock:
        if vlc_player is None:
            return

        if playing:
            if not vlc_player.is_playing():
                vlc_player.play()
        else:
            if vlc_player.is_playing():
                vlc_player.pause()


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
    print(f'\r[TIMECODE] {filename} | {timecode_str} / {duration:.2f}s @ {fps}fps', end='', flush=True)


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
    log("Video playing")
    set_playing(True)


async def handle_pause_message(data: dict):
    """Handle pause command"""
    log("Video paused")
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


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    global should_reconnect, should_exit
    print()  # New line
    log('Shutting down...', 'INFO')
    should_reconnect = False
    should_exit = True

    # Stop VLC player
    with vlc_lock:
        if vlc_player:
            vlc_player.stop()

    sys.exit(0)


def main():
    """Main entry point"""
    global should_reconnect, should_exit

    print('=' * 60)
    print('ZIN Video Player (VLC) with WebSocket Control')
    print('=' * 60)
    log(f'Server URL: {WS_URL}')
    log('Press Ctrl+C to exit')
    print('=' * 60)

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize VLC
    init_vlc()

    try:
        asyncio.run(websocket_client())
    except KeyboardInterrupt:
        should_reconnect = False
        should_exit = True
        log('Interrupted by user', 'INFO')
    finally:
        should_exit = True
        log('Disconnected', 'INFO')

        # Cleanup VLC
        with vlc_lock:
            if vlc_player:
                vlc_player.stop()
                vlc_player.release()
            if vlc_instance:
                vlc_instance.release()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log('Exiting...', 'INFO')
        sys.exit(0)
