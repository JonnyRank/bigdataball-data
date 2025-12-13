import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.types import Integer, Float  # <--- Added this
from datetime import datetime
import os
import numpy as np

# --- 1. Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# HARDCODED PATHS FOR MIGRATION
# Check if Google Drive (G:) exists
if os.path.exists(r"G:\My Drive"):
    BASE_DATA_PATH = r"G:\My Drive\Documents\bigdataball"
else:
    # Fallback for non-synced machines (looks for a local 'Data' folder)
    BASE_DATA_PATH = os.path.join(PROJECT_ROOT, "Data")

# Define specific paths
DB_PATH = os.path.join(BASE_DATA_PATH, "nba_fantasy_logs.db")
CSV_EXPORT_DIR = os.path.join(BASE_DATA_PATH, "csv_exports")

# Database Configuration
LOGS_TABLE_NAME = "fantasy_logs"
MAP_TEAMS_TABLE_NAME = "map_teams"
DIM_PLAYERS_TABLE_NAME = "dim_players"
AVERAGES_TABLE_NAME = "fantasy_averages"

# Initialize Engine
engine = create_engine(f"sqlite:///{DB_PATH}")


def create_fantasy_averages_table():
    """
    Loads raw fantasy logs, calculates player averages and standard deviations
    for different season types, and saves the result to a new table.
    """
    print("--- Starting summary table creation ---")
    try:
        # --- Step 0: Verify that the source tables exist ---
        inspector = inspect(engine)
        required_tables = [
            LOGS_TABLE_NAME,
            MAP_TEAMS_TABLE_NAME,
            DIM_PLAYERS_TABLE_NAME,
        ]
        available_tables = inspector.get_table_names()
        missing_tables = [tbl for tbl in required_tables if tbl not in available_tables]

        if missing_tables:
            print(
                f"\n*** ERROR: Missing required tables: {', '.join(missing_tables)} ***"
            )
            print(
                "Please ensure your data ingestion scripts have been run successfully."
            )
            if available_tables:
                print(f"Available tables are: {available_tables}")
            return False  # Stop execution

        # --- Step 1: Load and Join Data ---
        df = pd.read_sql_table(LOGS_TABLE_NAME, engine)
        map_teams_df = pd.read_sql_table(MAP_TEAMS_TABLE_NAME, engine)
        dim_players_df = pd.read_sql_table(DIM_PLAYERS_TABLE_NAME, engine)
        print(
            f"Loaded {len(df)} logs, {len(map_teams_df)} team mappings, and {len(dim_players_df)} players."
        )

        # Drop the inconsistent 'PLAYER' column from logs; we will use the canonical name from dim_players.
        df.drop(columns=["PLAYER"], inplace=True)

        # Join with dim_players on PLAYER_ID to get the canonical player name.
        df = pd.merge(
            df, dim_players_df[["PLAYER_ID", "PLAYER_NAME"]], on="PLAYER_ID", how="left"
        )
        # Rename PLAYER_NAME to PLAYER for consistency in the rest of the script.
        df.rename(columns={"PLAYER_NAME": "PLAYER"}, inplace=True)

        # Join with map_teams to get the abbreviation
        df = pd.merge(
            df,
            map_teams_df[["RAW_TEAM_NAME", "TEAM_ABBREVIATION"]],
            left_on="TEAM",
            right_on="RAW_TEAM_NAME",
            how="left",
        )
        df.drop(columns=["RAW_TEAM_NAME"], inplace=True)

        # --- Step 2: Pre-calculation & Data Cleaning ---

        # Define Season Type (Regular or Playoffs)
        conditions = [
            df["SEASON_SEGMENT"].str.contains("Regular Season|In-Season Tournament"),
            df["SEASON_SEGMENT"].str.contains("Playoffs|Play-In"),
        ]
        choices = ["Regular", "Playoffs"]
        df["SEASON_TYPE"] = np.select(conditions, choices, default=None)

        # Define Season Key
        # For Regular Season: '2023-24'
        # Use a regular expression to reliably extract the first 4-digit year.
        reg_season_mask = df["SEASON_TYPE"] == "Regular"
        start_year_series = df.loc[reg_season_mask, "SEASON_SEGMENT"].str.extract(
            r"(\d{4})", expand=False
        )

        # Convert to numeric, coercing errors to NaN (Not a Number)
        start_year_numeric = pd.to_numeric(start_year_series, errors="coerce")

        # Identify and report rows that could not be converted
        invalid_rows = start_year_numeric.isna() & reg_season_mask
        if invalid_rows.any():
            print(
                "\n--- WARNING: Could not parse year from some SEASON_SEGMENT values. ---"
            )
            print("These rows will be skipped. Problematic values:")
            print(df.loc[invalid_rows, "SEASON_SEGMENT"].unique())
            print(
                "---------------------------------------------------------------------\n"
            )

        # Calculate end year and format the SEASON_KEY, skipping invalid (NaN) rows
        end_year_series = (start_year_numeric + 1).astype(str).str.slice(2, 4)
        df.loc[reg_season_mask, "SEASON_KEY"] = (
            start_year_series + "-" + end_year_series
        )

        # For Playoffs: '2024' - Use regex to reliably get the 4-digit year
        playoff_mask = df["SEASON_TYPE"] == "Playoffs"
        df.loc[playoff_mask, "SEASON_KEY"] = df.loc[
            playoff_mask, "SEASON_SEGMENT"
        ].str.extract(r"(\d{4})", expand=False)

        # Drop any rows that don't match a season type
        df.dropna(subset=["SEASON_TYPE", "SEASON_KEY"], inplace=True)

        # --- NEW: Add columns for L30FPPM calculation ---
        # Ensure DATE column is datetime for comparison
        df["DATE"] = pd.to_datetime(df["DATE"])
        thirty_days_ago = pd.Timestamp.now().normalize() - pd.Timedelta(days=30)

        # Create conditional columns for points and minutes in the last 30 days
        # Use np.nan so these values are ignored in sums if they don't meet the condition
        df["L30_DK_POINTS"] = np.where(df["DATE"] >= thirty_days_ago, df["DK_POINTS"], np.nan)
        df["L30_MINUTES"] = np.where(df["DATE"] >= thirty_days_ago, df["MINUTES"], np.nan)

        # Calculate per-game metrics, handling division by zero
        df["GAME_FPPM"] = (
            (df["DK_POINTS"] / df["MINUTES"]).replace([np.inf, -np.inf], 0).fillna(0)
        )

        # Create conditional columns for starter-only stats (will be NULL for non-starters)
        df["GS_DK_POINTS"] = np.where(df["STARTED"] == "Y", df["DK_POINTS"], np.nan)
        df["GS_MINUTES"] = np.where(df["STARTED"] == "Y", df["MINUTES"], np.nan)
        df["GS_GAME_FPPM"] = np.where(df["STARTED"] == "Y", df["GAME_FPPM"], np.nan)

        # --- Step 3: Aggregation ---
        # Define the aggregations we want to perform.
        # Pandas' 'std' calculates sample standard deviation by default.
        aggregations = {
            "DATE": "count",  # This will be renamed to GP
            "STARTED": lambda x: (x == "Y").sum(),  # This will be renamed to GS
            "DK_SALARY": "mean",
            "DK_POINTS": ["mean", "std", "sum"],
            "MINUTES": ["mean", "std", "sum"],
            "GAME_FPPM": "std",  # Only need std dev of per-game FPPM for volatility
            "USAGE": "mean",
            "GS_DK_POINTS": ["mean", "std", "sum"],
            "GS_MINUTES": ["mean", "std", "sum"],
            "GS_GAME_FPPM": "std",  # Only need std dev of per-game FPPM for volatility
            "L30_DK_POINTS": "sum", # Sum of points in last 30 days
            "L30_MINUTES": "sum", # Sum of minutes in last 30 days
        }

        # Group by season, player, and team, then aggregate
        # Per user request: SEASON_TYPE, PLAYER, SEASON_KEY, TEAM_ABBREVIATION
        # Adding PLAYER_ID to the grouping to preserve it as a unique identifier.
        grouped = (
            df.groupby(
                [
                    "SEASON_TYPE",
                    "PLAYER_ID",
                    "PLAYER",
                    "SEASON_KEY",
                    "TEAM_ABBREVIATION",
                ]
            )
            .agg(aggregations)
            .reset_index()
        )

        # Flatten the multi-level column names (e.g., ('DK_POINTS', 'mean') -> 'DK_POINTS_mean')
        grouped.columns = ["_".join(col).strip() for col in grouped.columns.values]

        # --- Step 3.5: Calculate Correct FPPM Metrics Post-Aggregation ---
        # The correct FPPM is sum of points / sum of minutes, not the average of game-by-game FPPMs.
        # Handle division by zero for players with 0 total minutes.
        grouped["FPPM"] = (
            (grouped["DK_POINTS_sum"] / grouped["MINUTES_sum"])
            .replace([np.inf, -np.inf], 0)
            .fillna(0)
        )
        grouped["GSFPPM"] = (
            (grouped["GS_DK_POINTS_sum"] / grouped["GS_MINUTES_sum"])
            .replace([np.inf, -np.inf], 0)
            .fillna(0)
        )

        # Calculate L30FPPM
        grouped["L30FPPM"] = (
            (grouped["L30_DK_POINTS_sum"] / grouped["L30_MINUTES_sum"])
            .replace([np.inf, -np.inf], 0)
            .fillna(0)
        )

        # --- Step 4: Clean Up and Save ---
        # Rename columns to match our desired schema
        rename_map = {
            "PLAYER_ID_": "PLAYER_ID",
            "SEASON_TYPE_": "SEASON_TYPE",
            "PLAYER_": "PLAYER",
            "SEASON_KEY_": "SEASON",
            "TEAM_ABBREVIATION_": "TEAM",
            "DATE_count": "GP",
            "STARTED_<lambda>": "GS",
            "DK_SALARY_mean": "SALPG",
            "DK_POINTS_mean": "FPPG",
            "DK_POINTS_std": "STDV_FPPG",
            "MINUTES_mean": "MPG",
            "MINUTES_std": "STDV_MPG",
            "GAME_FPPM_std": "STDV_FPPM",  # This is the volatility of per-game FPPM
            "USAGE_mean": "USG",
            "GS_DK_POINTS_mean": "GSFPPG",
            "GS_DK_POINTS_std": "STDV_GSFPPG",
            "GS_MINUTES_mean": "GSMPG",
            "GS_MINUTES_std": "STDV_GSMPG",
            "GS_GAME_FPPM_std": "STDV_GSFPPM",  # This is the volatility of per-game FPPM as a starter
        }
        final_df = grouped.rename(columns=rename_map)

        # Round the columns for clean output
        rounding_map = {
            "SALPG": 0,
            "FPPG": 2,
            "STDV_FPPG": 2,
            "MPG": 1,
            "STDV_MPG": 2,
            "FPPM": 2,
            "STDV_FPPM": 2,
            "USG": 1,
            "GSFPPG": 2,
            "STDV_GSFPPG": 2,
            "GSMPG": 1,
            "STDV_GSMPG": 2,
            "GSFPPM": 2,
            "STDV_GSFPPM": 2,
            "L30FPPM": 2,
        }
        final_df = final_df.round(rounding_map).fillna(
            0
        )  # Use fillna(0) to replace any NaN from std dev on single games

        # Convert columns that should be whole numbers to integer type in the dataframe
        integer_columns = ["PLAYER_ID", "GP", "GS", "SALPG"]
        for col in integer_columns:
            final_df[col] = final_df[col].astype(int)

        # --- FIX: Explicitly define SQL types to prevent "BIGINT" (Binary) errors in Excel ---
        sql_types = {
            "PLAYER_ID": Integer(),  # Forces standard INTEGER
            "GP": Integer(),  # Forces standard INTEGER
            "GS": Integer(),  # Forces standard INTEGER
            "SALPG": Integer(),  # Forces standard INTEGER
            "FPPG": Float(),
            "STDV_FPPG": Float(),
            "MPG": Float(),
            "STDV_MPG": Float(),
            "FPPM": Float(),
            "STDV_FPPM": Float(),
            "USG": Float(),
            "GSFPPG": Float(),
            "STDV_GSFPPG": Float(),
            "GSMPG": Float(),
            "STDV_GSMPG": Float(),
            "GSFPPM": Float(),
            "STDV_GSFPPM": Float(),
            "L30FPPM": Float(),
        }

        # Save the final DataFrame to a new SQL table
        final_df.to_sql(
            AVERAGES_TABLE_NAME,
            engine,
            if_exists="replace",
            index=False,
            dtype=sql_types,  # <--- The critical fix
        )
        print(
            f"Successfully created/updated '{AVERAGES_TABLE_NAME}' table with {len(final_df)} rows."
        )
        return True

    except Exception as e:
        print(f"\n*** An error occurred: {e} ***")
        return False


