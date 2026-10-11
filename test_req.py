from datetime import datetime, timezone
from pathlib import Path
from shutil import rmtree

from fetch import FetchRequest, S3Fetcher


fetcher = S3Fetcher(
    cache_dir=Path("./radar_cache"),
)

request = FetchRequest(
    station="KIND",
    start_utc=datetime(
        2026, 9, 27, 14, 0,
        tzinfo=timezone.utc,
    ),
    end_utc=datetime(
        2026, 9, 27, 18, 0,
        tzinfo=timezone.utc,
    ),
)

references = fetcher.discover(request)

print(f"Discovered {len(references)} radar scan(s).")

for ref in references:
    print(ref.timestamp_utc.isoformat(), ref.source_uri)

if references:
    for ref in references:
        print(f"Downloading {ref.timestamp_utc.isoformat()}...")
        scan = fetcher.download(ref)

        print()
        print("Downloaded:")
        print(f"  Local path: {scan.local_path}")
        print(f"  Byte size:  {scan.byte_size:,}")
        print(f"  Exists:     {scan.local_path.exists()}")





# import pyart

# scan = fetcher.download(references[-1])

# radar = pyart.io.read_nexrad_archive(str(scan.local_path))

# print("File:", scan.local_path.name)
# print("Fields:", sorted(radar.fields))
# print("Sweeps:", radar.nsweeps)
# print("Rays:", radar.nrays)
# print("Gates per ray:", radar.ngates)

# assert radar.nsweeps > 0
# assert "reflectivity" in radar.fields



def cleanup():
    path = Path("./radar_cache")
    if path.exists():
        rmtree(path)

cleanup()