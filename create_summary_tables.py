import pandas as pd
from sqlalchemy import create_engine, inspect, text
from datetime import datetime
import os
import numpy as np

# --- 1. Configuration ---
# The database is located in a sibling directory called 'bigdataball'.
DB_DIRECTORY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "bigdataball")
)
DB_PATH = os.path.join(DB_DIRECTORY, "nba_fantasy_logs.db")

# Database Configuration
LOGS_TABLE_NAME = "fantasy_logs"
MAP_TEAMS_TABLE_NAME = "map_teams"
DIM_PLAYERS_TABLE_NAME = "dim_players"
AVERAGES_TABLE_NAME = "fantasy_averages"
CSV_EXPORT_DIR = os.path.join(DB_DIRECTORY, "csv_exports")
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
            "DK_POINTS": ["mean", "std"],
            "MINUTES": ["mean", "std"],
            "GAME_FPPM": ["mean", "std"],
            "USAGE": "mean",
            "GS_DK_POINTS": ["mean", "std"],
            "GS_MINUTES": ["mean", "std"],
            "GS_GAME_FPPM": ["mean", "std"],
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
            "GAME_FPPM_mean": "FPPM",
            "GAME_FPPM_std": "STDV_FPPM",
            "USAGE_mean": "USG",
            "GS_DK_POINTS_mean": "GSFPPG",
            "GS_DK_POINTS_std": "STDV_GSFPPG",
            "GS_MINUTES_mean": "GSMPG",
            "GS_MINUTES_std": "STDV_GSMPG",
            "GS_GAME_FPPM_mean": "GSFPPM",
            "GS_GAME_FPPM_std": "STDV_GSFPPM",
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
        }
        final_df = final_df.round(rounding_map).fillna(
            0
        )  # Use fillna(0) to replace any NaN from std dev on single games

        # Convert columns that should be whole numbers to integer type
        integer_columns = ["PLAYER_ID", "GP", "GS", "SALPG"]
        for col in integer_columns:
            final_df[col] = final_df[col].astype(int)

        # Save the final DataFrame to a new SQL table
        final_df.to_sql(AVERAGES_TABLE_NAME, engine, if_exists="replace", index=False)
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
    """
    print("\n--- Creating convenience views ---")

    # Define the view names
    reg_season_view_name = "vw_player_averages_regular_season"
    playoffs_view_name = "vw_player_averages_playoffs"

    # SQL statements for Regular Season View
    drop_reg_season_sql = f"DROP VIEW IF EXISTS {reg_season_view_name};"
    create_reg_season_sql = f"""
    CREATE VIEW vw_player_averages_regular_season AS
    SELECT *
    FROM {AVERAGES_TABLE_NAME}
    WHERE SEASON_TYPE = 'Regular';
    """

    # SQL for Playoffs View
    drop_playoffs_sql = f"DROP VIEW IF EXISTS {playoffs_view_name};"
    create_playoffs_sql = f"""
    CREATE VIEW vw_player_averages_playoffs AS
    SELECT *
    FROM {AVERAGES_TABLE_NAME}
    WHERE SEASON_TYPE = 'Playoffs';
    """

    # Execute each statement separately
    with engine.connect() as connection:
        connection.execute(text(drop_reg_season_sql))
        connection.execute(text(create_reg_season_sql))
        print(f"Successfully created/updated '{reg_season_view_name}'.")
        connection.execute(text(drop_playoffs_sql))
        connection.execute(text(create_playoffs_sql))
        print(f"Successfully created/updated '{playoffs_view_name}'.")
        connection.commit()
    print("--- View creation complete ---")


def export_views_to_csv():
    """
    Reads data from the database views and exports them to CSV files.
    """
    print("\n--- Exporting views to CSV ---")

    # Ensure the export directory exists
    os.makedirs(CSV_EXPORT_DIR, exist_ok=True)
    print(f"CSV files will be saved in: {CSV_EXPORT_DIR}")

    # Define view names and corresponding output file names
    views_to_export = {
        "vw_player_averages_regular_season": "player_averages_regular_season.csv",
        "vw_player_averages_playoffs": "player_averages_playoffs.csv",
    }

    # Generate a single timestamp for all files in this run
    timestamp = datetime.now().strftime("%m-%d-%Y_%H%M%S")

    try:
        for view_name, base_file_name in views_to_export.items():
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
        create_convenience_views()
        export_views_to_csv()


if __name__ == "__main__":
    run_summary_pipeline()