def create_convenience_views():
    """
    Creates simple database views on top of the fantasy_averages table
    for easy access to regular season and playoff data.

    Returns:
        list: A list of view names that were successfully created or updated.
    """
    print("\n--- Creating convenience views ---")
    successful_views = []

    # Define the views to be created in a structured way
    views_to_create = {
        "vw_player_averages_regular_season": f"""
            CREATE VIEW {{view_name}} AS
            SELECT * FROM {AVERAGES_TABLE_NAME}
            WHERE SEASON_TYPE = 'Regular'
        """,
        "vw_player_averages_playoffs": f"""
            CREATE VIEW {{view_name}} AS
            SELECT * FROM {AVERAGES_TABLE_NAME}
            WHERE SEASON_TYPE = 'Playoffs'
        """,
    }

    for view_name, create_sql_template in views_to_create.items():
        drop_sql = f"DROP VIEW IF EXISTS {view_name}"
        # The template uses {view_name} which we format here
        create_sql = create_sql_template.format(view_name=view_name)

        try:
            # Use a dedicated transaction for each view. This isolates failures,
            # preventing an issue with one view from affecting the other.
            # The `with engine.begin()` block ensures the DROP and CREATE
            # are committed together atomically.
            with engine.begin() as connection:
                connection.execute(text(drop_sql))
                connection.execute(text(create_sql))

            print(f"Successfully created/updated '{view_name}'.")
            successful_views.append(view_name)
        except Exception as e:
            # If a single view fails, we log it and continue.
            # This makes the pipeline more resilient.
            print(f"*** Error creating view '{view_name}': {e} ***")

    print("--- View creation complete ---")
    return successful_views


