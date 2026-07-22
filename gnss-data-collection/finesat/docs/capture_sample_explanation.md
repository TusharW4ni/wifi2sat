### 1. Pre-Flight & Setup (The `main` block)
* **Requirement Addressed:** High-speed batching and workflow automation.
* **What it does:** The script starts by asking you for the gesture label (e.g., `swipe_left`) and how many samples you want (e.g., `100`). It then enters a `while` loop that will not stop until you successfully collect that exact number of healthy samples. 

### 2. The Capture Phase (`capture_single_sample`)
* **Requirement Addressed:** Exact 10-second data windowing and human reaction time.
* **What it does:** * It prints a 3-second countdown (`3... 2... 1... GO!`) so you know exactly when to start your gesture.
    * It opens the serial port to your u-blox receiver at `115200` baud.
    * It reads the raw RTCM byte stream into temporary memory (`io.BytesIO()`) for exactly 10 seconds (`DURATION_SEC = 10`), giving you live feedback in the terminal.

### 3. The Parsing Phase (`parse_sample`)
* **Requirement Addressed:** Extracting usable carrier phase data for FineSat math.
* **What it does:** It feeds that 10-second raw byte buffer into `pyubx2.UBXReader`. It scans the data stream for three specific things:
    * **NAV-SAT (Message ID 0x01 0x35):** It looks for satellite elevations. This is so the script knows which satellites are high in the sky (to pick a good reference satellite later).
    * **RTCM 1077 (GPS) & RTCM 1127 (BeiDou):** It extracts the `Rough Range` and `Fine Phase` data for the L1/B1 signals and calculates the exact carrier phase in meters. 
    * **Message Tallying:** It keeps a running tally of exactly how many of each message type arrived.

### 4. The Strict Health Check (The Logic Core)
* **Requirement Addressed:** Guaranteeing 100 epochs, hardware consistency, and cycle-slip-free signals.
* **What it does:** This is the most important part of the script. It runs two aggressive tests:
    * **Test A (Message Counts):** It checks the tally. Did we get at least 100 GPS messages (`n_gps >= 100`)? 100 BeiDou messages? 10 NAV-SAT messages? If your receiver glitched and only sent 99, it fails the test. This guarantees your neural network will always get the data density it expects.
    * **Test B (Cycle Slips):** It looks at the carrier phase array for every single satellite. It checks the difference between every consecutive epoch (`np.diff`). If the signal jumps by more than 50 meters instantly (`> CYCLE_SLIP_THRESH`), it flags a "cycle slip" (meaning the receiver lost lock on the satellite).
    * **Test C (Usable Count):** It requires at least 2 perfectly clean satellites (one to act as the reference, and one or more to be the targets).

### 5. The Gatekeeper (Auto-Save or Discard)
* **Requirement Addressed:** Hands-free data management and preventing corrupted datasets.
* **What it does:** * **If the sample fails the health check:** It prints a big red ❌, tells you *why* it failed (e.g., not enough messages or cycle slips), pauses for 2.5 seconds so you can read the error, and returns `False`. The `while` loop sees `False` and forces you to repeat that exact sample index. No corrupted data makes it to your hard drive.
    * **If the sample passes:** It prints a green ✅, automatically generates a timestamped filename (e.g., `samples/swipe_left-260430-165839.rtcm`), dumps the raw buffer to your hard drive, pauses for 1.5 seconds so you can reset your hands, and returns `True`. The loop increments and immediately starts the 3-second countdown for the next sample.

By the time the script says "Batch collection complete!", you have absolute mathematical certainty that your `samples/` folder contains 100 pristine, cycle-slip-free, 10-second RTCM files ready for interpolation and classifier training.