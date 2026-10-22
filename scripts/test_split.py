"""
Quick test untuk post-processing chunk splitter.
"""

from app.services.regulation_parser import parse_regulation_structure


def main():
    text = (
        "BAB I\nPENDAHULUAN\n\n"
        + ("Ini kalimat contoh yang panjang. " * 500)
        + "\n\nBAB II\nPEMBAHASAN\n\n"
        + ("Ini paragraf kedua juga panjang. " * 500)
    )

    chunks = parse_regulation_structure(text)
    print(f"Total chunks: {len(chunks)}")
    print()

    for i, c in enumerate(chunks[:15]):
        bab = c.get("bab") or "no bab"
        print(f"[{i}] {len(c['text']):>6} char — {bab}")

    if len(chunks) > 15:
        print(f"... dan {len(chunks) - 15} chunk lagi")

    print()

    # Statistik
    sizes = [len(c["text"]) for c in chunks]
    if sizes:
        print(f"Min: {min(sizes)} char")
        print(f"Max: {max(sizes)} char")
        print(f"Avg: {sum(sizes) // len(sizes)} char")


if __name__ == "__main__":
    main()