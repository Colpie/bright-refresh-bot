"""
Windows Task Scheduler Setup Script

Creates a scheduled task to run the job refresh bot every Saturday morning.

Usage:
    python scripts/setup_scheduler.py --install
    python scripts/setup_scheduler.py --uninstall
    python scripts/setup_scheduler.py --status
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path


TASK_NAME = "BrightStaffingJobRefresh"
TASK_DESCRIPTION = "Automated job refresh for Bright Staffing - runs every Saturday"


def get_project_root() -> Path:
    """Get project root directory"""
    return Path(__file__).parent.parent.absolute()


def get_python_path() -> str:
    """Get Python executable path"""
    venv_python = get_project_root() / "venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def create_task_xml(hour: int = 6, minute: int = 0) -> str:
    """Generate Windows Task Scheduler XML"""
    project_root = get_project_root()
    python_path = get_python_path()

    xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{TASK_DESCRIPTION}</Description>
    <Author>JobRefreshBot</Author>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2024-01-06T{hour:02d}:{minute:02d}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek>
          <Saturday />
        </DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT4H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"{python_path}"</Command>
      <Arguments>-m src.main run</Arguments>
      <WorkingDirectory>{project_root}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>'''
    return xml


def install_task(hour: int = 6, minute: int = 0, dry_run: bool = False) -> bool:
    """Install the scheduled task"""
    print(f"Installing scheduled task: {TASK_NAME}")
    print(f"Schedule: Every Saturday at {hour:02d}:{minute:02d}")

    if dry_run:
        print("  Adding --dry-run flag for safe testing")

    project_root = get_project_root()
    xml_path = project_root / "scripts" / "task_schedule.xml"

    xml_content = create_task_xml(hour, minute)
    xml_path.write_text(xml_content, encoding="utf-16")

    print(f"  Created task XML: {xml_path}")

    try:
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True,
            text=True,
        )

        result = subprocess.run(
            ["schtasks", "/create", "/tn", TASK_NAME, "/xml", str(xml_path)],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print(f"  Task '{TASK_NAME}' created successfully!")
            return True
        else:
            print(f"  Error creating task: {result.stderr}")
            return False

    except FileNotFoundError:
        print("  Error: schtasks command not found. Are you running on Windows?")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def uninstall_task() -> bool:
    """Remove the scheduled task"""
    print(f"Removing scheduled task: {TASK_NAME}")

    try:
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print(f"  Task '{TASK_NAME}' removed successfully!")
            return True
        else:
            print(f"  Error removing task: {result.stderr}")
            return False

    except Exception as e:
        print(f"  Error: {e}")
        return False


def check_status() -> None:
    """Check task status"""
    print(f"Checking status of: {TASK_NAME}")

    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME, "/v", "/fo", "list"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print("\nTask Details:")
            print("-" * 50)
            for line in result.stdout.split("\n"):
                if line.strip():
                    print(f"  {line.strip()}")
        else:
            print(f"  Task not found or error: {result.stderr}")

    except Exception as e:
        print(f"  Error: {e}")


def run_task_now() -> bool:
    """Manually trigger the task"""
    print(f"Running task: {TASK_NAME}")

    try:
        result = subprocess.run(
            ["schtasks", "/run", "/tn", TASK_NAME],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print("  Task triggered successfully!")
            return True
        else:
            print(f"  Error: {result.stderr}")
            return False

    except Exception as e:
        print(f"  Error: {e}")
        return False


def _load_schedule_defaults() -> tuple[int, int]:
    """Load hour/minute defaults from config.yaml if available."""
    try:
        sys.path.insert(0, str(get_project_root()))
        from src.config import load_config
        config = load_config()
        return config.schedule.hour, config.schedule.minute
    except Exception:
        return 6, 0


def main():
    default_hour, default_minute = _load_schedule_defaults()

    parser = argparse.ArgumentParser(
        description="Manage Windows Task Scheduler for Job Refresh Bot"
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install the scheduled task",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the scheduled task",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check task status",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Trigger the task immediately",
    )
    parser.add_argument(
        "--hour",
        type=int,
        default=default_hour,
        help=f"Hour to run (0-23, default from config: {default_hour})",
    )
    parser.add_argument(
        "--minute",
        type=int,
        default=default_minute,
        help=f"Minute to run (0-59, default from config: {default_minute})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Configure task to run in dry-run mode",
    )

    args = parser.parse_args()

    if args.install:
        install_task(args.hour, args.minute, args.dry_run)
    elif args.uninstall:
        uninstall_task()
    elif args.status:
        check_status()
    elif args.run_now:
        run_task_now()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
