#!/usr/bin/env python3

"""
ZIN Video Player with WebSocket Timecode Control

This Python script connects to the ZIN WebSocket server at https://signcollect.nl/zin_wss
and receives real-time timecode updates and video control commands.

Usage:
    python zin_video_player.py

Dependencies:
    pip install websockets opencv-python

Controls:
    - Timecode and playback controlled via WebSocket
    - Press 'q' to quit
"""

import asyncio
import json
import signal
import sys
import time
from datetime import datetime
from typing import Optional
import threading
import cv2

try:
    import websockets
except ImportError:
    print("Error: websockets library not found.")
    print("Install with: pip install websockets")
    sys.exit(1)

# Configuration
WS_URL = 'wss://signcollect.nl/zin_wss'

# Global state
websocket_connection: Optional[object] = None
should_reconnect = True
should_exit = False
current_video_info = {}

# Video player state
video_cap = None
current_video_path = None
target_time = 0.0
is_playing = False
video_fps = 30.0
video_lock = threading.Lock()
frame_cache = None
frame_updated = False


def log(message: str, level: str = 'INFO'):
    """Log a message with timestamp"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f'[{timestamp}] [{level}] {message}')


def load_video(filename: str) -> bool:
    """Load a video file"""
    global video_cap, current_video_path, video_fps

    with video_lock:
        if video_cap is not None:
            video_cap.release()

        video_cap = cv2.VideoCapture(filename)

        if not video_cap.isOpened():
            log(f"Failed to open video: {filename}", 'ERROR')
            return False

        current_video_path = filename
        video_fps = video_cap.get(cv2.CAP_PROP_FPS)
        if video_fps <= 0:
            video_fps = 30.0

        log(f"Loaded video: {filename} @ {video_fps}fps")
        return True


def seek_video(time_seconds: float):
    """Seek to a specific time in the video"""
    global target_time, frame_cache, frame_updated

    with video_lock:
        if video_cap is None or not video_cap.isOpened():
            return

        target_time = time_seconds
        video_cap.set(cv2.CAP_PROP_POS_MSEC, time_seconds * 1000)

        # Read the frame at this position
        ret, frame = video_cap.read()
        if ret:
            frame_cache = frame.copy()
            frame_updated = True


def video_player_thread():
    """Video player thread - displays video frames"""
    global should_exit, video_cap, is_playing, frame_cache, frame_updated

    cv2.namedWindow('ZIN Video Player', cv2.WINDOW_NORMAL)
    import numpy as np

    while not should_exit:
        display_frame = None

        with video_lock:
            if video_cap is not None and video_cap.isOpened():
                if is_playing:
                    # Playing mode: read next frame
                    ret, frame = video_cap.read()
                    if ret:
                        display_frame = frame
                    else:
                        # Video ended
                        is_playing = False
                else:
                    # Paused mode: use cached frame if available
                    if frame_updated and frame_cache is not None:
                        display_frame = frame_cache.copy()
                        frame_updated = False
                    elif frame_cache is not None:
                        display_frame = frame_cache.copy()

        # Display frame outside of lock
        if display_frame is not None:
            current_pos = target_time

            # Add timecode overlay
            hours = int(current_pos // 3600)
            minutes = int((current_pos % 3600) // 60)
            seconds = int(current_pos % 60)
            milliseconds = int((current_pos % 1) * 1000)
            timecode_str = f'{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}'

            cv2.putText(display_frame, timecode_str, (10, 30),
                      cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

            cv2.imshow('ZIN Video Player', display_frame)
        else:
            # Show black frame when no video loaded
            black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(black_frame, 'ZIN Video Player - Waiting for video...', (50, 240),
                      cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow('ZIN Video Player', black_frame)

        # Wait for key press (1ms) - allows 'q' to quit
        key = cv2.waitKey(int(1000 / video_fps)) & 0xFF
        if key == ord('q'):
            should_exit = True
            break

    cv2.destroyAllWindows()
    if video_cap is not None:
        video_cap.release()


async def handle_timecode_message(data: dict):
    """Handle timecode update messages"""
    current_time = data.get('currentTime', 0)
    duration = data.get('duration', 0)
    fps = data.get('fps', 60)
    filename = data.get('filename', 'unknown')

    # Seek video to the received timecode (but don't auto-play)
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
    global is_playing

    is_playing = True
    log("Video playing")


async def handle_pause_message(data: dict):
    """Handle pause command"""
    global is_playing

    is_playing = False
    log("Video paused")


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
    sys.exit(0)


def websocket_thread_func():
    """Run WebSocket client in a separate thread"""
    asyncio.run(websocket_client())


def main():
    """Main entry point"""
    global should_reconnect, should_exit

    print('=' * 60)
    print('ZIN Video Player with WebSocket Control')
    print('=' * 60)
    log(f'Server URL: {WS_URL}')
    log('Press Ctrl+C or "q" in video window to exit')
    print('=' * 60)

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start WebSocket in a separate thread (not main thread)
    ws_thread = threading.Thread(target=websocket_thread_func, daemon=True)
    ws_thread.start()

    # Run video player in main thread (required for macOS OpenCV GUI)
    try:
        video_player_thread()
    except KeyboardInterrupt:
        should_reconnect = False
        should_exit = True
        log('Interrupted by user', 'INFO')
    finally:
        should_exit = True
        log('Disconnected', 'INFO')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log('Exiting...', 'INFO')
        sys.exit(0)
