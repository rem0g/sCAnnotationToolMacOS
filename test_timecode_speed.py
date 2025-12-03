#!/usr/bin/env python3

"""
ZIN Timecode Speed Test

This script connects to the WebSocket server and measures the timecode update rate.
It displays statistics about messages received per second.

Usage:
    python test_timecode_speed.py
"""

import asyncio
import json
import time
from datetime import datetime

try:
    import websockets
except ImportError:
    print("Error: websockets library not found.")
    print("Install with: pip install websockets")
    exit(1)

# Configuration
WS_URL = 'wss://signcollect.nl/zin_wss'

# Statistics
message_count = 0
timecode_count = 0
start_time = None
last_stats_time = None
messages_last_second = 0
last_timecode = None


def log(message: str):
    """Log a message with timestamp"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f'[{timestamp}] {message}')


async def handle_message(message: str):
    """Handle incoming WebSocket messages"""
    global message_count, timecode_count, messages_last_second, last_timecode

    try:
        data = json.loads(message)
        message_type = data.get('type', 'unknown')
        message_count += 1
        messages_last_second += 1

        if message_type == 'connection':
            log(f"Connected: {data.get('message', '')}")

        elif message_type == 'registered':
            log(f"Registered as: {data.get('clientType', 'unknown')}")

        elif message_type == 'timecode':
            timecode_count += 1
            current_time = data.get('currentTime', 0)

            # Calculate time delta if we have previous timecode
            if last_timecode is not None:
                delta = current_time - last_timecode
                delta_ms = delta * 1000
                fps_estimate = 1.0 / delta if delta > 0 else 0
                print(f'\r[TC #{timecode_count}] Time: {current_time:.3f}s | Delta: {delta_ms:.1f}ms | Est FPS: {fps_estimate:.1f}    ', end='', flush=True)
            else:
                print(f'\r[TC #{timecode_count}] Time: {current_time:.3f}s', end='', flush=True)

            last_timecode = current_time

        elif message_type == 'video_info':
            print()  # New line
            log(f"Video: {data.get('filename', 'unknown')} | Duration: {data.get('duration', 0):.2f}s | FPS: {data.get('fps', 60)}")

        elif message_type == 'play':
            print()  # New line
            log("Play command received")

        elif message_type == 'pause':
            print()  # New line
            log("Pause command received")

    except json.JSONDecodeError as e:
        log(f"Error parsing JSON: {e}")
    except Exception as e:
        log(f"Error handling message: {e}")


async def print_statistics():
    """Print statistics every second"""
    global last_stats_time, messages_last_second, start_time

    while True:
        await asyncio.sleep(1.0)

        elapsed = time.time() - start_time
        avg_msg_per_sec = message_count / elapsed if elapsed > 0 else 0

        print()  # New line
        log(f"Stats: {messages_last_second} msg/s | Total: {message_count} msgs, {timecode_count} timecodes | Avg: {avg_msg_per_sec:.1f} msg/s")

        messages_last_second = 0


async def websocket_client():
    """Main WebSocket client loop"""
    global start_time

    try:
        log(f'Connecting to: {WS_URL}')

        async with websockets.connect(WS_URL, ssl=True) as websocket:
            log('Connected!')
            start_time = time.time()

            # Register as test client
            register_msg = json.dumps({
                'type': 'register',
                'clientType': 'python'
            })
            await websocket.send(register_msg)
            log('Registered as python client')

            # Start statistics printer
            stats_task = asyncio.create_task(print_statistics())

            # Listen for messages
            try:
                async for message in websocket:
                    await handle_message(message)
            except KeyboardInterrupt:
                stats_task.cancel()
                raise

    except websockets.exceptions.ConnectionClosed:
        log('Connection closed by server')
    except Exception as e:
        log(f'Error: {e}')


async def main():
    """Main entry point"""
    print('=' * 70)
    print('ZIN Timecode Speed Test')
    print('=' * 70)
    log(f'Server: {WS_URL}')
    log('Press Ctrl+C to exit')
    print('=' * 70)

    try:
        await websocket_client()
    except KeyboardInterrupt:
        print()  # New line
        log('Interrupted by user')

        # Print final statistics
        if start_time:
            elapsed = time.time() - start_time
            avg_msg_per_sec = message_count / elapsed if elapsed > 0 else 0
            print()
            print('=' * 70)
            log('Final Statistics:')
            log(f'  Total messages: {message_count}')
            log(f'  Total timecodes: {timecode_count}')
            log(f'  Duration: {elapsed:.1f}s')
            log(f'  Average rate: {avg_msg_per_sec:.1f} msg/s')
            print('=' * 70)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
