import os
import subprocess
import sys
import uvicorn

def main():
    # Start the Telegram bot as a background process
    subprocess.Popen([sys.executable, "bot.py"])

    # Run the FastAPI server in the foreground — this is what
    # keeps the container alive and what Railway will route traffic to
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api.main:app", host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()