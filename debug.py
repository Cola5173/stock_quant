"""快速启动 Web 回测界面"""
import subprocess
import sys
import os

if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    venv_streamlit = os.path.join(root, ".venv", "bin", "streamlit")

    if os.path.exists(venv_streamlit):
        cmd = [venv_streamlit, "run", os.path.join(root, "web", "app.py")]
    else:
        cmd = [sys.executable, "-m", "streamlit", "run", os.path.join(root, "web", "app.py")]

    subprocess.run(cmd)
