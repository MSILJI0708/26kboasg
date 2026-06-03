# trigger.py
import requests
import os

TOKEN = os.environ["GITHUB_TOKEN"]
OWNER = "MSILJI0708"
REPO  = "26kboasg"
WORKFLOW = "Kboallstar.yml"

res = requests.post(
    f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json"
    },
    json={"ref": "main"}
)

print("성공" if res.status_code == 204 else f"실패: {res.status_code}")