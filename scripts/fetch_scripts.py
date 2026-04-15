import subprocess
import time

scripts = [
    "scripts/get-all-5m-time-series.py",
    "scripts/get-all-1h-time-series.py",
    "scripts/get-all-6h-time-series.py",
    "scripts/get-all-24h-time-series.py",
]

processes = {}

def start_script(script):
    print(f"Starting {script}...")
    return subprocess.Popen(["python", script])

for script in scripts:
    processes[script] = start_script(script)

print("All scripts started.")

try:
    while True:
        time.sleep(5)

        for script, process in list(processes.items()):
            if process.poll() is not None:
                print(f"{script} crashed with code {process.returncode}. Restarting...")
                processes[script] = start_script(script)

except KeyboardInterrupt:
    print("\nStopping all scripts...")
    for process in processes.values():
        process.terminate()
    for process in processes.values():
        process.wait()
    print("All scripts stopped.")
