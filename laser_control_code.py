import re
import nidaqmx
from nidaqmx.constants import Edge, AcquisitionType
import time
import threading
from tkinter import Tk, Button, Label, Entry, filedialog, Frame
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from nidaqmx.constants import LineGrouping

# default path to the configuration file
#config_file_path = r"Z:\_personalDATA\JS+LV_4F-TIRF\Software\Python_Trigger\new_configurations\2025-04-02_generated_config_bla.txt"
selected_filename = ""
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
trigger_points, block_zeit_ms = parse_config_file(selected_filename)#  (config_file_path)
# Parse configuration files for single Lasers
#blue
blue_path = r"Z:\_personalDATA\JS+LV_4F-TIRF\Software\Python_Trigger\new_configurations\Config_OnlyBlueLaser.txt"
TP_OnlyB, BT_OnlyB = parse_config_file(blue_path)
#green
green_path = r"Z:\_personalDATA\JS+LV_4F-TIRF\Software\Python_Trigger\new_configurations\Config_OnlyGreenLaser.txt"
TP_OnlyG, BT_OnlyG = parse_config_file(green_path)
#orange
orange_path = r"Z:\_personalDATA\JS+LV_4F-TIRF\Software\Python_Trigger\new_configurations\Config_OnlyOrangeLaser.txt"
TP_OnlyO, BT_OnlyO = parse_config_file(orange_path)
#red
red_path = r"Z:\_personalDATA\JS+LV_4F-TIRF\Software\Python_Trigger\new_configurations\Config_OnlyRedLaser.txt"
TP_OnlyR, BT_OnlyR = parse_config_file(red_path)

# Fallback to default if not found
if block_zeit_ms is None:
    block_zeit_ms = 200  # Default value
    
# default for triggering single lasers
Single_Laser = [(29, 129)]  # last point has to be OFF
block_zeit_ms_1Laser =130

# Print results for confirmation
print("Parsed Trigger Points:")
for device, intervals in trigger_points.items():
    print(f"{device}: {intervals}")
print(f"Block Zeit (ms): {block_zeit_ms}")

# Calculate sample rate
sample_rate = 10**6 / block_zeit_ms  # This remains unchanged
repeat_count =-1   # Default: repeat indefinitely. Change to a positive number to pause after that many blocks.
wait_time = 0       # Default: no pause. Set to a number (in seconds) to pause.
recording_time = -1 # Default: record non-stop. Change to a positive number in seconds to stop after that.

# Function to check if the current time is within any ON interval for a device
def is_device_on(current_time, intervals):
    for start, end in intervals:
        if start <= current_time < end:
            return True
    return False

# Function to generate output based on the current time
def generate_output(current_time,TPs):
    current_time = current_time % block_zeit_ms  # Repeat pattern every 200 ms

    # Check if the current time falls within the ON periods for each device
    CamOR_state = is_device_on(current_time, TPs["Cam o/r"])
    CamBG_state = is_device_on(current_time, TPs["Cam b/g"])
    laser_blue_state = is_device_on(current_time, TPs["Laser blue"])
    laser_green_state = is_device_on(current_time, TPs["Laser green"])
    laser_orange_state = is_device_on(current_time, TPs["Laser orange"])
    laser_red_state = is_device_on(current_time, TPs["Laser red"])
    shutterBlue = is_device_on(current_time, TPs["shutter in blue detection"])
    shutterOrange = is_device_on(current_time, TPs["shutter in orange detection"])
    
    # Return the states of all 5 channels as booleans (True for ON, False for OFF)
    output_states = [CamOR_state, CamBG_state, 
                     laser_blue_state, laser_green_state, 
                     laser_orange_state, laser_red_state, 
                     shutterBlue, shutterOrange]
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
                task.do_channels.add_do_chan("Dev1/port0/line0:7", line_grouping=LineGrouping.CHAN_PER_LINE)
                
                # Generate full block pattern for all channels (block_zeit_ms samples)
                # Each call to generate_output() returns a list of 8 booleans.
                pattern = [generate_output(t, trigger_points) for t in range(int(block_zeit_ms))]
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
            
            total_time += block_zeit_ms/1000 # in seconds
            block_counter += 1
            print(f"Block count: {block_counter}")
            
            # Check if a repeat count is set and reached, then pause the lasers.
            if repeat_count != -1 and block_counter >= repeat_count:
                print(f"Reached {repeat_count} blocks, pausing for {wait_time} seconds.")
                # Use a temporary off-task to turn all channels off.
                with nidaqmx.Task() as off_task:
                    off_task.do_channels.add_do_chan("Dev1/port0/line0:7", line_grouping=LineGrouping.CHAN_PER_LINE)
                    off_task.write([False, False, False, False, False, False, False, False], auto_start=True)
                    total_time += wait_time
                time.sleep(wait_time)
                block_counter = 0  # Reset the counter after waiting
            
            # Check if a recording_time is set and reached, then stop the lasers.
            if recording_time != -1 and total_time >= recording_time:
                print(f"Reached total reconding time. {total_time} seconds elapsed")
                # Use a temporary off-task to turn all channels off.
                with nidaqmx.Task() as off_task:
                    off_task.do_channels.add_do_chan("Dev1/port0/line0:7", line_grouping=LineGrouping.CHAN_PER_LINE)
                    off_task.write([False, False, False, False, False, False, False, False], auto_start=True)
            
            # Optional: a short delay to allow the hardware to fully release channels.
            time.sleep(0.01)

    except nidaqmx.errors.DaqError as e:
        print(f"DAQmx Error: {e}")

