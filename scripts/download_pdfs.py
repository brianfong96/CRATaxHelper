"""Download 6 CRA PDFs and render screenshots."""
import httpx
import pathlib
import fitz

forms = [
    ("5000-s5", "schedule5"),
    ("5000-s7", "schedule7"),
    ("5000-s8", "schedule8"),
    ("t777",    "t777"),
    ("t2209",   "t2209"),
    ("5000-d1", "worksheet-fed"),
]

screenshots_dir = pathlib.Path("app/static/forms/screenshots")
screenshots_dir.mkdir(parents=True, exist_ok=True)

for cra_id, local_name in forms:
    url = f"https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/{cra_id}/{cra_id}-fill-25e.pdf"
    print(f"Downloading {cra_id}...")
    try:
        r = httpx.get(url, follow_redirects=True, timeout=60)
        r.raise_for_status()
        dest = pathlib.Path(f"app/static/forms/{local_name}-2025.pdf")
        dest.write_bytes(r.content)
        print(f"  Saved {dest} ({len(r.content)//1024} KB)")
    except Exception as e:
        print(f"  ERROR downloading {cra_id}: {e}")
        continue

    # Render pages
    print(f"  Rendering pages for {local_name}...")
    try:
        doc = fitz.open(str(dest))
        for i, page in enumerate(doc):
            mat = fitz.Matrix(150/72, 150/72)
            pix = page.get_pixmap(matrix=mat)
            out = screenshots_dir / f"{local_name}_page{i+1}.png"
            pix.save(str(out))
            print(f"    Page {i+1} -> {out}")
        doc.close()
    except Exception as e:
        print(f"  ERROR rendering {local_name}: {e}")

print("Done.")
