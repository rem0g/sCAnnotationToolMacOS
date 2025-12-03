#!/usr/bin/env python3
"""
PyAV Frame Seeker - Efficient frame-accurate video seeking using PyAV
Uses the optimized seeking algorithm from PyAV discussion #1113
"""

import sys
import av
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                              QHBoxLayout, QLabel, QPushButton, QSlider,
                              QLineEdit, QFileDialog, QMessageBox, QSpinBox,
                              QGroupBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap


class PyAVFrameSeeker:
    """
    Efficient frame seeking utility using PyAV.
    Implements the optimized seeking algorithm from PyAV discussion #1113.
    """

    def __init__(self, video_path):
        """
        Initialize the frame seeker with a video file.

        Args:
            video_path: Path to the video file
        """
        self.video_path = video_path
        self.container = av.open(video_path)
        self.stream = self.container.streams.video[0]

        # Cache video metadata
        self.framerate = float(self.stream.average_rate)
        self.time_base = self.stream.time_base
        self.total_frames = self.stream.frames

        # If total_frames is not available, estimate from duration
        if self.total_frames == 0:
            duration = self.stream.duration
            if duration:
                self.total_frames = int(duration * self.time_base * self.framerate)

        self.width = self.stream.width
        self.height = self.stream.height
        self.current_frame_num = 0
        self.current_frame = None

        print(f"Video loaded: {self.width}x{self.height}, {self.framerate:.2f} fps, {self.total_frames} frames")

    def seek_to_frame(self, frame_num):
        """
        Seek to a specific frame number using the optimized algorithm.

        This method:
        1. Seeks to approximate time position
        2. Gets the actual keyframe position
        3. Iterates through remaining frames to target

        Args:
            frame_num: Target frame number (0-indexed)

        Returns:
            numpy array of the frame in RGB format, or None if seek fails
        """
        if frame_num < 0 or frame_num >= self.total_frames:
            print(f"Frame {frame_num} out of range (0-{self.total_frames-1})")
            return None

        try:
            # Calculate timestamp for target frame
            sec = int(frame_num / self.framerate)

            # Seek to approximate time position (backward to nearest keyframe)
            # Note: offset is in microseconds (AV_TIME_BASE units)
            self.container.seek(sec * 1000000, backward=True)

            # Get the first available frame after seeking
            frame = next(self.container.decode(video=0))

            # Calculate the actual frame number of the keyframe we landed on
            sec_frame = int(frame.pts * self.time_base * self.framerate)

            # Iterate through remaining frames to reach target
            for _ in range(sec_frame, frame_num):
                frame = next(self.container.decode(video=0))

            # Convert frame to numpy array
            self.current_frame = frame.to_ndarray(format='rgb24')
            self.current_frame_num = frame_num

            return self.current_frame

        except StopIteration:
            print(f"Could not decode frame {frame_num}")
            return None
        except Exception as e:
            print(f"Error seeking to frame {frame_num}: {e}")
            return None

    def get_frame_range(self, start_frame, end_frame):
        """
        Extract a range of consecutive frames.

        Args:
            start_frame: First frame number (inclusive)
            end_frame: Last frame number (inclusive)

        Returns:
            List of numpy arrays, one per frame
        """
        frames = []

        if start_frame < 0 or end_frame >= self.total_frames or start_frame > end_frame:
            print(f"Invalid frame range: {start_frame}-{end_frame}")
            return frames

        # Seek to start frame
        self.seek_to_frame(start_frame)
        if self.current_frame is not None:
            frames.append(self.current_frame.copy())

        # Get remaining frames in range
        try:
            for frame_num in range(start_frame + 1, end_frame + 1):
                frame = next(self.container.decode(video=0))
                frame_array = frame.to_ndarray(format='rgb24')
                frames.append(frame_array)
        except StopIteration:
            print(f"Reached end of video at frame {len(frames) + start_frame}")
        except Exception as e:
            print(f"Error extracting frame range: {e}")

        return frames

    def get_next_frame(self):
        """Get the next frame in sequence."""
        return self.seek_to_frame(self.current_frame_num + 1)

    def get_previous_frame(self):
        """Get the previous frame in sequence."""
        return self.seek_to_frame(self.current_frame_num - 1)

    def close(self):
        """Close the video container."""
        if self.container:
            self.container.close()


