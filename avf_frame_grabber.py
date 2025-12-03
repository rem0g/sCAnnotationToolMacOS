#!/usr/bin/env python3
"""
AVFoundation Frame Grabber - Native macOS frame-accurate video seeking
Based on ELAN 7.0's AVFFrameGrabber implementation
Provides zero-tolerance frame-perfect seeking using macOS AVFoundation framework
"""

import os
import sys
import numpy as np

# Check platform
if sys.platform != 'darwin':
    raise RuntimeError("AVFoundation is only available on macOS")

try:
    from Foundation import NSURL
    from AVFoundation import (
        AVURLAsset,
        AVAssetImageGenerator,
        AVMediaTypeVideo
    )
    from CoreMedia import (
        CMTimeMake,
        CMTimeGetSeconds,
        kCMTimeZero
    )
    from Quartz.CoreGraphics import (
        CGImageGetDataProvider,
        CGDataProviderCopyData,
        CGImageGetWidth,
        CGImageGetHeight,
        CGImageGetBitsPerPixel,
        CGImageGetBitsPerComponent,
        CGImageGetBytesPerRow,
        CGImageGetAlphaInfo,
        CGImageRelease,
        kCGImageAlphaNoneSkipLast,
        kCGImageAlphaNoneSkipFirst,
        kCGImageAlphaPremultipliedLast,
        kCGImageAlphaPremultipliedFirst
    )
    from Quartz.ImageIO import (
        CGImageDestinationCreateWithURL,
        CGImageDestinationAddImage,
        CGImageDestinationFinalize
    )
    from CoreFoundation import (
        CFDataGetBytePtr,
        CFDataGetLength,
        CFRelease
    )
    # UTType constants - use string literals for compatibility
    kUTTypePNG = 'public.png'
    kUTTypeJPEG = 'public.jpeg'
    kUTTypeBMP = 'com.microsoft.bmp'
except ImportError as e:
    raise RuntimeError(f"PyObjC not installed. Run: pip install pyobjc-framework-AVFoundation pyobjc-framework-Quartz\nError: {e}")


