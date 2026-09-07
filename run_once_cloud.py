from google.transit import gtfs_realtime_pb2
import requests
import pandas as pd
from datetime import datetime
import zoneinfo
import os
import zipfile
import io

def download_stop_times():
    print("Downloading fresh GTFS zip...")
    zip_url = "https://unternehmen.vbb.de/gtfs"
    response = requests.get(zip_url)
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        with z.open("stop_times.txt") as f:
            return pd.read_csv(f, low_memory=False)

def run_once():
    stop_times = download_stop_times()
    stop_times["trip_id"] = stop_times["trip_id"].astype(str)

    url = "https://production.gtfsrt.vbb.de/data"
    headers = {"User-Agent": "jerry-berlin-transport-portfolio-project (learning project, contact: your_email@example.com)"}
    response = requests.get(url, headers=headers)

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

    berlin_tz = zoneinfo.ZoneInfo("Europe/Berlin")

    realtime_rows = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        trip_id = entity.trip_update.trip.trip_id
        for stu in entity.trip_update.stop_time_update:
            if not stu.HasField("arrival"):
                continue
            realtime_rows.append({
                "trip_id": trip_id,
                "stop_id": stu.stop_id,
                "realtime_unix": stu.arrival.time
            })

    realtime_df = pd.DataFrame(realtime_rows)

    merged = realtime_df.merge(stop_times[["trip_id", "stop_id", "arrival_time"]], on=["trip_id", "stop_id"], how="inner")

    merged["realtime_dt"] = merged["realtime_unix"].apply(lambda t: datetime.fromtimestamp(t, tz=berlin_tz))
    merged["trip_date"] = merged["realtime_dt"].apply(lambda d: d.date())
    merged["scheduled_dt"] = pd.to_datetime(merged["trip_date"].astype(str) + " " + merged["arrival_time"], errors="coerce")
    merged = merged.dropna(subset=["scheduled_dt"])
    merged["scheduled_dt"] = merged["scheduled_dt"].dt.tz_localize(berlin_tz)

    merged["delay_min"] = (merged["realtime_dt"] - merged["scheduled_dt"]).dt.total_seconds() / 60

    clean = merged[(merged["delay_min"] > -30) & (merged["delay_min"] < 60)].copy()
    clean["snapshot_time"] = datetime.now(berlin_tz).isoformat()

    hour_str = datetime.now(berlin_tz).strftime("%Y-%m-%d_%H")
    output_file = f"delay_log_{hour_str}.csv"
    file_exists = os.path.isfile(output_file)
    clean[["trip_id", "stop_id", "delay_min", "snapshot_time"]].to_csv(output_file, mode="a", header=not file_exists, index=False)


    print(f"[{datetime.now(berlin_tz).strftime('%H:%M:%S')}] Appended {len(clean)} records")

run_once()  # runs once per trigger — GitHub Actions handles repetition