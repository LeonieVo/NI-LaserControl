import re
import nidaqmx
from nidaqmx.constants import Edge, AcquisitionType
import time
import threading
from tkinter import Tk, Button, Label, Entry
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from nidaqmx.constants import LineGrouping

# Path to the configuration file
config_file_path = r"C:\Users\khatri\Desktop\Anushka_docs\saved_configurations\config_file_with_block.txt"

# Function to parse the configuration file
def parse_config_file(file_path):
    """
    Reads a configuration file and extracts trigger points and block_zeit_ms.

    Args:
        file_path (str): Path to the configuration file.

    Returns:
        tuple: (trigger_points dict, block_zeit_ms int)
    """
    trigger_points = {}
    block_zeit_ms = None

    try:
        with open(file_path, 'r') as file:
            for line in file:
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                # Extract Block Zeit (ms)
                match_zeit = re.match(r'"Block Zeit \(ms\)":(\d+)', line)
                if match_zeit:
                    block_zeit_ms = int(match_zeit.group(1))
                    continue

                # Match the format: channelX:"Device Name":start-end-start-end
                match_trigger = re.match(r'channel\d*:"(.*?)":([\d\-]+)', line)
                if match_trigger:
                    device_name = match_trigger.group(1)
                    intervals = match_trigger.group(2)

                    # Convert intervals to list of (start, end) tuples
                    interval_pairs = []
                    interval_values = [int(x) for x in intervals.split('-')]
                    for i in range(0, len(interval_values), 2):
                        interval_pairs.append((interval_values[i], interval_values[i + 1]))

                    trigger_points[device_name] = interval_pairs

    except Exception as e:
        print(f"Error reading configuration file: {e}")

    return trigger_points, block_zeit_ms

# Parse the configuration file to get trigger points and block time
trigger_points, block_zeit_ms = parse_config_file(config_file_path)

# Fallback to default if not found
if block_zeit_ms is None:
    block_zeit_ms = 200  # Default value

# Print results for confirmation
print("Parsed Trigger Points:")
for device, intervals in trigger_points.items():
    print(f"{device}: {intervals}")
print(f"Block Zeit (ms): {block_zeit_ms}")

# Calculate sample rate
sample_rate = 10**6 / block_zeit_ms  # This remains unchanged
repeat_count =-1   # Default: repeat indefinitely. Change to a positive number to pause after that many blocks.
wait_time = 0       # Default: no pause. Set to a number (in seconds) to pause.

# Function to check if the current time is within any ON interval for a device
def is_device_on(current_time, intervals):
    for start, end in intervals:
        if start <= current_time < end:
            return True
    return False

# Function to generate output based on the current time
def generate_output(current_time):
    current_time = current_time % block_zeit_ms  # Repeat pattern every 200 ms

    # Check if the current time falls within the ON periods for each device
    andor_state = is_device_on(current_time, trigger_points["Andor"])
    laser_green_state = is_device_on(current_time, trigger_points["Laser green"])
    laser_red_state = is_device_on(current_time, trigger_points["Laser red"])
    dalsa_state = is_device_on(current_time, trigger_points["Dalsa"])
    prime95b_state = is_device_on(current_time, trigger_points["Prime95B"])
    
    # Return the states of all 5 channels as booleans (True for ON, False for OFF)
    output_states = [andor_state, laser_green_state, laser_red_state, dalsa_state, prime95b_state]
    return output_states

def run_task():
    global running
    total_time = 0
    block_counter = 0  # Initialize the block repeat counter

    try:
        while running:
            # Create a single task for all channels so that they are reserved together.
            with nidaqmx.Task() as task:
                # Add channels Dev1/port0/line0 to Dev1/port0/line4 as separate channels.
                task.do_channels.add_do_chan("Dev1/port0/line0:4", line_grouping=LineGrouping.CHAN_PER_LINE)
                
                # Generate full block pattern for all channels (block_zeit_ms samples)
                # Each call to generate_output() returns a list of 5 booleans.
                pattern = [generate_output(t) for t in range(int(block_zeit_ms))]
                # Transpose the pattern so that the data is organized per channel:
                # Resulting shape: 5 lists, each containing block_zeit_ms samples.
                pattern = list(map(list, zip(*pattern)))
                
                # Configure the onboard clock in FINITE mode:
                # Rate: 1000 Hz => 1 ms per sample, and samps_per_chan equals block_zeit_ms.
                task.timing.cfg_samp_clk_timing(
                    rate=1000,
                    source='',
                    active_edge=Edge.RISING,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=int(block_zeit_ms)
                )
                
                # Write the full block to the task and start it automatically.
                start_time = time.time()
                task.write(pattern, auto_start=True)
                # Wait until the block is output (with a small timeout margin)
                task.wait_until_done(timeout=(block_zeit_ms / 1000.0) + 1)
                elapsed_time = time.time() - start_time
                print(f"Elapsed time for {block_zeit_ms} ms block: {elapsed_time:.3f} seconds")
            
            total_time += block_zeit_ms
            block_counter += 1
            print(f"Block count: {block_counter}")
            
            # Check if a repeat count is set and reached, then pause the lasers.
            if repeat_count != -1 and block_counter >= repeat_count:
                print(f"Reached {repeat_count} blocks, pausing for {wait_time} seconds.")
                # Use a temporary off-task to turn all channels off.
                with nidaqmx.Task() as off_task:
                    off_task.do_channels.add_do_chan("Dev1/port0/line0:4", line_grouping=LineGrouping.CHAN_PER_LINE)
                    off_task.write([False, False, False, False, False], auto_start=True)
                time.sleep(wait_time)
                block_counter = 0  # Reset the counter after waiting
            
            # Optional: a short delay to allow the hardware to fully release channels.
            time.sleep(0.01)

    except nidaqmx.errors.DaqError as e:
        print(f"DAQmx Error: {e}")


