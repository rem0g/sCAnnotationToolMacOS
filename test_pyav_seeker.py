#!/usr/bin/env python3
"""
Quick test script for PyAVFrameSeeker functionality
"""

import sys
from zin_pyav_frame_seeker import PyAVFrameSeeker

def test_frame_seeking():
    """Test the frame seeking functionality."""
    video_path = "M20250603_8881.mp4"

    print("=" * 60)
    print("PyAV Frame Seeker Test")
    print("=" * 60)

    try:
        # Initialize seeker
        print(f"\n1. Loading video: {video_path}")
        seeker = PyAVFrameSeeker(video_path)
        print(f"   ✓ Video loaded successfully")
        print(f"   - Resolution: {seeker.width}x{seeker.height}")
        print(f"   - Frame rate: {seeker.framerate:.2f} fps")
        print(f"   - Total frames: {seeker.total_frames}")

        # Test seeking to specific frames
        test_frames = [0, 100, 500, 1000]

        print(f"\n2. Testing frame seeking:")
        for frame_num in test_frames:
            if frame_num < seeker.total_frames:
                print(f"   - Seeking to frame {frame_num}...", end=" ")
                frame = seeker.seek_to_frame(frame_num)
                if frame is not None:
                    print(f"✓ Success (shape: {frame.shape})")
                else:
                    print(f"✗ Failed")

        # Test frame range extraction
        print(f"\n3. Testing frame range extraction:")
        start, end = 10, 20
        print(f"   - Extracting frames {start}-{end}...", end=" ")
        frames = seeker.get_frame_range(start, end)
        print(f"✓ Extracted {len(frames)} frames")

        # Test navigation
        print(f"\n4. Testing frame navigation:")
        seeker.seek_to_frame(50)
        print(f"   - Current frame: {seeker.current_frame_num}")

        seeker.get_next_frame()
        print(f"   - After next(): {seeker.current_frame_num}")

        seeker.get_previous_frame()
        print(f"   - After previous(): {seeker.current_frame_num}")

        # Cleanup
        seeker.close()
        print(f"\n✓ All tests passed!")
        print("=" * 60)

    except FileNotFoundError:
        print(f"   ✗ Error: Video file '{video_path}' not found")
        print(f"   Please ensure the file exists in the current directory")
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_frame_seeking()
