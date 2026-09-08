"""Generate an evidence master key: python -m app.core.keygen"""

from app.core.crypto import generate_master_key

if __name__ == "__main__":
    print(generate_master_key())