def run_blue_laser_task():
    global blue_laser_running
    block_counter = 0  # Counter for number of blocks repeated

    try:
        while blue_laser_running:
            # Create a new task for each block to ensure exclusive access
            with nidaqmx.Task() as laser_blue_task:
                # Add digital output channel for the blue laser
                laser_blue_task.do_channels.add_do_chan("Dev1/port0/line0:7", line_grouping=LineGrouping.CHAN_PER_LINE)
                
                ## Generate the full block pattern for the blue laser (block_zeit_ms samples)
                #pattern = [is_device_on(t, Single_Laser) for t in range(int(block_zeit_ms_1Laser))]
                # Each call to generate_output() returns a list of 8 booleans.
                pattern = [generate_output(t, TP_OnlyB) for t in range(int(BT_OnlyB))]
                # Transpose the pattern so that the data is organized per channel:
                # Resulting shape: 5 lists, each containing block_zeit_ms samples.
                pattern = list(map(list, zip(*pattern)))
                
                # Configure the onboard clock in FINITE mode for this block.
                # This will output block_zeit_ms samples at 1000 samples/second (1 ms per sample).
                laser_blue_task.timing.cfg_samp_clk_timing(
                    rate=1000,
                    source='',
                    active_edge=Edge.RISING,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=int(BT_OnlyG)  #samps_per_chan=int(block_zeit_ms_1Laser)
                )

                # Write the block pattern and start the task automatically.
                start_time = time.time()
                laser_blue_task.write(pattern, auto_start=True)
                # Wait until the block has been output (with a small timeout margin)
                laser_blue_task.wait_until_done(timeout=(BT_OnlyB / 1000.0) + 1)
                elapsed_time = time.time() - start_time
                print(f"blue Laser - Elapsed time for {BT_OnlyB} ms block: {elapsed_time:.3f} seconds")
                
                block_counter += 1
                print(f"blue Laser - Block count: {block_counter}")
                
                # If a repeat count is set and reached, pause the blue laser
                if repeat_count != -1 and block_counter >= repeat_count:
                    print(f"blue Laser - Reached {repeat_count} blocks, pausing for {wait_time} seconds.")
                    # Turn off the blue laser output
                    laser_blue_task.write([False, False, False, False, False, False, False, False], auto_start=True)
                    time.sleep(wait_time)
                    block_counter = 0  # Reset counter after pausing

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
                laser_green_task.do_channels.add_do_chan("Dev1/port0/line0:7", line_grouping=LineGrouping.CHAN_PER_LINE)
                
                ## Generate the full block pattern for the green laser (block_zeit_ms samples)
                #pattern = [is_device_on(t, Single_Laser) for t in range(int(block_zeit_ms_1Laser))]
                # Each call to generate_output() returns a list of 8 booleans.
                pattern = [generate_output(t, TP_OnlyG) for t in range(int(BT_OnlyG))]
                # Transpose the pattern so that the data is organized per channel:
                # Resulting shape: 5 lists, each containing block_zeit_ms samples.
                pattern = list(map(list, zip(*pattern)))
                
                # Configure the onboard clock in FINITE mode for this block.
                # This will output block_zeit_ms samples at 1000 samples/second (1 ms per sample).
                laser_green_task.timing.cfg_samp_clk_timing(
                    rate=1000,
                    source='',
                    active_edge=Edge.RISING,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=int(BT_OnlyG)  #samps_per_chan=int(block_zeit_ms_1Laser)
                )

                # Write the block pattern and start the task automatically.
                start_time = time.time()
                laser_green_task.write(pattern, auto_start=True)
                # Wait until the block has been output (with a small timeout margin)
                laser_green_task.wait_until_done(timeout=(BT_OnlyG / 1000.0) + 1)
                elapsed_time = time.time() - start_time
                print(f"Green Laser - Elapsed time for {BT_OnlyG} ms block: {elapsed_time:.3f} seconds")
                
                block_counter += 1
                print(f"Green Laser - Block count: {block_counter}")
                
                # If a repeat count is set and reached, pause the green laser
                if repeat_count != -1 and block_counter >= repeat_count:
                    print(f"Green Laser - Reached {repeat_count} blocks, pausing for {wait_time} seconds.")
                    # Turn off the green laser output
                    laser_green_task.write([False, False, False, False, False, False, False, False], auto_start=True)
                    time.sleep(wait_time)
                    block_counter = 0  # Reset counter after pausing

    except nidaqmx.errors.DaqError as e:
        print(f"DAQmx Error: {e}")

