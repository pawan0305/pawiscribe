#!/usr/bin/env python3
"""
PawiScribe Device Detection Test
Tests the audio device scanning and loopback detection logic
"""

import sys

try:
    import sounddevice as sd
    import numpy as np
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    print("ERROR: sounddevice not installed. Run: pip install sounddevice")
    sys.exit(1)


def scan_devices():
    """Scan all audio devices and categorize them"""
    devices = []
    input_devices = []
    output_devices = []
    loopback_devices = []
    
    try:
        device_list = sd.query_devices()
        hostapis = sd.query_hostapis()
        
        print("=" * 70)
        print("AUDIO DEVICE SCAN REPORT")
        print("=" * 70)
        print(f"\nPlatform: {sys.platform}")
        print(f"Host APIs: {len(hostapis)}")
        for i, api in enumerate(hostapis):
            print(f"  [{i}] {api['name']} - Default input: {api.get('default_input_device', 'None')}, "
                  f"Default output: {api.get('default_output_device', 'None')}")
        
        print(f"\n{'=' * 70}")
        print("ALL DEVICES:")
        print("=" * 70)
        
        for i, dev in enumerate(device_list):
            hostapi_name = hostapis[dev['hostapi']]['name'] if dev['hostapi'] < len(hostapis) else 'Unknown'
            
            # Check if this is a loopback device
            is_loopback = False
            if 'WASAPI' in hostapi_name and dev['max_input_channels'] > 0:
                name_lower = dev['name'].lower()
                if any(keyword in name_lower for keyword in ['loopback', 'stereo mix', 'what u hear']):
                    is_loopback = True
            
            loopback_tag = " [LOOPBACK]" if is_loopback else ""
            
            print(f"\n[{i}] {dev['name']}{loopback_tag}")
            print(f"    Host API: {hostapi_name}")
            print(f"    Input channels: {dev['max_input_channels']}")
            print(f"    Output channels: {dev['max_output_channels']}")
            print(f"    Default samplerate: {dev['default_samplerate']} Hz")
            
            device_info = {
                'index': i,
                'name': dev['name'],
                'hostapi': hostapi_name,
                'max_input_channels': dev['max_input_channels'],
                'max_output_channels': dev['max_output_channels'],
                'is_loopback': is_loopback
            }
            
            devices.append(device_info)
            
            if dev['max_input_channels'] > 0 and not is_loopback:
                input_devices.append(device_info)
            if dev['max_output_channels'] > 0:
                output_devices.append(device_info)
            if is_loopback:
                loopback_devices.append(device_info)
        
        # Summary
        print(f"\n{'=' * 70}")
        print("SUMMARY:")
        print("=" * 70)
        print(f"Total devices: {len(devices)}")
        print(f"Input devices: {len(input_devices)}")
        print(f"Output devices: {len(output_devices)}")
        print(f"Loopback devices: {len(loopback_devices)}")
        
        if loopback_devices:
            print("\n✅ LOOPBACK DEVICES FOUND (System audio capture available):")
            for dev in loopback_devices:
                print(f"  - [{dev['index']}] {dev['name']}")
        else:
            print("\n⚠️  NO LOOPBACK DEVICES FOUND")
            print("\nTo capture system audio:")
            print("  1. Right-click speaker icon → Sounds → Recording tab")
            print("  2. Right-click in empty area → Show Disabled Devices")
            print("  3. Right-click 'Stereo Mix' → Enable")
        
        # Show default devices
        try:
            default_input = sd.query_devices(kind='input')
            print(f"\n🎤 Default input device: {default_input['name']}")
        except Exception as e:
            print(f"\n🎤 Default input device: Not available ({e})")
        
        try:
            default_output = sd.query_devices(kind='output')
            print(f"🔊 Default output device: {default_output['name']}")
        except Exception as e:
            print(f"🔊 Default output device: Not available ({e})")
        
        print(f"\n{'=' * 70}")
        
        return {
            'all': devices,
            'inputs': input_devices,
            'outputs': output_devices,
            'loopbacks': loopback_devices
        }
        
    except Exception as e:
        print(f"Error scanning devices: {e}")
        import traceback
        traceback.print_exc()
        return {'all': [], 'inputs': [], 'outputs': [], 'loopbacks': []}


def test_recording_devices(devices):
    """Test recording from microphone and loopback devices"""
    print("\n" + "=" * 70)
    print("RECORDING TESTS")
    print("=" * 70)
    
    # Test microphone
    if devices['inputs']:
        mic = devices['inputs'][0]
        print(f"\n🎤 Testing microphone: {mic['name']}")
        try:
            test_frames = []
            
            def callback(indata, frames, time_info, status):
                test_frames.append(indata.copy())
                if len(test_frames) >= 5:  # ~0.3 seconds at 16kHz with 1024 buffer
                    raise sd.CallbackStop()
            
            with sd.InputStream(
                device=mic['index'],
                samplerate=16000,
                channels=1,
                dtype=np.float32,
                callback=callback
            ):
                import time
                time.sleep(0.5)
            
            if test_frames:
                audio_data = np.concatenate(test_frames, axis=0)
                print(f"  ✅ Microphone test PASSED - Captured {len(audio_data)} samples")
            else:
                print("  ❌ Microphone test FAILED - No audio captured")
        except Exception as e:
            print(f"  ❌ Microphone test FAILED - {e}")
    else:
        print("\n🎤 No microphone devices found")
    
    # Test loopback
    if devices['loopbacks']:
        loopback = devices['loopbacks'][0]
        print(f"\n🔊 Testing loopback device: {loopback['name']}")
        print("  (Play some audio to test - checking for signal...)")
        try:
            test_frames = []
            
            def callback(indata, frames, time_info, status):
                test_frames.append(indata.copy())
                if len(test_frames) >= 10:  # ~0.6 seconds
                    raise sd.CallbackStop()
            
            with sd.InputStream(
                device=loopback['index'],
                samplerate=16000,
                channels=1,
                dtype=np.float32,
                callback=callback
            ):
                import time
                time.sleep(1.0)
            
            if test_frames:
                audio_data = np.concatenate(test_frames, axis=0)
                # Check if there's actual audio (not just silence)
                max_val = np.max(np.abs(audio_data))
                if max_val > 0.01:
                    print(f"  ✅ Loopback test PASSED - Captured {len(audio_data)} samples (max level: {max_val:.3f})")
                else:
                    print(f"  ⚠️  Loopback test PASSED but low signal - {len(audio_data)} samples (max level: {max_val:.3f})")
                    print("      (This is normal if no audio is playing)")
            else:
                print("  ❌ Loopback test FAILED - No audio captured")
        except Exception as e:
            print(f"  ❌ Loopback test FAILED - {e}")
    else:
        print("\n🔊 No loopback devices found - Skipping system audio test")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("PAWISCRIBE DEVICE DETECTION TEST")
    print("=" * 70)
    
    devices = scan_devices()
    
    # Ask if user wants to run recording tests
    print("\n" + "=" * 70)
    response = input("Run recording tests? (y/n): ").strip().lower()
    if response == 'y':
        test_recording_devices(devices)
    
    print("\n✅ Device detection test complete!")
