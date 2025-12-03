#!/usr/bin/env python3

"""
ZIN Video Player with VLC + PyQt5 and WebSocket Timecode Control

This Python script connects to the ZIN WebSocket server and uses VLC
with PyQt5 GUI for high-performance video playback with accurate timecode seeking.

Usage:
    python zin_video_player_qt.py

Dependencies:
    pip install websockets python-vlc PyQt5

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

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QFrame
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt5.QtGui import QPalette, QColor

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
target_time = 0.0
seek_threshold = 0.05  # Only seek if difference is > 50ms


def log(message: str, level: str = 'INFO'):
    """Log a message with timestamp"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f'[{timestamp}] [{level}] {message}')


class SignalEmitter(QObject):
    """Signal emitter for thread-safe GUI updates"""
    status_update = pyqtSignal(str)


class VideoPlayerWindow(QMainWindow):
    """Main video player window"""

    def __init__(self):
        super().__init__()
        self.signal_emitter = SignalEmitter()
        self.signal_emitter.status_update.connect(self.update_status)
        self.is_scrubbing = True  # Always in scrubbing mode by default
        self.init_ui()
        self.init_vlc()
        self.init_timer()

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("ZIN Video Player (VLC + PyQt5)")
        self.resize(1280, 720)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Video frame
        self.video_frame = QFrame()
        self.video_frame.setStyleSheet("background-color: black;")
        layout.addWidget(self.video_frame)

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

    def init_vlc(self):
        """Initialize VLC player"""
        global vlc_instance, vlc_player

        vlc_instance = vlc.Instance()
        vlc_player = vlc_instance.media_player_new()

        # Set video output to our widget
        if sys.platform.startswith('darwin'):  # macOS
            vlc_player.set_nsobject(int(self.video_frame.winId()))
        elif sys.platform.startswith('win'):  # Windows
            vlc_player.set_hwnd(self.video_frame.winId())
        else:  # Linux
            vlc_player.set_xwindow(self.video_frame.winId())

        log("VLC player initialized")

    def init_timer(self):
        """Initialize timer for keeping video paused at specific position"""
        self.timer = QTimer(self)
        self.timer.setInterval(50)  # 50ms = 20fps update rate
        self.timer.timeout.connect(self.maintain_position)
        self.timer.start()

    def maintain_position(self):
        """Maintain video at target position when scrubbing"""
        global target_time

        if vlc_player and self.is_scrubbing and target_time >= 0:
            current_time = vlc_player.get_time()
            if current_time >= 0:
                target_ms = int(target_time * 1000)
                # Keep video at the target position by continuously seeking
                # This creates a "frozen" frame effect while video stays playing
                if abs(current_time - target_ms) > 50:  # More than 50ms off
                    vlc_player.set_time(target_ms)

    def update_status(self, message: str):
        """Update status label"""
        self.status_label.setText(message)

    def closeEvent(self, event):
        """Handle window close event"""
        global should_reconnect, should_exit

        log("Closing application...")
        should_reconnect = False
        should_exit = True

        # Stop VLC player
        if vlc_player:
            vlc_player.stop()
            vlc_player.release()
        if vlc_instance:
            vlc_instance.release()

        event.accept()


# Global reference to main window
main_window = None


def load_video(url: str) -> bool:
    """Load a video file or URL"""
    global vlc_player

    if vlc_player is None:
        log("VLC player not initialized", 'ERROR')
        return False

    try:
        media = vlc_instance.media_new(url)

        # Parse the metadata of the file
        media.parse()

        # Put the media in the media player
        vlc_player.set_media(media)

        # Start playing - we'll keep it playing to avoid "reading while paused" error
        vlc_player.play()

        # Wait a moment for decoder to initialize
        import time
        time.sleep(0.3)

        log(f"Loaded video: {url}")
        if main_window:
            main_window.signal_emitter.status_update.emit(f"Loaded: {url}")
        return True
    except Exception as e:
        log(f"Failed to load video: {e}", 'ERROR')
        return False


def seek_video(time_seconds: float):
    """Seek to a specific time in the video"""
    global target_time

    if vlc_player is None:
        return

    # Update target time - the timer will maintain this position
    target_time = time_seconds

    # Keep playing but timer will maintain position
    # This avoids "reading while paused" error
    if not vlc_player.is_playing():
        vlc_player.play()

    # Set the time position immediately
    vlc_player.set_time(int(time_seconds * 1000))


def set_playing(playing: bool):
    """Set playback state"""
    if vlc_player is None:
        return

    if main_window:
        main_window.is_scrubbing = not playing

    if playing:
        vlc_player.play()
        log("Started playback")
    else:
        vlc_player.pause()
        log("Paused playback (scrubbing mode)")


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


def main():
    """Main entry point"""
    global main_window

    print('=' * 60)
    print('ZIN Video Player (VLC + PyQt5) with WebSocket Control')
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
