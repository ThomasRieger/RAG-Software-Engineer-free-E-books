import os

# Keep everything on this machine: ChromaDB otherwise sends anonymous usage telemetry.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
