#!/usr/bin/env python3
"""
RTP Audio Generator for PipeWire
Generates sine wave audio and sends it via RTP to PipeWire RTP source.

Requirements:
    pip install numpy

Usage:
    python rtp_generator.py
"""

import socket
import struct
import time
import numpy as np
import threading
import argparse

class RTPAudioGenerator:
    def __init__(self, target_ip="127.0.0.1", target_port=5004, 
                 sample_rate=48000, channels=2, buffer_size=64):
        # RTP Configuration
        self.target_ip = target_ip
        self.target_port = target_port
        
        # Audio Configuration
        self.sample_rate = sample_rate
        self.channels = channels
        self.buffer_size = buffer_size
        self.bytes_per_sample = 2  # S16LE = 2 bytes per sample
        
        # RTP Header fields
        self.version = 2
        self.padding = 0
        self.extension = 0
        self.cc = 0  # CSRC count
        self.marker = 0
        self.payload_type = 10  # L16 stereo 44.1kHz (try 10 instead of 96)
        self.sequence_number = 0
        self.timestamp = 0
        self.ssrc = 0x12345678  # Synchronization source identifier
        
        # Audio generation
        self.frequency = 440.0  # A4 note
        self.amplitude = 0.3    # Reduce amplitude to prevent clipping
        self.phase = 0.0
        
        # Socket setup
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Control
        self.running = False
        
    def create_rtp_header(self):
        """Create RTP header (12 bytes)"""
        # First byte: Version(2) + Padding(1) + Extension(1) + CC(4)
        first_byte = (self.version << 6) | (self.padding << 5) | (self.extension << 4) | self.cc
        
        # Second byte: Marker(1) + PT(7)
        second_byte = (self.marker << 7) | self.payload_type
        
        # Pack RTP header: 4 bytes + 4 bytes + 4 bytes = 12 bytes total
        header = struct.pack('!BBHII',
                           first_byte,
                           second_byte,
                           self.sequence_number & 0xFFFF,
                           self.timestamp & 0xFFFFFFFF,
                           self.ssrc)
        
        return header
    
    def generate_audio_buffer(self):
        """Generate audio buffer (sine wave)"""
        # Generate time array for this buffer
        samples_per_buffer = self.buffer_size
        t = np.arange(samples_per_buffer) / self.sample_rate + self.phase
        
        # Generate sine wave
        audio = self.amplitude * np.sin(2 * np.pi * self.frequency * t)
        
        # Convert to stereo if needed
        if self.channels == 2:
            # Create stereo: left channel = sine, right channel = sine * 0.7
            stereo_audio = np.zeros((samples_per_buffer, 2))
            stereo_audio[:, 0] = audio  # Left channel
            stereo_audio[:, 1] = audio * 0.7  # Right channel (slightly quieter)
            audio = stereo_audio.flatten()  # Interleave L,R,L,R...
        
        # Convert to S16LE (16-bit signed little-endian)
        audio_int16 = (audio * 32767).astype(np.int16)
        audio_bytes = audio_int16.tobytes()
        
        # Update phase for continuity
        self.phase += samples_per_buffer / self.sample_rate
        if self.phase > 1.0:
            self.phase -= 1.0
            
        return audio_bytes
    
    def debug_rtp_header(self, header):
        """Debug RTP header contents"""
        if len(header) >= 12:
            # Unpack the header
            data = struct.unpack('!BBHII', header)
            first_byte, second_byte, seq, ts, ssrc = data
            
            version = (first_byte >> 6) & 0x3
            padding = (first_byte >> 5) & 0x1
            extension = (first_byte >> 4) & 0x1
            cc = first_byte & 0xF
            marker = (second_byte >> 7) & 0x1
            pt = second_byte & 0x7F
            
            print(f"RTP Header: V={version} P={padding} X={extension} CC={cc} M={marker} PT={pt} SEQ={seq} TS={ts} SSRC={ssrc:x}")

    def send_rtp_packet(self):
        """Generate and send one RTP packet"""
        # Create RTP header
        rtp_header = self.create_rtp_header()
        
        # Generate audio payload
        audio_payload = self.generate_audio_buffer()
        
        # Combine header and payload
        rtp_packet = rtp_header + audio_payload
        
        # Debug: Print packet info every 100 packets
        if self.sequence_number % 100 == 0:
            print(f"Sending packet #{self.sequence_number}, size: {len(rtp_packet)} bytes, timestamp: {self.timestamp}")
            self.debug_rtp_header(rtp_header)
        
        # Send packet
        try:
            bytes_sent = self.socket.sendto(rtp_packet, (self.target_ip, self.target_port))
            if self.sequence_number % 100 == 0:
                print(f"Sent {bytes_sent} bytes to {self.target_ip}:{self.target_port}")
        except Exception as e:
            print(f"Error sending RTP packet: {e}")
            return False
        
        # Update RTP header fields for next packet
        self.sequence_number += 1
        self.timestamp += self.buffer_size  # Increment by samples per packet (not per channel)
        
        return True
    
    def send_sap_announcement(self):
        """Send SAP announcement for the RTP stream"""
        # SAP packet format (simplified)
        sap_header = struct.pack('!BBH', 
                                0x20,  # SAP version and flags
                                0x00,  # Authentication length
                                0x0000)  # Message ID hash
        
        # SDP (Session Description Protocol) payload
        sdp_payload = f"""v=0
o=- 123456789 123456789 IN IP4 127.0.0.1
s=Python RTP Stream
c=IN IP4 127.0.0.1
t=0 0
m=audio 5004 RTP/AVP 96
a=rtpmap:96 L16/48000/2
""".encode('utf-8')
        
        sap_packet = sap_header + sdp_payload
        
        try:
            # Send to SAP multicast address
            sap_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sap_socket.sendto(sap_packet, ("224.0.0.56", 9875))
            sap_socket.close()
            print("SAP announcement sent")
        except Exception as e:
            print(f"Failed to send SAP announcement: {e}")

    def start_streaming(self, duration=None):
        """Start RTP audio streaming"""
        print(f"Starting RTP audio stream to {self.target_ip}:{self.target_port}")
        print(f"Audio: {self.sample_rate}Hz, {self.channels} channels, buffer size: {self.buffer_size}")
        print(f"Frequency: {self.frequency}Hz")
        print("Press Ctrl+C to stop")
        
        # Send SAP announcement first
        self.send_sap_announcement()
        
        self.running = True
        packet_interval = self.buffer_size / self.sample_rate  # Time between packets
        start_time = time.time()
        packet_count = 0
        
        try:
            while self.running:
                packet_start = time.time()
                
                # Send RTP packet
                if not self.send_rtp_packet():
                    break
                    
                packet_count += 1
                
                # Calculate when to send next packet
                next_packet_time = start_time + (packet_count * packet_interval)
                sleep_time = next_packet_time - time.time()
                
                if sleep_time > 0:
                    time.sleep(sleep_time)
                elif sleep_time < -0.001:  # If we're more than 1ms behind
                    print(f"Warning: Timing drift detected ({sleep_time*1000:.1f}ms)")
                
                # Stop after duration if specified
                if duration and (time.time() - start_time) >= duration:
                    break
                    
        except KeyboardInterrupt:
            print("\nStopping RTP stream...")
        finally:
            self.running = False
            self.socket.close()
            print(f"Sent {packet_count} RTP packets")
    
    def set_frequency(self, freq):
        """Change the generated frequency"""
        self.frequency = freq
        print(f"Frequency changed to {freq}Hz")
    
    def set_amplitude(self, amp):
        """Change the amplitude (0.0 to 1.0)"""
        self.amplitude = max(0.0, min(1.0, amp))
        print(f"Amplitude changed to {self.amplitude}")

def main():
    parser = argparse.ArgumentParser(description='RTP Audio Generator for PipeWire')
    parser.add_argument('--ip', default='127.0.0.1', help='Target IP address')
    parser.add_argument('--port', type=int, default=5004, help='Target port')
    parser.add_argument('--rate', type=int, default=48000, help='Sample rate')
    parser.add_argument('--channels', type=int, default=2, help='Number of channels')
    parser.add_argument('--buffer', type=int, default=64, help='Buffer size in samples')
    parser.add_argument('--freq', type=float, default=440.0, help='Sine wave frequency')
    parser.add_argument('--duration', type=float, help='Duration in seconds (default: infinite)')
    
    args = parser.parse_args()
    
    # Create generator
    generator = RTPAudioGenerator(
        target_ip=args.ip,
        target_port=args.port,
        sample_rate=args.rate,
        channels=args.channels,
        buffer_size=args.buffer
    )
    
    generator.set_frequency(args.freq)
    
    # Start streaming
    generator.start_streaming(duration=args.duration)

if __name__ == "__main__":
    main()