def export_views_to_csv(views_to_export: list):
    """
    Reads data from the database views and exports them to CSV files.

    Args:
        views_to_export (list): A list of view names to export. This function
                                will only attempt to export views in this list.
    """
    print("\n--- Exporting views to CSV ---")

    if not views_to_export:
        print("No views were successfully created, skipping CSV export.")
        return

    # Ensure the export directory exists
    os.makedirs(CSV_EXPORT_DIR, exist_ok=True)
    print(f"CSV files will be saved in: {CSV_EXPORT_DIR}")

    # Map view names to their desired output file names
    view_file_map = {
        "vw_player_averages_regular_season": "player_averages_regular_season.csv",
        "vw_player_averages_playoffs": "player_averages_playoffs.csv",
    }

    # Generate a single timestamp for all files in this run
    timestamp = datetime.now().strftime("%m-%d-%Y_%H%M%S")

    try:
        # Iterate over the list of views that were successfully created
        for view_name in views_to_export:
            if view_name not in view_file_map:
                continue  # Skip if we don't have a file mapping for this view
            base_file_name = view_file_map[view_name]
            # Split the base filename into name and extension
            name_part, extension = os.path.splitext(base_file_name)
            # Create the new filename with the timestamp
            new_file_name = f"{name_part}_{timestamp}{extension}"

            # Construct the full path for the output file
            output_path = os.path.join(CSV_EXPORT_DIR, new_file_name)

            # Read the view data into a pandas DataFrame
            df = pd.read_sql_query(f"SELECT * FROM {view_name}", engine)

            # Save the DataFrame to a CSV file, without the pandas index
            df.to_csv(output_path, index=False)
            print(f"Successfully exported '{view_name}' to '{new_file_name}'.")

        print("--- CSV export complete ---")
    except Exception as e:
        print(f"\n*** An error occurred during CSV export: {e} ***")


def run_summary_pipeline():
    """Runs the full data summary and export pipeline."""
    if create_fantasy_averages_table():
        successful_views = create_convenience_views()
        # Only attempt to export the views that were created without errors.
        export_views_to_csv(successful_views)


if __name__ == "__main__":
    run_summary_pipeline()