def run_green_laser_task():
    global green_laser_running
    block_counter = 0  # Counter for number of blocks repeated

    try:
        while green_laser_running:
            # Create a new task for each block to ensure exclusive access
            with nidaqmx.Task() as laser_green_task:
                # Add digital output channel for the green laser
                laser_green_task.do_channels.add_do_chan("Dev1/port0/line1")
                
                # Generate the full block pattern for the green laser (block_zeit_ms samples)
                pattern = [is_device_on(t, trigger_points["Laser green"]) for t in range(int(block_zeit_ms))]
                
                # Configure the onboard clock in FINITE mode for this block.
                # This will output block_zeit_ms samples at 1000 samples/second (1 ms per sample).
                laser_green_task.timing.cfg_samp_clk_timing(
                    rate=1000,
                    source='',
                    active_edge=Edge.RISING,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=int(block_zeit_ms)
                )
                
                # Write the block pattern and start the task automatically.
                start_time = time.time()
                laser_green_task.write(pattern, auto_start=True)
                # Wait until the block has been output (with a small timeout margin)
                laser_green_task.wait_until_done(timeout=(block_zeit_ms / 1000.0) + 1)
                elapsed_time = time.time() - start_time
                print(f"Green Laser - Elapsed time for {block_zeit_ms} ms block: {elapsed_time:.3f} seconds")
                
                block_counter += 1
                print(f"Green Laser - Block count: {block_counter}")
                
                # If a repeat count is set and reached, pause the green laser
                if repeat_count != -1 and block_counter >= repeat_count:
                    print(f"Green Laser - Reached {repeat_count} blocks, pausing for {wait_time} seconds.")
                    # Turn off the green laser output
                    laser_green_task.write(False, auto_start=True)
                    time.sleep(wait_time)
                    block_counter = 0  # Reset counter after pausing

    except nidaqmx.errors.DaqError as e:
        print(f"DAQmx Error: {e}")

# Function to run the red laser task independently
def run_red_laser_task():
    global red_laser_running
    block_counter = 0  # Counter for number of blocks repeated

    try:
        while red_laser_running:
            # Create a new task for the red laser channel for each block
            with nidaqmx.Task() as laser_red_task:
                # Add digital output channel for the red laser
                laser_red_task.do_channels.add_do_chan("Dev1/port0/line2")
                
                # Generate the full block pattern for the red laser (block_zeit_ms samples)
                pattern = [is_device_on(t, trigger_points["Laser red"]) for t in range(int(block_zeit_ms))]
                
                # Configure the onboard clock in FINITE mode for this block.
                # This outputs block_zeit_ms samples at 1000 samples/second (1 ms per sample).
                laser_red_task.timing.cfg_samp_clk_timing(
                    rate=1000,
                    source='',
                    active_edge=Edge.RISING,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=int(block_zeit_ms)
                )
                
                # Write the full block pattern and start the task automatically.
                start_time = time.time()
                laser_red_task.write(pattern, auto_start=True)
                # Wait until the block has been output (with a small timeout margin)
                laser_red_task.wait_until_done(timeout=(block_zeit_ms / 1000.0) + 1)
                elapsed_time = time.time() - start_time
                print(f"Red Laser - Elapsed time for {block_zeit_ms} ms block: {elapsed_time:.3f} seconds")
                
                block_counter += 1
                print(f"Red Laser - Block count: {block_counter}")
                
                # If a repeat count is set and reached, pause the red laser.
                if repeat_count != -1 and block_counter >= repeat_count:
                    print(f"Red Laser - Reached {repeat_count} blocks, pausing for {wait_time} seconds.")
                    # Turn off the red laser output
                    laser_red_task.write(False, auto_start=True)
                    time.sleep(wait_time)
                    block_counter = 0  # Reset counter after pausing

    except nidaqmx.errors.DaqError as e:
        print(f"DAQmx Error: {e}")


