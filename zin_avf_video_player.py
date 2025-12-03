#!/usr/bin/env python3
"""
AVFoundation Video Player - Minimal WebSocket-driven video display
Features:
- Native macOS AVFoundation backend for hardware-accelerated decoding
- WebSocket timecode synchronization (wss://signcollect.nl/zin_wss)
- Frame-accurate seeking with debounced updates
- Minimal UI - video display only
"""

import sys
import os
import asyncio
import json
import threading
from datetime import datetime
from typing import Optional
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QImage, QPixmap

try:
    import websockets
except ImportError:
    print("Warning: websockets library not found.")
    print("Install with: pip install websockets")
    print("WebSocket features will be disabled.")
    websockets = None

# Check platform
if sys.platform != 'darwin':
    print("Error: AVFoundation is only available on macOS")
    print("Please use zin_pyav_frame_seeker.py for cross-platform support")
    sys.exit(1)

try:
    from avf_frame_grabber import AVFFrameGrabber
except ImportError:
    print("Error: avf_frame_grabber.py not found")
    print("Please ensure avf_frame_grabber.py is in the same directory")
    sys.exit(1)

# WebSocket Configuration
WS_URL = 'wss://signcollect.nl/zin_wss'

# Debug: Set to True to see raw WebSocket messages
DEBUG_WS_MESSAGES = True

# Global WebSocket state
websocket_connection: Optional[object] = None
should_reconnect = True
should_exit = False
ws_enabled = websockets is not None


