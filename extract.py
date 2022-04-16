import gzip
import os
import re

import pandas as pd

import experiment
import fluffi

# Constants
DATA_DIR = os.path.expanduser("~/fluffi-tools/data/")
LOCATIONS = [
    fluffi.LOCATION_FMT.format(n) for n in range(experiment.N_MIN, experiment.N_MAX + 1)
]
RUN1_DIR = os.path.join(experiment.EXP_BASE_DIR, "run1/")
RUN2_DIR = os.path.join(experiment.EXP_BASE_DIR, "run2/")
RUN1_NAMES = {
    "1021-5": "Constant / FLUFFI",
    "1021-6": "FAST / FLUFFI",
    "1021-7": "Constant / Round-Robin",
    "1021-8": "FAST / Round-Robin",
}
RUN2_NAMES = {
    "1021-5": "Constant / AFLFast",
    "1021-6": "FAST / AFLFast",
    "1021-7": "Constant / AFLFast",
    "1021-8": "FAST / AFLFast",
}
EXPERIMENTS = [
    "Constant / FLUFFI",
    "FAST / FLUFFI",
    "Constant / Round-Robin",
    "FAST / Round-Robin",
    "Constant / AFLFast",
    "FAST / AFLFast",
]


def main():
    # Initialization
    measurements = []
    covered_blocks = []
    paths = []
    crashes = []

    # Create data directory
    os.makedirs(DATA_DIR, exist_ok=True)

    # Iterate over locations
    for location in LOCATIONS:
        location1_dir = os.path.join(RUN1_DIR, location)
        location2_dir = os.path.join(RUN2_DIR, location)

        # Iterate over benchmarks
        for benchmark in experiment.BENCHMARKS:
            process(
                os.path.join(location1_dir, benchmark),
                benchmark,
                location,
                RUN1_NAMES,
                measurements,
                covered_blocks,
                paths,
                crashes,
            )
            process(
                os.path.join(location2_dir, benchmark),
                benchmark,
                location,
                RUN2_NAMES,
                measurements,
                covered_blocks,
                paths,
                crashes,
            )

    # Export measurements
    df = pd.concat(measurements, ignore_index=True)
    df = df.loc[df["cpu_time"] <= experiment.TRIAL_TIME]
    df.to_parquet(os.path.join(DATA_DIR, "measurements.parquet"))

    # Export covered blocks
    df = pd.concat(covered_blocks, ignore_index=True)
    df.to_parquet(os.path.join(DATA_DIR, "covered_blocks.parquet"))

    # Export paths
    df = pd.concat(paths, ignore_index=True)
    df.to_parquet(os.path.join(DATA_DIR, "paths.parquet"))

    # Export crashes
    df = pd.concat(crashes, ignore_index=True)
    df.to_parquet(os.path.join(DATA_DIR, "crashes.parquet"))


# Processes each benchmark
def process(
    benchmark_dir,
    benchmark,
    location,
    name_mapping,
    measurements,
    covered_blocks,
    paths,
    crashes,
):
    for filename in os.listdir(benchmark_dir):
        file_path = os.path.join(benchmark_dir, filename)
        print(file_path)
        trial = int(filename.split(".")[0])
        if name_mapping == RUN2_NAMES and location in ["1021-7", "1021-8"]:
            trial += 10

        # Read from SQL
        if filename.endswith(".sql.gz"):

            # Decompress the file
            with gzip.open(file_path, "rb") as f:
                dump = f.read()

            # Create lists
            covered_blocks_trial = []
            crashes_trial = []

            # Iterate over the lines
            for line in dump.split(b"\n"):
                if line.startswith(b"INSERT INTO `covered_blocks` VALUES"):
                    matches = re.findall(rb"\(\d+,\d+,\d+,(\d+),'(.+?)'\)", line)
                    df = pd.DataFrame(matches, columns=["offset", "time"])
                    df["offset"] = df["offset"].astype(int)
                    df["time"] = pd.to_datetime(df["time"].str.decode("utf-8"))
                    covered_blocks_trial.append(df)
                elif line.startswith(b"INSERT INTO `edge_coverage` VALUES"):
                    matches = re.findall(rb"\('(.+?)',(\d+)\)", line)
                    df = pd.DataFrame(matches, columns=["hash", "counter"])
                    df["hash"] = df["hash"].str.decode("utf-8")
                    df["counter"] = df["counter"].astype(int)
                    df["experiment"] = name_mapping[location]
                    df["benchmark"] = benchmark
                    df["trial"] = trial
                    paths.append(df)
                elif line.startswith(b"INSERT INTO `crash_descriptions` VALUES"):
                    matches = re.findall(rb"\(\d+,\d+,'(.+?)'\)", line)
                    if len(matches) > 0:
                        df = pd.DataFrame(matches, columns=["description"])
                        df["description"] = df["description"].str.decode("utf-8")
                        crashes_trial.append(df)

            # Dedup covered blocks
            df = pd.concat(covered_blocks_trial, ignore_index=True)
            df = df.sort_values("time").drop_duplicates("offset", keep="first")
            df["experiment"] = name_mapping[location]
            df["benchmark"] = benchmark
            df["trial"] = trial
            covered_blocks.append(df)

            # Dedup crashes
            if len(crashes_trial) > 0:
                df = pd.concat(crashes_trial, ignore_index=True)
                df = df.drop_duplicates("description")
                df["experiment"] = name_mapping[location]
                df["benchmark"] = benchmark
                df["trial"] = trial
                crashes.append(df)

        # Read from parquet
        if filename.endswith(".parquet"):
            df = pd.read_parquet(file_path)
            df["experiment"] = name_mapping[location]
            df["benchmark"] = benchmark
            df["trial"] = trial
            measurements.append(df)


if __name__ == "__main__":
    main()