# Plotting function for trigger points
def plot_trigger_points(fig):
    ax = fig.add_subplot(111)

    y_positions = {
        "Andor": 5,
        "Laser green": 4,
        "Laser red": 3,
        "Dalsa": 2,
        "Prime95B": 1
    }

    time_points = [i / 1000.0 for i in range(0, block_zeit_ms + 1, 1)]  # 0 to 0.2 sec with 0.001 sec intervals

    for name, intervals in trigger_points.items():
        signal = [0] * (block_zeit_ms + 1)  # Initialize all to 0 (off)
        for start, end in intervals:
            for i in range(start, end):  # Mark the signal as on (1) for the specified intervals
                signal[i] = 1

        # Shift the signal up by the y_position of the device
        signal = [s + y_positions[name] for s in signal]

        ax.step(time_points[:block_zeit_ms], signal[:block_zeit_ms], label=name, where='post')

    ax.set_yticks(list(y_positions.values()))
    ax.set_yticklabels(list(y_positions.keys()))
    ax.set_xlabel("Time (seconds)")
    ax.set_ylabel("On/Off States")
    ax.set_title("Trigger Points for Lasers")
    ax.grid(True)
    ax.legend(loc='upper right')

def start_task():
    global running
    update_parameters()  # Update parameters from the GUI entries before starting
    running = True
    threading.Thread(target=run_task).start()  # Run the task in a separate thread

# Stop the task controlling all lasers
def stop_task():
    global running
    running = False

# Start the green laser task independently
def start_green_laser():
    global green_laser_running
    green_laser_running = True
    threading.Thread(target=run_green_laser_task).start()

# Stop the green laser task independently
def stop_green_laser():
    global green_laser_running
    green_laser_running = False

def start_red_laser():
    global red_laser_running
    red_laser_running = True
    threading.Thread(target=run_red_laser_task).start()

def stop_red_laser():
    global red_laser_running
    red_laser_running = False
def update_parameters():
    global repeat_count, wait_time, repeat_count_entry, wait_time_entry
    try:
        repeat_count = int(repeat_count_entry.get())
    except ValueError:
        repeat_count = -1  # Use -1 if input is invalid
    try:
        wait_time = float(wait_time_entry.get())
    except ValueError:
        wait_time = 0

# Tkinter GUI setup
def create_gui():
    global repeat_count_entry, wait_time_entry  # Declare as global so update_parameters() can access them
    root = Tk()
    root.title("Laser Control")

    # Start button for all lasers
    start_btn = Button(root, text="Start All Lasers", command=start_task, padx=20, pady=10, bg="green")
    start_btn.pack(pady=10)

    # Stop button for all lasers
    stop_btn = Button(root, text="Stop All Lasers", command=stop_task, padx=20, pady=10, bg="red")
    stop_btn.pack(pady=10)

    # Start button for the green laser only
    start_green_btn = Button(root, text="Start Green Laser", command=start_green_laser, padx=20, pady=10, bg="lightgreen")
    start_green_btn.pack(pady=10)

    # Stop button for the green laser only
    stop_green_btn = Button(root, text="Stop Green Laser", command=stop_green_laser, padx=20, pady=10, bg="darkgreen")
    stop_green_btn.pack(pady=10)

    # Start button for the red laser only
    start_red_btn = Button(root, text="Start Red Laser", command=start_red_laser, padx=20, pady=10, bg="lightcoral")
    start_red_btn.pack(pady=10)

    # Stop button for the red laser only
    stop_red_btn = Button(root, text="Stop Red Laser", command=stop_red_laser, padx=20, pady=10, bg="darkred")
    stop_red_btn.pack(pady=10)

    # New parameters: Repeat Count and Wait Time
    # Label and Entry for Repeat Count
    repeat_count_label = Label(root, text="Repeat Count:")
    repeat_count_label.pack(pady=5)
    repeat_count_entry = Entry(root)
    repeat_count_entry.insert(0, str(repeat_count))  # Insert default value
    repeat_count_entry.pack(pady=5)

    # Label and Entry for Wait Time (seconds)
    wait_time_label = Label(root, text="Wait Time (s):")
    wait_time_label.pack(pady=5)
    wait_time_entry = Entry(root)
    wait_time_entry.insert(0, str(wait_time))  # Insert default value
    wait_time_entry.pack(pady=5)

    # Instruction label
    label = Label(root, text="Press 'Start All' to control all lasers, or control the green and red lasers individually.", padx=20, pady=20)
    label.pack(pady=10)

    # Matplotlib figure and canvas for the graph
    fig = plt.Figure(figsize=(6, 4), dpi=100)
    plot_trigger_points(fig)  # Plot the trigger points on the graph

    canvas = FigureCanvasTkAgg(fig, master=root)  # A tk.DrawingArea
    canvas.draw()
    canvas.get_tk_widget().pack()

    root.mainloop()

# Run the GUI
if __name__ == "__main__":
    create_gui()