def log(message: str, level: str = 'INFO'):
    """Log a message with timestamp"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f'[{timestamp}] [{level}] {message}')


class SignalEmitter(QObject):
    """Signal emitter for thread-safe GUI updates from WebSocket thread"""
    status_update = pyqtSignal(str)
    seek_request = pyqtSignal(float)  # Seek to time in seconds
    load_video_request = pyqtSignal(str)  # Load video by path/URL


class AVFVideoPlayerWindow(QMainWindow):
    """
    High-performance video player using native macOS AVFoundation.
    Supports WebSocket timecode synchronization.
    """

    def __init__(self):
        super().__init__()
        self.grabber = None
        self.current_frame = 0

        # WebSocket signal emitter
        self.signal_emitter = SignalEmitter()
        self.signal_emitter.status_update.connect(self.update_ws_status)
        self.signal_emitter.seek_request.connect(self.seek_to_time_seconds)
        self.signal_emitter.load_video_request.connect(self.load_video)

        # WebSocket seek debouncing (prevents lag from rapid timecode updates)
        self.ws_seek_debounce_timer = QTimer()
        self.ws_seek_debounce_timer.setSingleShot(True)
        self.ws_seek_debounce_timer.timeout.connect(self.perform_ws_seek)
        self.pending_ws_seek_time = None

        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("AVFoundation Video Player")
        self.setGeometry(100, 100, 1280, 720)

        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Video display area (fullscreen)
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setText("Awaiting source...")
        self.video_label.setStyleSheet("""
            QLabel {
                background-color: #000000;
                color: #666666;
                font-size: 24px;
                font-weight: 300;
            }
        """)
        main_layout.addWidget(self.video_label, stretch=1)

        # Status label for connection debugging
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setText("Starting...")
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: #1a1a1a;
                color: #888888;
                font-size: 12px;
                padding: 8px;
                font-family: monospace;
            }
        """)
        main_layout.addWidget(self.status_label)

        # Apply global background
        self.setStyleSheet("background-color: #000000;")

    def load_video(self, video_path):
        """Load a video file using AVFoundation (supports local files and URLs)."""
        try:
            # Close existing grabber if any
            if self.grabber:
                self.grabber.close()

            # Create new grabber
            log(f"Loading video: {video_path}")
            self.grabber = AVFFrameGrabber(video_path)

            # Load first frame
            self.current_frame = 0
            self.display_frame(0)

            log(f"Video loaded: {self.grabber.video_width}x{self.grabber.video_height} @ {self.grabber.framerate:.2f}fps | {self.grabber.total_frames} frames")

        except Exception as e:
            log(f"Failed to load video: {e}", 'ERROR')
            import traceback
            traceback.print_exc()

    def display_frame(self, frame_num):
        """Display a specific frame."""
        if not self.grabber:
            return

        frame_array = self.grabber.grab_frame_number(frame_num)

        if frame_array is not None:
            # Convert numpy array to QPixmap
            height, width, channel = frame_array.shape
            bytes_per_line = 3 * width
            q_image = QImage(frame_array.data, width, height, bytes_per_line, QImage.Format_RGB888)

            # Scale to fit label while maintaining aspect ratio
            pixmap = QPixmap.fromImage(q_image)
            scaled_pixmap = pixmap.scaled(
                self.video_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.video_label.setPixmap(scaled_pixmap)

            self.current_frame = frame_num

    def update_ws_status(self, message: str):
        """Update WebSocket status display (called from WebSocket thread)."""
        if hasattr(self, 'status_label'):
            self.status_label.setText(message)

    def seek_to_time_seconds(self, time_seconds: float):
        """Seek to a specific time in seconds (called from WebSocket thread)."""
        if not self.grabber:
            return

        # Store pending seek time and restart debounce timer
        # This prevents lag when receiving rapid timecode updates
        self.pending_ws_seek_time = time_seconds

        # Debounce with 30ms delay (similar to hover scrubbing but faster for real-time sync)
        self.ws_seek_debounce_timer.stop()
        self.ws_seek_debounce_timer.start(30)

    def perform_ws_seek(self):
        """Actually perform the websocket seek (called after debounce timer)."""
        if not self.grabber or self.pending_ws_seek_time is None:
            return

        time_seconds = self.pending_ws_seek_time

        # Convert seconds to frame number
        frame_num = int(time_seconds * self.grabber.framerate)
        frame_num = max(0, min(frame_num, self.grabber.total_frames - 1))

        # Display the frame
        self.display_frame(frame_num)

    def closeEvent(self, event):
        """Handle window close event."""
        global should_reconnect, should_exit

        log("Closing application...")
        should_reconnect = False
        should_exit = True

        if self.grabber:
            self.grabber.close()

        event.accept()


# Global reference to main window (for WebSocket thread)
main_window = None


async def handle_timecode_message(data: dict):
    """Handle timecode update messages from WebSocket"""
    current_time = data.get('currentTime', 0)
    duration = data.get('duration', 0)
    fps = data.get('fps', 60)
    filename = data.get('filename', 'unknown')

    # Seek video to the received timecode
    if main_window and main_window.grabber:
        main_window.signal_emitter.seek_request.emit(current_time)

    # Format timecode
    hours = int(current_time // 3600)
    minutes = int((current_time % 3600) // 60)
    seconds = int(current_time % 60)
    milliseconds = int((current_time % 1) * 1000)

    timecode_str = f'{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}'

    # Calculate frame number
    frame_num = int(current_time * fps) if main_window and main_window.grabber else 0

    # Print timecode to console (overwrite same line)
    status_text = f'{filename} | {timecode_str} / {duration:.2f}s @ {fps}fps'
    print(f'\r[TIMECODE] Time: {current_time:.3f}s | Frame: {frame_num} | {timecode_str} | {filename}', end='', flush=True)

    # Update GUI status
    if main_window:
        main_window.signal_emitter.status_update.emit(status_text)


async def handle_video_info_message(data: dict):
    """Handle video information messages"""
    filename = data.get('filename', 'unknown')
    duration = data.get('duration', 0)
    fps = data.get('fps', 60)

    print()  # New line after timecode updates
    log("=" * 70)
    log("VIDEO INFO RECEIVED:")
    log(f"  Filename: {filename}")
    log(f"  Duration: {duration:.2f}s ({duration/60:.1f} minutes)")
    log(f"  FPS: {fps}")

    # Load the video file if path is provided
    video_path = data.get('videoPath') or data.get('filename')
    if video_path and main_window:
        log(f"  Original path: {video_path}")

        # Convert filename to full URL if needed
        if not video_path.startswith('http') and not os.path.exists(video_path):
            # Extract base filename and change extension to .mp4
            base_name = os.path.splitext(video_path)[0]
            video_path = f'https://media.signcollect.nl/{base_name}.mp4'
            log(f"  Converted to URL: {video_path}")

        log(f"  Loading video...")
        main_window.signal_emitter.load_video_request.emit(video_path)
    log("=" * 70)


async def handle_play_message(data: dict):
    """Handle play command"""
    log("Received play command")
    # Note: AVF player doesn't need explicit play handling for timecode mode
    # Timecode updates will drive the seeking


async def handle_pause_message(data: dict):
    """Handle pause command"""
    log("Received pause command")
    # Note: AVF player is always in scrubbing mode when receiving timecodes


async def handle_message(message: str):
    """Handle incoming WebSocket messages"""
    try:
        data = json.loads(message)
        message_type = data.get('type', 'unknown')

        # Debug: Print raw message
        if DEBUG_WS_MESSAGES and message_type not in ['pong', 'timecode']:
            print()  # New line
            log(f"[WS RECV] Type: {message_type}")
            log(f"[WS RECV] Raw data: {json.dumps(data, indent=2)}")

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
    """Register this client as a Python AVF video player"""
    register_msg = json.dumps({
        'type': 'register',
        'clientType': 'python'
    })
    await websocket.send(register_msg)
    log('Sent registration message (AVF Player)')


async def websocket_client():
    """Main WebSocket client loop"""
    global websocket_connection, should_reconnect, should_exit

    retry_delay = 3  # seconds

    def update_status(msg):
        if main_window:
            main_window.signal_emitter.status_update.emit(msg)

    while should_reconnect and not should_exit:
        try:
            update_status(f"Connecting to {WS_URL}...")
            log(f'Connecting to WebSocket server: {WS_URL}')

            async with websockets.connect(WS_URL, ssl=True) as websocket:
                websocket_connection = websocket
                update_status("Connected! Registering...")
                log('WebSocket connected successfully!')

                # Register as Python AVF video player client
                await send_register_message(websocket)
                update_status("Registered. Waiting for video source...")

                # Listen for messages
                async for message in websocket:
                    if should_exit:
                        break
                    await handle_message(message)

        except websockets.exceptions.ConnectionClosed:
            log('WebSocket connection closed by server', 'WARN')
            update_status("Connection closed by server")
            websocket_connection = None

        except ConnectionRefusedError:
            log(f'Connection refused. Is the server running at {WS_URL}?', 'ERROR')
            update_status(f"Connection refused: {WS_URL}")
            websocket_connection = None

        except Exception as e:
            log(f'WebSocket connection error: {e}', 'ERROR')
            update_status(f"Error: {str(e)[:50]}")
            websocket_connection = None

        if should_reconnect and not should_exit:
            update_status(f"Reconnecting in {retry_delay}s...")
            log(f'Reconnecting in {retry_delay} seconds...')
            await asyncio.sleep(retry_delay)


def run_websocket_client():
    """Run the WebSocket client in a separate thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(websocket_client())


def main():
    """Main entry point."""
    global main_window

    app = QApplication(sys.argv)

    # Set application style
    app.setStyle('Fusion')

    # Create and show the window
    window = AVFVideoPlayerWindow()
    main_window = window
    window.show()

    # Start WebSocket client in background thread (if websockets available)
    if ws_enabled:
        log("Starting WebSocket client...")
        window.status_label.setText("Initializing WebSocket...")
        ws_thread = threading.Thread(target=run_websocket_client, daemon=True)
        ws_thread.start()
    else:
        log("WebSocket support disabled (library not installed)")
        window.status_label.setText("ERROR: websockets library not installed")

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