class AVFFrameGrabber:
    """
    Native macOS frame grabber using AVFoundation.

    This implementation replicates ELAN 7.0's high-performance frame seeking:
    - Zero-tolerance seeking (exact frames, no approximation)
    - Hardware-accelerated decoding (VideoToolbox)
    - Direct pixel buffer access (minimal copying)
    - Frame-accurate time calculations using CMTime

    Based on: elan-7.0/native/AVFPlayer/AVFFrameGrabber/src/nl_mpi_avf_frame_AVFFrameGrabber.mm
    """

    def __init__(self, video_path):
        """
        Initialize the AVFoundation frame grabber.

        Args:
            video_path: Path to video file (local path or URL)

        Raises:
            FileNotFoundError: If local video file doesn't exist
            ValueError: If no video tracks found
            RuntimeError: If frame extraction fails during initialization
        """
        self.video_path = video_path

        # Check if it's a URL or local file path
        if video_path.startswith('http://') or video_path.startswith('https://'):
            # It's a URL - create NSURL directly from string
            print(f"Loading video from URL: {video_path}")
            self.url = NSURL.URLWithString_(video_path)
        else:
            # It's a local file path
            # Resolve to absolute path
            if not video_path.startswith('/'):
                video_path = os.path.abspath(video_path)

            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")

            # Create NSURL from file path (ELAN: nl_mpi_avf_frame_AVFFrameGrabber.mm:79)
            self.url = NSURL.fileURLWithPath_(video_path)

        # Create AVURLAsset (ELAN: line 94)
        self.asset = AVURLAsset.URLAssetWithURL_options_(self.url, None)

        # Get duration (ELAN: lines 98-102)
        cm_duration = self.asset.duration()
        self.duration_seconds = float(cm_duration.value) / float(cm_duration.timescale)
        self.duration_ms = int(self.duration_seconds * 1000)

        # Get video tracks (ELAN: lines 106-117)
        video_tracks = self.asset.tracksWithMediaType_(AVMediaTypeVideo)

        if not video_tracks or len(video_tracks) == 0:
            raise ValueError("No video tracks found in file")

        self.video_track = video_tracks[0]

        # Get video dimensions from natural size (ELAN: lines 119-122)
        nat_size = self.video_track.naturalSize()
        self.video_width = int(nat_size.width)
        self.video_height = int(nat_size.height)

        # Get frame rate (ELAN: line 124)
        self.framerate = float(self.video_track.nominalFrameRate())

        # Calculate total frames
        self.total_frames = int(self.duration_seconds * self.framerate)

        # Create image generator (ELAN: lines 127-129)
        self.generator = AVAssetImageGenerator.assetImageGeneratorWithAsset_(self.asset)

        # CRITICAL: Set zero tolerance for frame-accurate seeking (ELAN: lines 131-134)
        # This forces AVFoundation to return the EXACT frame requested, not an approximation
        self.generator.setRequestedTimeToleranceBefore_(kCMTimeZero)
        self.generator.setRequestedTimeToleranceAfter_(kCMTimeZero)

        # Extract test frame to initialize image metadata (ELAN: lines 138-147)
        test_time = CMTimeMake(cm_duration.value // 2, cm_duration.timescale)

        # Extract frame - PyObjC returns tuple (image, actual_time)
        try:
            test_image = self.generator.copyCGImageAtTime_actualTime_error_(test_time, None, None)[0]
        except (TypeError, IndexError):
            raise RuntimeError("Failed to extract test frame")

        if not test_image:
            raise RuntimeError("No image returned from test frame extraction")

        # Get image metadata (ELAN: lines 153-258)
        self.bits_per_component = CGImageGetBitsPerComponent(test_image)
        self.bits_per_pixel = CGImageGetBitsPerPixel(test_image)
        self.bytes_per_row = CGImageGetBytesPerRow(test_image)
        self.image_width = CGImageGetWidth(test_image)
        self.image_height = CGImageGetHeight(test_image)
        self.alpha_info = CGImageGetAlphaInfo(test_image)

        # Calculate frame size
        self.frame_bytes = self.bytes_per_row * self.image_height

        # Determine if we have alpha channel
        self.has_alpha = self.alpha_info in (
            kCGImageAlphaPremultipliedLast,
            kCGImageAlphaPremultipliedFirst,
            kCGImageAlphaNoneSkipLast,
            kCGImageAlphaNoneSkipFirst
        )

        # Release test image (ELAN pattern: always release CGImage)
        CGImageRelease(test_image)

        print(f"AVF Video loaded: {self.video_width}x{self.video_height}, "
              f"{self.framerate:.2f} fps, {self.total_frames} frames")
        print(f"Image format: {self.bits_per_component} bpc, {self.bits_per_pixel} bpp, "
              f"{self.bytes_per_row} bytes/row, alpha={self.has_alpha}")

    def grab_frame_at_time(self, time_ms):
        """
        Grab a frame at a specific time in milliseconds.

        Implements ELAN's grabVideoFrame method (nl_mpi_avf_frame_AVFFrameGrabber.mm:285-336)

        Args:
            time_ms: Time in milliseconds

        Returns:
            numpy array (height, width, 3) in RGB format, or None if error
        """
        # Create CMTime with timescale 1000 (ELAN: line 296)
        # ELAN uses milliseconds for convenience
        req_time = CMTimeMake(int(time_ms), 1000)

        # Extract frame (ELAN: lines 300-303)
        # PyObjC handling: copyCGImageAtTime with error parameter
        try:
            image = self.generator.copyCGImageAtTime_actualTime_error_(req_time, None, None)[0]
        except (TypeError, IndexError):
            print(f"Error extracting frame at {time_ms}ms")
            return None

        if not image:
            print(f"No image returned for time {time_ms}ms")
            return None

        # Extract raw pixel data (ELAN: lines 308-312)
        data_provider = CGImageGetDataProvider(image)

        # PyObjC simplification: CGDataProviderCopyData returns bytes directly!
        # No need for CFDataGetBytePtr - data_ref IS the bytes
        data_ref = CGDataProviderCopyData(data_provider)

        # Convert bytes to numpy array
        bytes_per_pixel = self.bits_per_pixel // 8
        frame_array = np.frombuffer(data_ref, dtype=np.uint8)

        # Reshape accounting for row padding
        frame_array = frame_array.reshape((self.image_height, self.bytes_per_row))

        # Extract only actual image data (remove row padding if present)
        actual_row_bytes = self.image_width * bytes_per_pixel
        if self.bytes_per_row > actual_row_bytes:
            frame_array = frame_array[:, :actual_row_bytes]

        # Reshape to image dimensions
        frame_array = frame_array.reshape((self.image_height, self.image_width, bytes_per_pixel))

        # Convert to RGB (macOS typically uses BGRA or BGRX format)
        if bytes_per_pixel == 4:
            # BGRA or BGRX -> RGB (discard alpha)
            frame_rgb = np.empty((self.image_height, self.image_width, 3), dtype=np.uint8)
            frame_rgb[:, :, 0] = frame_array[:, :, 2]  # R = B
            frame_rgb[:, :, 1] = frame_array[:, :, 1]  # G = G
            frame_rgb[:, :, 2] = frame_array[:, :, 0]  # B = R
            frame_array = frame_rgb
        elif bytes_per_pixel == 3:
            # BGR -> RGB
            frame_rgb = np.empty((self.image_height, self.image_width, 3), dtype=np.uint8)
            frame_rgb[:, :, 0] = frame_array[:, :, 2]  # R
            frame_rgb[:, :, 1] = frame_array[:, :, 1]  # G
            frame_rgb[:, :, 2] = frame_array[:, :, 0]  # B
            frame_array = frame_rgb

        # Cleanup (ELAN: always release CoreFoundation objects)
        # Note: In PyObjC, data_ref is bytes so no CFRelease needed
        CGImageRelease(image)

        return frame_array

    def grab_frame_number(self, frame_num):
        """
        Grab a specific frame by frame number.

        Args:
            frame_num: Frame number (0-indexed)

        Returns:
            numpy array (height, width, 3) in RGB format, or None if error
        """
        if frame_num < 0 or frame_num >= self.total_frames:
            print(f"Frame {frame_num} out of range (0-{self.total_frames-1})")
            return None

        # Convert frame number to milliseconds (ELAN pattern)
        time_seconds = frame_num / self.framerate
        time_ms = int(time_seconds * 1000)

        return self.grab_frame_at_time(time_ms)

    def get_frame_range(self, start_frame, end_frame):
        """
        Extract a range of consecutive frames.

        Args:
            start_frame: First frame number (inclusive)
            end_frame: Last frame number (inclusive)

        Returns:
            List of numpy arrays in RGB format
        """
        frames = []

        if start_frame < 0 or end_frame >= self.total_frames or start_frame > end_frame:
            print(f"Invalid frame range: {start_frame}-{end_frame}")
            return frames

        for frame_num in range(start_frame, end_frame + 1):
            frame = self.grab_frame_number(frame_num)
            if frame is not None:
                frames.append(frame)
            else:
                print(f"Warning: Failed to extract frame {frame_num}")

        return frames

    def save_frame(self, frame_num, output_path):
        """
        Save a frame directly to disk using CoreGraphics.

        This is more efficient than grab_frame + save, as it avoids
        converting to numpy and back to image format.

        Args:
            frame_num: Frame number to save
            output_path: Output file path (PNG, JPEG, or BMP based on extension)

        Returns:
            True if successful, False otherwise
        """
        if frame_num < 0 or frame_num >= self.total_frames:
            print(f"Frame {frame_num} out of range")
            return False

        # Convert frame to time
        time_seconds = frame_num / self.framerate
        time_ms = int(time_seconds * 1000)
        req_time = CMTimeMake(time_ms, 1000)

        # Extract frame
        try:
            image = self.generator.copyCGImageAtTime_actualTime_error_(req_time, None, None)[0]
        except (TypeError, IndexError):
            print(f"Failed to extract frame {frame_num}")
            return False

        if not image:
            print(f"No image returned for frame {frame_num}")
            return False

        # Determine image type from extension
        output_url = NSURL.fileURLWithPath_(os.path.abspath(output_path))

        if output_path.lower().endswith(('.jpg', '.jpeg')):
            image_type = kUTTypeJPEG
        elif output_path.lower().endswith('.bmp'):
            image_type = kUTTypeBMP
        else:
            image_type = kUTTypePNG

        # Create destination and write
        dest_ref = CGImageDestinationCreateWithURL(output_url, image_type, 1, None)
        if not dest_ref:
            print(f"Failed to create image destination: {output_path}")
            CGImageRelease(image)
            return False

        CGImageDestinationAddImage(dest_ref, image, None)
        success = CGImageDestinationFinalize(dest_ref)

        # Cleanup
        CGImageRelease(image)
        CFRelease(dest_ref)

        return success

    def close(self):
        """
        Release resources.

        Note: PyObjC handles most memory management automatically,
        but we explicitly release references to help garbage collection.
        """
        self.generator = None
        self.asset = None
        self.video_track = None
        self.url = None


def main():
    """Test the AVFoundation frame grabber."""
    import time

    if len(sys.argv) < 2:
        print("Usage: python avf_frame_grabber.py <video_file>")
        print("\nExample:")
        print("  python avf_frame_grabber.py M20250603_8881.mp4")
        sys.exit(1)

    video_path = sys.argv[1]

    print("=" * 70)
    print("AVFoundation Frame Grabber Test")
    print("=" * 70)

    try:
        # Initialize grabber
        print(f"\n1. Loading video: {video_path}")
        start_time = time.time()
        grabber = AVFFrameGrabber(video_path)
        load_time = time.time() - start_time
        print(f"   ✓ Loaded in {load_time:.3f}s")

        # Test frame extraction
        print(f"\n2. Testing frame seeking:")
        test_frames = [0, 100, 500, 1000, grabber.total_frames - 1]

        seek_times = []
        for frame_num in test_frames:
            if frame_num < grabber.total_frames:
                print(f"   - Frame {frame_num}...", end=" ")
                start_time = time.time()
                frame = grabber.grab_frame_number(frame_num)
                seek_time = time.time() - start_time
                seek_times.append(seek_time)

                if frame is not None:
                    print(f"✓ {seek_time*1000:.1f}ms (shape: {frame.shape})")
                else:
                    print(f"✗ Failed")

        avg_seek_time = sum(seek_times) / len(seek_times) if seek_times else 0
        print(f"\n   Average seek time: {avg_seek_time*1000:.1f}ms")

        # Test frame range extraction
        print(f"\n3. Testing frame range extraction:")
        start, end = 10, 20
        print(f"   - Extracting frames {start}-{end}...", end=" ")
        start_time = time.time()
        frames = grabber.get_frame_range(start, end)
        range_time = time.time() - start_time
        print(f"✓ {len(frames)} frames in {range_time:.3f}s ({range_time/len(frames)*1000:.1f}ms per frame)")

        # Test save
        print(f"\n4. Testing frame save:")
        output_file = "test_avf_frame.png"
        print(f"   - Saving frame 0 to {output_file}...", end=" ")
        success = grabber.save_frame(0, output_file)
        if success:
            print(f"✓ Saved")
        else:
            print(f"✗ Failed")

        # Cleanup
        grabber.close()

        print(f"\n✓ All tests completed!")
        print("=" * 70)

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
