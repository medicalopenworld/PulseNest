from scipy import signal
import numpy as np

fs = 500
lowcut = 0.5
highcut = 40.0

nyq = 0.5 * fs
low = lowcut / nyq
high = highcut / nyq

# 1st order Butterworth bandpass (results in 2nd order total system - 1 SOS section)
# This is "mayor orden" than original 1st order HP (which was only 1-pole HP, total system was 1st order)
# A bandpass with 1 section is a 2nd order system (1 pole for LP, 1 pole for HP essentially)
sos_2nd = signal.butter(1, [low, high], btype='band', output='sos')

print("\nSOS sections for 2nd order total (1 section) 0.5 - 40 Hz:")
for i, s in enumerate(sos_2nd):
    print(f"Section {i}:")
    print(f"  B0: {s[0]:.10f}")
    print(f"  B1: {s[1]:.10f}")
    print(f"  B2: {s[2]:.10f}")
    print(f"  A1: {s[4]:.10f}")
    print(f"  A2: {s[5]:.10f}")

# 2nd order Butterworth bandpass (results in 4th order total system - 2 SOS sections)
sos_4th = signal.butter(2, [low, high], btype='band', output='sos')

print("\nSOS sections for 4th order total (2 sections) 0.5 - 40 Hz:")
for i, s in enumerate(sos_4th):
    print(f"Section {i}:")
    print(f"  B0: {s[0]:.10f}")
    print(f"  B1: {s[1]:.10f}")
    print(f"  B2: {s[2]:.10f}")
    print(f"  A1: {s[4]:.10f}")
    print(f"  A2: {s[5]:.10f}")
