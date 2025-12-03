#!/usr/bin/env python3
"""Simple test to isolate AVFoundation issues"""

import sys
from Foundation import NSURL
from AVFoundation import AVURLAsset, AVAssetImageGenerator, AVMediaTypeVideo
from CoreMedia import CMTimeMake, kCMTimeZero
from Quartz.CoreGraphics import (
    CGImageGetDataProvider, CGDataProviderCopyData,
    CGImageGetWidth, CGImageGetHeight,
    CGImageRelease
)
from CoreFoundation import CFDataGetBytePtr, CFDataGetLength, CFRelease
import numpy as np

print("Step 1: Loading video...")
url = NSURL.fileURLWithPath_('/Users/gomerotterspeer/zin_app/M20250603_8881.mp4')
asset = AVURLAsset.URLAssetWithURL_options_(url, None)
print(f"Asset created: {asset}")

print("\nStep 2: Creating generator...")
generator = AVAssetImageGenerator.assetImageGeneratorWithAsset_(asset)
generator.setRequestedTimeToleranceBefore_(kCMTimeZero)
generator.setRequestedTimeToleranceAfter_(kCMTimeZero)
print(f"Generator created: {generator}")

print("\nStep 3: Extracting frame...")
req_time = CMTimeMake(0, 1000)
result = generator.copyCGImageAtTime_actualTime_error_(req_time, None, None)
print(f"Result type: {type(result)}")
print(f"Result: {result}")

if result and len(result) >= 1:
    image = result[0]
    print(f"\nStep 4: Got image: {image}")
    print(f"Width: {CGImageGetWidth(image)}")
    print(f"Height: {CGImageGetHeight(image)}")

    print("\nStep 5: Getting data provider...")
    data_provider = CGImageGetDataProvider(image)
    print(f"Data provider: {data_provider}")

    print("\nStep 6: Copying data...")
    data_ref = CGDataProviderCopyData(data_provider)
    print(f"Data ref: {data_ref}")

    print("\nStep 7: Working with data...")
    print(f"Data ref type: {type(data_ref)}")
    print(f"Data ref is bytes: {isinstance(data_ref, bytes)}")
    print(f"Data length: {len(data_ref)}")
    print(f"First 20 bytes: {data_ref[:20]}")

    print("\nStep 8: Converting to numpy...")
    try:
        import numpy as np
        arr = np.frombuffer(data_ref, dtype=np.uint8)
        print(f"Numpy array shape: {arr.shape}")
        print(f"Array dtype: {arr.dtype}")
        print(f"First 10 values: {arr[:10]}")
    except Exception as e:
        print(f"Numpy conversion failed: {e}")
        import traceback
        traceback.print_exc()

    print("\nStep 9: Cleanup...")
    CGImageRelease(image)
    print("Done!")
else:
    print("Failed to extract frame!")
