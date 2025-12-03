#!/usr/bin/env python3

"""
ZIN Video Player with ImageIO/PyAV and WebSocket Timecode Control

This Python script uses imageio with PyAV for frame-accurate video seeking
controlled via WebSocket timecode messages.

Usage:
    python zin_video_player_imageio.py

Dependencies:
    pip install websockets imageio imageio-ffmpeg av PyQt5

Controls:
    - Timecode controlled via WebSocket
    - Close window to exit
"""

import asyncio
import json
import sys
import threading
from datetime import datetime
from typing import Optional
import numpy as np

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QImage, QPixmap

try:
    import websockets
except ImportError:
    print("Error: websockets library not found.")
    print("Install with: pip install websockets")
    sys.exit(1)

try:
    import imageio.v3 as iio
    import av
except ImportError:
    print("Error: imageio/av libraries not found.")
    print("Install with: pip install imageio imageio-ffmpeg av")
    sys.exit(1)

# Configuration
WS_URL = 'wss://signcollect.nl/zin_wss'

# Global state
websocket_connection: Optional[object] = None
should_reconnect = True
should_exit = False
current_video_info = {}

# Video player state
video_frames = []  # All frames loaded in memory
video_url = None
target_time = 0.0
video_fps = 60.0
video_duration = 0.0
video_lock = threading.Lock()


def log(message: str, level: str = 'INFO'):
    """Log a message with timestamp"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f'[{timestamp}] [{level}] {message}')


class SignalEmitter(QObject):
    """Signal emitter for thread-safe GUI updates"""
    status_update = pyqtSignal(str)
    frame_update = pyqtSignal(np.ndarray)


class VideoPlayerWindow(QMainWindow):
    """Main video player window"""

    def __init__(self):
        super().__init__()
        self.signal_emitter = SignalEmitter()
        self.signal_emitter.status_update.connect(self.update_status)
        self.signal_emitter.frame_update.connect(self.update_frame)
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("ZIN Video Player (ImageIO/PyAV)")
        self.resize(800, 480)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Video label (displays frame as QPixmap)
        self.video_label = QLabel()
        self.video_label.setStyleSheet("background-color: black;")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setScaledContents(False)  # Don't scale, keep aspect ratio
        layout.addWidget(self.video_label)

        # Status bar
        self.status_label = QLabel("Waiting for video...")
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: #2c3e50;
                color: white;
                padding: 8px;
                font-size: 11pt;
            }
        """)
        self.status_label.setMaximumHeight(35)
        layout.addWidget(self.status_label)

        central_widget.setLayout(layout)

    def update_status(self, message: str):
        """Update status label"""
        self.status_label.setText(message)

    def update_frame(self, frame: np.ndarray):
        """Update video frame display"""
        if frame is None or frame.size == 0:
            return

        # Convert numpy array to QImage
        height, width, channel = frame.shape
        bytes_per_line = 3 * width
        q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)

        # Convert to pixmap and display
        pixmap = QPixmap.fromImage(q_image)
        self.video_label.setPixmap(pixmap)

    def closeEvent(self, event):
        """Handle window close event"""
        global should_reconnect, should_exit, video_frames

        log("Closing application...")
        should_reconnect = False
        should_exit = True

        # Clear video frames from memory
        with video_lock:
            video_frames.clear()

        event.accept()


# Global reference to main window
main_window = None


def load_video(url: str) -> bool:
    """Load entire video into memory for instant frame access"""
    global video_frames, video_url, video_fps, video_duration

    with video_lock:
        try:
            log(f"Loading video into memory: {url}")
            log("This may take a moment...")

            # Clear previous frames
            video_frames = []

            # Open video with PyAV
            container = av.open(url)
            stream = container.streams.video[0]

            # Get metadata
            video_fps = float(stream.average_rate)
            video_duration = float(stream.duration * stream.time_base) if stream.duration else 0

            # Load all frames into memory
            frame_count = 0
            for frame in container.decode(video=0):
                # Convert frame to numpy array (RGB)
                img = frame.to_ndarray(format='rgb24')
                video_frames.append(img)
                frame_count += 1

                # Log progress every 100 frames
                if frame_count % 100 == 0:
                    log(f"Loaded {frame_count} frames...")

            container.close()
            video_url = url

            log(f"Loaded video: {url}")
            log(f"  Total frames: {len(video_frames)}")
            log(f"  FPS: {video_fps}")
            log(f"  Duration: {video_duration:.2f}s")

            if main_window:
                main_window.signal_emitter.status_update.emit(f"Loaded: {url} ({len(video_frames)} frames)")

            return True
        except Exception as e:
            log(f"Failed to load video: {e}", 'ERROR')
            return False


def get_frame_at_time(time_seconds: float) -> Optional[np.ndarray]:
    """Get frame at a specific time from loaded frames"""
    global video_frames, video_fps

    with video_lock:
        if not video_frames:
            return None

        try:
            # Calculate frame index based on time and FPS
            frame_index = int(time_seconds * video_fps)

            # Clamp to valid range
            frame_index = max(0, min(frame_index, len(video_frames) - 1))

            return video_frames[frame_index]

        except Exception as e:
            log(f"Error getting frame at {time_seconds}s: {e}", 'ERROR')
            return None


def seek_video(time_seconds: float):
    """Seek to a specific time in the video and update display"""
    global target_time

    target_time = time_seconds

    # Get the frame at this timecode (instant lookup from memory)
    frame = get_frame_at_time(time_seconds)

    if frame is not None and main_window:
        # Update GUI with the frame
        main_window.signal_emitter.frame_update.emit(frame)


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
    if main_window:
        main_window.signal_emitter.status_update.emit(status_text)


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
    log("Play command received (not implemented in frame-by-frame mode)")


async def handle_pause_message(data: dict):
    """Handle pause command"""
    log("Pause command received (always in frame-by-frame mode)")


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


def main():
    """Main entry point"""
    global main_window

    print('=' * 60)
    print('ZIN Video Player (ImageIO/PyAV) with WebSocket Control')
    print('=' * 60)
    log(f'Server URL: {WS_URL}')
    log('Close window to exit')
    print('=' * 60)

    # Create Qt application
    app = QApplication(sys.argv)

    # Create main window
    main_window = VideoPlayerWindow()
    main_window.show()

    # Start WebSocket in a separate thread
    ws_thread = threading.Thread(target=websocket_thread_func, daemon=True)
    ws_thread.start()

    # Run Qt event loop
    sys.exit(app.exec_())


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log('Exiting...', 'INFO')
        sys.exit(0)
