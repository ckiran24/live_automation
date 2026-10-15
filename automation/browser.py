import os
import shutil


def launch_options(headed=False):
    options = {"headless": not headed}
    executable = os.environ.get("BROWSER_EXECUTABLE")
    if executable:
        options["executable_path"] = executable
    elif shutil.which("chromium"):
        options["executable_path"] = shutil.which("chromium")
    # Otherwise use the version-matched Playwright-managed Chromium.
    return options