# Function to run the orange laser task independently
def run_orange_laser_task():
    global orange_laser_running
    block_counter = 0  # Counter for number of blocks repeated

    try:
        while orange_laser_running:
            # Create a new task for each block to ensure exclusive access
            with nidaqmx.Task() as laser_orange_task:
                # Add digital output channel for the orange laser
                laser_orange_task.do_channels.add_do_chan("Dev1/port0/line0:7", line_grouping=LineGrouping.CHAN_PER_LINE)
                
                ## Generate the full block pattern for the orange laser (block_zeit_ms samples)
                #pattern = [is_device_on(t, Single_Laser) for t in range(int(block_zeit_ms_1Laser))]
                # Each call to generate_output() returns a list of 8 booleans.
                pattern = [generate_output(t, TP_OnlyO) for t in range(int(BT_OnlyO))]
                # Transpose the pattern so that the data is organized per channel:
                # Resulting shape: 5 lists, each containing block_zeit_ms samples.
                pattern = list(map(list, zip(*pattern)))
                
                # Configure the onboard clock in FINITE mode for this block.
                # This will output block_zeit_ms samples at 1000 samples/second (1 ms per sample).
                laser_orange_task.timing.cfg_samp_clk_timing(
                    rate=1000,
                    source='',
                    active_edge=Edge.RISING,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=int(BT_OnlyG)  #samps_per_chan=int(block_zeit_ms_1Laser)
                )

                # Write the block pattern and start the task automatically.
                start_time = time.time()
                laser_orange_task.write(pattern, auto_start=True)
                # Wait until the block has been output (with a small timeout margin)
                laser_orange_task.wait_until_done(timeout=(BT_OnlyO / 1000.0) + 1)
                elapsed_time = time.time() - start_time
                print(f"orange Laser - Elapsed time for {BT_OnlyO} ms block: {elapsed_time:.3f} seconds")
                
                block_counter += 1
                print(f"orange Laser - Block count: {block_counter}")
                
                # If a repeat count is set and reached, pause the orange laser
                if repeat_count != -1 and block_counter >= repeat_count:
                    print(f"orange Laser - Reached {repeat_count} blocks, pausing for {wait_time} seconds.")
                    # Turn off the orange laser output
                    laser_orange_task.write([False, False, False, False, False, False, False, False], auto_start=True)
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
            # Create a new task for each block to ensure exclusive access
            with nidaqmx.Task() as laser_red_task:
                # Add digital output channel for the red laser
                laser_red_task.do_channels.add_do_chan("Dev1/port0/line0:7", line_grouping=LineGrouping.CHAN_PER_LINE)
                
                ## Generate the full block pattern for the red laser (block_zeit_ms samples)
                #pattern = [is_device_on(t, Single_Laser) for t in range(int(block_zeit_ms_1Laser))]
                # Each call to generate_output() returns a list of 8 booleans.
                pattern = [generate_output(t, TP_OnlyR) for t in range(int(BT_OnlyR))]
                # Transpose the pattern so that the data is organized per channel:
                # Resulting shape: 5 lists, each containing block_zeit_ms samples.
                pattern = list(map(list, zip(*pattern)))
                
                # Configure the onboard clock in FINITE mode for this block.
                # This will output block_zeit_ms samples at 1000 samples/second (1 ms per sample).
                laser_red_task.timing.cfg_samp_clk_timing(
                    rate=1000,
                    source='',
                    active_edge=Edge.RISING,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=int(BT_OnlyR)  #samps_per_chan=int(block_zeit_ms_1Laser)
                )

                # Write the block pattern and start the task automatically.
                start_time = time.time()
                laser_red_task.write(pattern, auto_start=True)
                # Wait until the block has been output (with a small timeout margin)
                laser_red_task.wait_until_done(timeout=(BT_OnlyR / 1000.0) + 1)
                elapsed_time = time.time() - start_time
                print(f"red Laser - Elapsed time for {BT_OnlyR} ms block: {elapsed_time:.3f} seconds")
                
                block_counter += 1
                print(f"red Laser - Block count: {block_counter}")
                
                # If a repeat count is set and reached, pause the red laser
                if repeat_count != -1 and block_counter >= repeat_count:
                    print(f"red Laser - Reached {repeat_count} blocks, pausing for {wait_time} seconds.")
                    # Turn off the red laser output
                    laser_red_task.write([False, False, False, False, False, False, False, False], auto_start=True)
                    time.sleep(wait_time)
                    block_counter = 0  # Reset counter after pausing

    except nidaqmx.errors.DaqError as e:
        print(f"DAQmx Error: {e}")

