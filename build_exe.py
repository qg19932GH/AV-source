import subprocess
import sys

# Reconfigure stdout to use utf-8 to prevent CP1252 encoding errors in Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def build():
    print("Starting build process using PyInstaller...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name=AV_Organizer",
        "--clean",
        "organizer.py"
    ]
    try:
        subprocess.run(cmd, check=True)
        print("\n" + "="*50)
        print("Build successful! The executable is located in the 'dist' directory:")
        print("dist/AV_Organizer.exe")
        print("="*50)
    except Exception as e:
        print(f"Build failed: {e}")
        # Raise or exit with non-zero to correctly report failure to GitHub Actions
        sys.exit(1)

if __name__ == '__main__':
    build()