class VideoPlayerWindow(QMainWindow):
    """
    PyQt5-based video player window with frame seeking controls.
    """

    def __init__(self):
        super().__init__()
        self.seeker = None
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("PyAV Frame Seeker")
        self.setGeometry(100, 100, 1000, 800)

        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Video display area
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("QLabel { background-color: black; }")
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setText("No video loaded")
        main_layout.addWidget(self.video_label, stretch=1)

        # File controls
        file_layout = QHBoxLayout()
        self.file_path_label = QLabel("No file loaded")
        file_layout.addWidget(self.file_path_label)
        open_button = QPushButton("Open Video")
        open_button.clicked.connect(self.open_video)
        file_layout.addWidget(open_button)
        main_layout.addLayout(file_layout)

        # Timeline slider
        timeline_layout = QVBoxLayout()
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.valueChanged.connect(self.on_slider_changed)
        timeline_layout.addWidget(self.timeline_slider)

        # Frame info display
        self.frame_info_label = QLabel("Frame: 0 / 0")
        self.frame_info_label.setAlignment(Qt.AlignCenter)
        timeline_layout.addWidget(self.frame_info_label)
        main_layout.addLayout(timeline_layout)

        # Navigation controls
        nav_layout = QHBoxLayout()

        self.prev_button = QPushButton("◀ Previous")
        self.prev_button.setEnabled(False)
        self.prev_button.clicked.connect(self.previous_frame)
        nav_layout.addWidget(self.prev_button)

        self.play_button = QPushButton("▶ Play")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.toggle_play)
        nav_layout.addWidget(self.play_button)

        self.next_button = QPushButton("Next ▶")
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self.next_frame)
        nav_layout.addWidget(self.next_button)

        main_layout.addLayout(nav_layout)

        # Seek controls group
        seek_group = QGroupBox("Frame Seeking")
        seek_layout = QHBoxLayout()

        seek_layout.addWidget(QLabel("Go to frame:"))
        self.frame_input = QSpinBox()
        self.frame_input.setEnabled(False)
        self.frame_input.setMinimum(0)
        self.frame_input.setMaximum(0)
        self.frame_input.returnPressed = lambda: self.seek_to_frame()
        seek_layout.addWidget(self.frame_input)

        seek_button = QPushButton("Seek")
        seek_button.setEnabled(False)
        seek_button.clicked.connect(self.seek_to_frame)
        seek_layout.addWidget(seek_button)
        self.seek_button = seek_button

        seek_group.setLayout(seek_layout)
        main_layout.addWidget(seek_group)

        # Frame range extraction group
        range_group = QGroupBox("Frame Range Extraction")
        range_layout = QHBoxLayout()

        range_layout.addWidget(QLabel("Start:"))
        self.range_start_input = QSpinBox()
        self.range_start_input.setEnabled(False)
        self.range_start_input.setMinimum(0)
        self.range_start_input.setMaximum(0)
        range_layout.addWidget(self.range_start_input)

        range_layout.addWidget(QLabel("End:"))
        self.range_end_input = QSpinBox()
        self.range_end_input.setEnabled(False)
        self.range_end_input.setMinimum(0)
        self.range_end_input.setMaximum(0)
        range_layout.addWidget(self.range_end_input)

        extract_button = QPushButton("Extract Range")
        extract_button.setEnabled(False)
        extract_button.clicked.connect(self.extract_range)
        range_layout.addWidget(extract_button)
        self.extract_button = extract_button

        range_group.setLayout(range_layout)
        main_layout.addWidget(range_group)

        # Playback state
        self.is_playing = False
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self.play_next_frame)

    def open_video(self):
        """Open a video file dialog and load the selected video."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Video File",
            "",
            "Video Files (*.mp4 *.avi *.mkv *.mov);;All Files (*)"
        )

        if file_path:
            self.load_video(file_path)

    def load_video(self, video_path):
        """Load a video file using PyAVFrameSeeker."""
        try:
            # Close existing seeker if any
            if self.seeker:
                self.seeker.close()

            # Create new seeker
            self.seeker = PyAVFrameSeeker(video_path)

            # Update UI
            self.file_path_label.setText(f"File: {video_path.split('/')[-1]}")

            # Enable controls
            self.timeline_slider.setEnabled(True)
            self.timeline_slider.setMaximum(self.seeker.total_frames - 1)
            self.timeline_slider.setValue(0)

            self.frame_input.setEnabled(True)
            self.frame_input.setMaximum(self.seeker.total_frames - 1)
            self.seek_button.setEnabled(True)

            self.range_start_input.setEnabled(True)
            self.range_start_input.setMaximum(self.seeker.total_frames - 1)
            self.range_end_input.setEnabled(True)
            self.range_end_input.setMaximum(self.seeker.total_frames - 1)
            self.range_end_input.setValue(min(10, self.seeker.total_frames - 1))
            self.extract_button.setEnabled(True)

            self.prev_button.setEnabled(True)
            self.play_button.setEnabled(True)
            self.next_button.setEnabled(True)

            # Load first frame
            self.display_frame(0)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load video:\n{str(e)}")

    def display_frame(self, frame_num):
        """Display a specific frame."""
        if not self.seeker:
            return

        frame_array = self.seeker.seek_to_frame(frame_num)

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

            # Update frame info
            self.frame_info_label.setText(f"Frame: {frame_num} / {self.seeker.total_frames - 1}")

            # Update slider without triggering valueChanged
            self.timeline_slider.blockSignals(True)
            self.timeline_slider.setValue(frame_num)
            self.timeline_slider.blockSignals(False)

    def seek_to_frame(self):
        """Seek to the frame number entered in the input field."""
        frame_num = self.frame_input.value()
        self.display_frame(frame_num)

    def on_slider_changed(self, value):
        """Handle timeline slider changes."""
        self.display_frame(value)

    def previous_frame(self):
        """Go to the previous frame."""
        if self.seeker and self.seeker.current_frame_num > 0:
            self.display_frame(self.seeker.current_frame_num - 1)

    def next_frame(self):
        """Go to the next frame."""
        if self.seeker and self.seeker.current_frame_num < self.seeker.total_frames - 1:
            self.display_frame(self.seeker.current_frame_num + 1)

    def toggle_play(self):
        """Toggle play/pause."""
        if not self.seeker:
            return

        self.is_playing = not self.is_playing

        if self.is_playing:
            self.play_button.setText("⏸ Pause")
            # Calculate frame interval in milliseconds
            interval = int(1000 / self.seeker.framerate)
            self.play_timer.start(interval)
        else:
            self.play_button.setText("▶ Play")
            self.play_timer.stop()

    def play_next_frame(self):
        """Play the next frame (called by timer)."""
        if self.seeker.current_frame_num < self.seeker.total_frames - 1:
            self.next_frame()
        else:
            # Reached end of video
            self.toggle_play()

    def extract_range(self):
        """Extract and display information about a frame range."""
        start = self.range_start_input.value()
        end = self.range_end_input.value()

        if start > end:
            QMessageBox.warning(self, "Invalid Range", "Start frame must be <= end frame")
            return

        if end - start > 100:
            reply = QMessageBox.question(
                self,
                "Large Range",
                f"You are about to extract {end - start + 1} frames. Continue?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        # Extract frames
        frames = self.seeker.get_frame_range(start, end)

        QMessageBox.information(
            self,
            "Range Extracted",
            f"Extracted {len(frames)} frames from {start} to {end}\n"
            f"Frame shape: {frames[0].shape if frames else 'N/A'}\n"
            f"Memory usage: ~{len(frames) * frames[0].nbytes / 1024 / 1024:.1f} MB"
        )

        # Display the first frame of the range
        if frames:
            self.display_frame(start)

    def closeEvent(self, event):
        """Handle window close event."""
        if self.seeker:
            self.seeker.close()
        event.accept()


def main():
    """Main entry point."""
    app = QApplication(sys.argv)

    # Create and show the window
    window = VideoPlayerWindow()
    window.show()

    # If a video path is provided as command-line argument, load it
    if len(sys.argv) > 1:
        video_path = sys.argv[1]
        window.load_video(video_path)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