# Plotting function for trigger points
def plot_trigger_points(fig):
    ax = fig.add_subplot(111)

    y_positions = {
        "Cam o/r": 8.7,
        "Cam b/g": 7.6,
        "Laser blue": 6.5,
        "Laser green": 5.4,
        "Laser orange": 4.3,
        "Laser red": 3.2,
        "shutter in blue detection": 2.1,
        "shutter in orange detection": 1
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
    ax.set_title("Trigger Configuration ")
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

# Start the blue laser task independently
def start_blue_laser():
    global blue_laser_running
    blue_laser_running = True
    threading.Thread(target=run_blue_laser_task).start()

# Stop the green laser task independently
def stop_blue_laser():
    global blue_laser_running
    blue_laser_running = False
    
# Start the green laser task independently
def start_green_laser():
    global green_laser_running
    green_laser_running = True
    threading.Thread(target=run_green_laser_task).start()

# Stop the green laser task independently
def stop_green_laser():
    global green_laser_running
    green_laser_running = False
    
# Start the orange laser task independently
def start_orange_laser():
    global orange_laser_running
    orange_laser_running = True
    threading.Thread(target=run_orange_laser_task).start()

# Stop the orange laser task independently
def stop_orange_laser():
    global orange_laser_running
    orange_laser_running = False

def start_red_laser():
    global red_laser_running
    red_laser_running = True
    threading.Thread(target=run_red_laser_task).start()

def stop_red_laser():
    global red_laser_running
    red_laser_running = False
def update_parameters():
    global repeat_count, wait_time, repeat_count_entry, wait_time_entry, recording_time, recording_time_entry
    try:
        repeat_count = int(repeat_count_entry.get())
    except ValueError:
        repeat_count = -1  # Use -1 if input is invalid
    try:
        wait_time = float(wait_time_entry.get())
    except ValueError:
        wait_time = 0
    try:
        recording_time = float(recording_time_entry.get())
    except ValueError:
        recording_time = -1
        
# open config file
def select_file():
    global selected_filename  # Declare it as global to modify it
    selected_filename = filedialog.askopenfilename(
        title='Open a file',
        initialdir='/',
        filetypes=(('Text files', '*.txt'),)
        )
    print(f"Selected triggering file: {selected_filename}")
        
# Tkinter GUI setup
def create_gui():
    global repeat_count_entry, wait_time_entry, recording_time_entry  # Declare as global so update_parameters() can access them
    root = Tk()
    root.title("Laser Control")
    
    frame1 = Frame(root, bg='white',padx=3, pady=3)
    frame2 = Frame(root, bg='grey80',padx=3, pady=3)
    frame1.grid(row=0, sticky="ew")
    frame2.grid(row=1, sticky="ew")
    
    # open label
    open_label = Label(frame1, text="select your configuration file:", background='grey80')
    open_label.grid(column=0, row=0, sticky="ew")
    # open button
    open_button = Button(
        frame1,
        text='Open Triggering File',
        command=select_file
    )
    open_button.grid(column=1, row=0, sticky="ew")

    
    # Start button for all lasers
    start_btn = Button(frame1, text="Start All Lasers", command=start_task, padx=20, pady=10, bg="green")
    start_btn.grid(column=0, row=1, sticky="ew")#, columnspan=2)

    # Stop button for all lasers
    stop_btn = Button(frame1, text="Stop All Lasers", command=stop_task, padx=20, pady=10, bg="red")
    stop_btn.grid(column=1, row=1, sticky="ew")#, columnspan=2)
    
    # Instruction label
    label = Label(frame2, text="Control lasers individually:", padx=20, pady=20)
    label.grid(column=0, row=0, columnspan=2)

    # Start button for the blue laser only
    start_blue_btn = Button(frame2, text="Start Blue Laser", command=start_blue_laser, padx=20, pady=10, bg="dodgerblue")
    start_blue_btn.grid(column=0, row=2, sticky="ew")
    
    # Stop button for the blue laser only
    stop_blue_btn = Button(frame2, text="Stop Blue Laser", command=stop_blue_laser, padx=20, pady=10, bg="darkblue",fg="white")
    stop_blue_btn.grid(column=1, row=2, sticky="ew")    
    
    # Start button for the green laser only
    start_green_btn = Button(frame2, text="Start Green Laser", command=start_green_laser, padx=20, pady=10, bg="chartreuse2")
    start_green_btn.grid(column=0, row=3, sticky="ew")

    # Stop button for the green laser only
    stop_green_btn = Button(frame2, text="Stop Green Laser", command=stop_green_laser, padx=20, pady=10, bg="darkgreen",fg="white")
    stop_green_btn.grid(column=1, row=3, sticky="ew")
    
    # Start button for the orange laser only
    start_orange_btn = Button(frame2, text="Start Orange Laser", command=start_orange_laser, padx=20, pady=10, bg="orange")
    start_orange_btn.grid(column=2, row=2, sticky="ew")

    # Stop button for the orange laser only
    stop_orange_btn = Button(frame2, text="Stop Orange Laser", command=stop_orange_laser, padx=20, pady=10, bg="darkorange3",fg="white")
    stop_orange_btn.grid(column=3, row=2, sticky="ew")

    # Start button for the red laser only
    start_red_btn = Button(frame2, text="Start Red Laser", command=start_red_laser, padx=20, pady=10, bg="firebrick2")
    start_red_btn.grid(column=2, row=3, sticky="ew")

    # Stop button for the red laser only
    stop_red_btn = Button(frame2, text="Stop Red Laser", command=stop_red_laser, padx=20, pady=10, bg="darkred",fg="white")
    stop_red_btn.grid(column=3, row=3, sticky="ew")
    
    # New parameters: Repeat Count and Wait Time and recording Time
    # TimeSettings label
    TimeSettings_label = Label(frame1, 
                               text="The loop runs for the specified Repeat Count, waits for the set Wait Time, and then repeats this cycle until the Total Recording Time is reached. \n The Total Recording Time can also be set independently.", 
                               background='peach puff')
    TimeSettings_label.grid(column=2, row=0, columnspan=2, sticky="ew")
    # Label and Entry for Repeat Count
    repeat_count_label = Label(frame1, text="Repeat Count:", background='peach puff')
    repeat_count_label.grid(column=2, row=1, sticky="ew")
    repeat_count_entry = Entry(frame1, background='peach puff')
    repeat_count_entry.insert(0, str(repeat_count))  # Insert default value
    repeat_count_entry.grid(column=3, row=1, sticky="ew")

    # Label and Entry for Wait Time (seconds)
    wait_time_label = Label(frame1, text="Wait Time (s):", background='peach puff')
    wait_time_label.grid(column=2, row=2, sticky="ew")
    wait_time_entry = Entry(frame1,background='peach puff')
    wait_time_entry.insert(0, str(wait_time))  # Insert default value
    wait_time_entry.grid(column=3, row=2, sticky="ew")

    # Label and Entry for total recording time (seconds)
    recording_time_label = Label(frame1, text="Total Recording Time (s):", background='peach puff')
    recording_time_label.grid(column=2, row=3, sticky="ew")
    recording_time_entry = Entry(frame1,background='peach puff')
    recording_time_entry.insert(0, str(recording_time))  # Insert default value
    recording_time_entry.grid(column=3, row=3, sticky="ew")
    
    # Matplotlib figure and canvas for the graph
    fig = plt.Figure(figsize=(12, 4), dpi=100)
    plot_trigger_points(fig)  # Plot the trigger points on the graph

    canvas = FigureCanvasTkAgg(fig, master=frame1)  # A tk.DrawingArea
    canvas.draw()
    canvas.get_tk_widget().grid(row=4, column=0, columnspan=4)

    root.mainloop()

# Run the GUI
if __name__ == "__main__":
    create_gui()

