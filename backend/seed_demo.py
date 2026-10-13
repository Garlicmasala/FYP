"""
seed_demo.py — seed a few DEMO uploads + a Garrick profile so the YouTube-style
feed is populated for the demo/presentation. Every record is real: the file bytes
are hashed with SHA-256 and mined into a block on the Content Chain (GCP).

Run:  python seed_demo.py   (backend must be running on 8000)
Delete any of them anytime from the Admin Panel — the on-chain record is preserved.
Reset to clean:  python reset_chains.py
"""
import io, json, random, requests

BASE = "http://127.0.0.1:8000"

def main():
    # login garrick (admin/creator)
    r = requests.post(f"{BASE}/api/identity/login",
                      json={"email": "garrick@nexushub.dev", "password": "garrick123"}).json()
    ref = r["user"]["identityRef"]
    # create Garrick's profile on Profile Chain (Azure) if not present
    if requests.get(f"{BASE}/api/profiles").json()["record_count"] == 0:
        p = requests.post(f"{BASE}/api/profile", json={
            "identityRef": ref, "username": "garrick", "displayName": "Garrick",
            "bio": "FYP student. Building NexusHub on Ethereum infrastructure.",
            "avatarColor": "#5865F2", "bannerColor": "#12182A"}).json()
        print("profile:", p.get("action"), "block", p.get("blockNumber"))

    demo = [
        {"title": "NexusHub Architecture Walkthrough",
         "desc": "How three Ethereum chains (AWS / Azure / GCP) prove ownership independently.",
         "grad": "linear-gradient(135deg,#5865F2,#7B85F5)", "dur": 512},
        {"title": "Behind the Scenes: FYP Week 1",
         "desc": "Building the upload pipeline: drag-drop, auto SHA-256, IPFS pin, chain registration.",
         "grad": "linear-gradient(135deg,#12182A,#5865F2)", "dur": 388},
        {"title": "Blockchain Verification Demo",
         "desc": "Click the Verified badge — anyone can check the on-chain record without trusting the platform.",
         "grad": "linear-gradient(135deg,#0EA5E9,#5865F2)", "dur": 264},
    ]
    for d in demo:
        size = random.randint(120000, 900000)
        blob = bytearray(b"\x00\x00\x00\x18ftypmp42") + bytes((i % 251 for i in range(size - 20)))
        files = {"file": ("demo.mp4", io.BytesIO(bytes(blob)), "video/mp4")}
        data = {"title": d["title"], "uploader": "garrick", "identity_ref": ref}
        up = requests.post(f"{BASE}/api/content/register", data=data, files=files).json()
        print("uploaded:", d["title"], "| sha", up["sha256"][:16], "| block", up["blockNumber"], "| cid", up["ipfsCid"][:16])

if __name__ == "__main__":
    main()
