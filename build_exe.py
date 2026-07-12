import subprocess
import sys

def build():
    print("Starting build process using PyInstaller...")
    import sys
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
        print("打包成功！生成的独立可执行文件位于 'dist' 目录中：")
        print("dist/AV_Organizer.exe")
        print("="*50)
    except Exception as e:
        print(f"打包失败: {e}")

if __name__ == '__main__':
    build()
