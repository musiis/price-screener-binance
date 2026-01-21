"""
Quick check if price screener is running
"""
import subprocess
import sys
from datetime import datetime

# Check if process is running
result = subprocess.run(
    ['tasklist'],
    capture_output=True,
    text=True,
    shell=True
)

python_processes = [line for line in result.stdout.split('\n') if 'python' in line.lower()]

if not python_processes:
    print("❌ Screener NOT running - no Python processes found")
    sys.exit(1)

print("✓ Python process(es) running:")
for proc in python_processes:
    print(f"  {proc.strip()}")

# Try to read last few lines of log
try:
    import glob
    import os

    # Find most recent task output
    task_files = glob.glob(r'C:\Users\Samuli\AppData\Local\Temp\claude\C--Users-Samuli-testi\tasks\*.output')
    if task_files:
        latest_file = max(task_files, key=os.path.getmtime)

        with open(latest_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            last_lines = [l.strip() for l in lines[-5:] if l.strip()]

        print(f"\n✓ Last activity in {os.path.basename(latest_file)}:")
        for line in last_lines:
            print(f"  {line}")

except Exception as e:
    print(f"\n⚠ Could not read log file: {e}")

print(f"\n✓ Status checked at {datetime.now().strftime('%H:%M:%S')}")
print("✓ Screener appears to be running!")
