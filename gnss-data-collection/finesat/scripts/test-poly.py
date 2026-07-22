import os
import sys
import numpy as np
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)  # so capture_sample (same dir) imports from any CWD
from capture_sample import parse_sample # Importing your existing parser

# Load your specific test sample
with open(os.path.join(SCRIPT_DIR, "..", "data", "samples", "push-260430-181437.rtcm"), "rb") as f:
    elevations, phases, msg_counts = parse_sample(f)

# Pick one healthy satellite from your sample (e.g., GPS_006 or whatever is valid)
target_sat = list(phases.keys())[0] 
raw_signal = np.array(phases[target_sat][:100])
t = np.linspace(0, 10, len(raw_signal))

# Fit polynomials
poly_3 = np.polyval(np.polyfit(t, raw_signal, 3), t)
poly_10 = np.polyval(np.polyfit(t, raw_signal, 10), t)

# Plot to see the difference
plt.figure(figsize=(10, 5))
plt.plot(t, raw_signal, label="Raw Carrier Phase", color='black', alpha=0.5)
plt.plot(t, poly_3, label="3rd-Order Trend (Paper)", color='blue', linewidth=2)
plt.plot(t, poly_10, label="10th-Order Trend (Yours)", color='red', linestyle='dashed', linewidth=2)
plt.legend()
plt.title(f"Polynomial Fit Comparison on {target_sat}")
plt.show()