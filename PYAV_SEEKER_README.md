# PyAV Frame Seeker

A high-performance video player with frame-accurate seeking using PyAV.

## Features

- **Efficient Frame Seeking**: Uses optimized algorithm from [PyAV Discussion #1113](https://github.com/PyAV-Org/PyAV/discussions/1113)
- **Frame-Accurate Navigation**: Seek to any frame number instantly
- **Frame Range Extraction**: Extract multiple consecutive frames
- **Interactive GUI**: PyQt5-based interface with timeline slider
- **Playback Controls**: Play/pause, next/previous frame navigation

## Installation

Make sure PyAV and PyQt5 are installed:

```bash
source venv/bin/activate  # Activate your virtual environment
pip install av PyQt5 numpy
```

## Usage

### GUI Mode (Video Player)

Launch the video player with GUI:

```bash
python3 zin_pyav_frame_seeker.py
```

Or load a video directly:

```bash
python3 zin_pyav_frame_seeker.py M20250603_8881.mp4
```

### Programmatic Usage

Use the `PyAVFrameSeeker` class in your own scripts:

```python
from zin_pyav_frame_seeker import PyAVFrameSeeker

# Initialize with video file
seeker = PyAVFrameSeeker("M20250603_8881.mp4")

# Seek to specific frame
frame = seeker.seek_to_frame(1000)  # Returns numpy array (RGB)

# Get frame range
frames = seeker.get_frame_range(100, 200)  # Returns list of numpy arrays

# Navigate frames
next_frame = seeker.get_next_frame()
prev_frame = seeker.get_previous_frame()

# Get video info
print(f"Resolution: {seeker.width}x{seeker.height}")
print(f"FPS: {seeker.framerate}")
print(f"Total frames: {seeker.total_frames}")

# Cleanup
seeker.close()
```

## How It Works

The frame seeking algorithm optimizes performance by:

1. **Time-based seeking**: Calculates approximate timestamp for target frame
2. **Keyframe alignment**: Seeks backward to nearest keyframe
3. **Frame iteration**: Decodes only remaining frames to reach target

This approach is significantly faster than decoding from the beginning, especially for long videos.

### Algorithm Details

```python
frame_num = 1000  # Target frame
framerate = container.streams.video[0].average_rate
time_base = container.streams.video[0].time_base

# Calculate time position
sec = int(frame_num / framerate)

# Seek to approximate position (backward to keyframe)
container.seek(sec * 1000000, backward=True)

# Get keyframe and calculate its frame number
frame = next(container.decode(video=0))
sec_frame = int(frame.pts * time_base * framerate)

# Iterate remaining frames to target
for _ in range(sec_frame, frame_num):
    frame = next(container.decode(video=0))
```

## GUI Controls

- **Open Video**: Load a video file
- **Timeline Slider**: Scrub through video by dragging
- **Previous/Next**: Navigate frame by frame
- **Play/Pause**: Continuous playback at original framerate
- **Frame Input**: Enter specific frame number and seek
- **Frame Range**: Extract multiple consecutive frames

## Testing

Run the test script to verify functionality:

```bash
python3 test_pyav_seeker.py
```

This tests:
- Video loading and metadata extraction
- Frame seeking to various positions
- Frame range extraction
- Frame navigation (next/previous)

## Video Information

Your test video (`M20250603_8881.mp4`):
- Resolution: 1594x1386
- Frame rate: 59.94 fps
- Total frames: 6780
- Duration: ~113 seconds

## Performance

The optimized seeking algorithm provides:
- **Sub-second seeks** to any frame in the video
- **Minimal memory usage** (only current frame in memory)
- **Frame-accurate positioning** (no approximation)

Compare this to the naive approach of iterating from frame 0, which would take several seconds for frames near the end of the video.

## Credits

Based on the solution from [PyAV Discussion #1113](https://github.com/PyAV-Org/PyAV/discussions/1113) by the PyAV community.
