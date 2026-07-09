import os
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("PROJECT_ID", "pharma-ai-dashboard")
DATASET_ID = os.getenv("DATASET_ID", "Pharma_Warehouse")
TABLE_ID = os.getenv("TABLE_ID", "medicines_master")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

FULL_DATASET_NAME = f"{PROJECT_ID}.{DATASET_ID}"
FULL_TABLE_NAME = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

TABLES = {
    "medicines_master": f"{FULL_DATASET_NAME}.medicines_master",
    "clients": f"{FULL_DATASET_NAME}.clients",
    "action_classes": f"{FULL_DATASET_NAME}.Action_classes",
    "chemical_classes": f"{FULL_DATASET_NAME}.Chemical_classes",
    "uses": f"{FULL_DATASET_NAME}.uses",
    "side_effects": f"{FULL_DATASET_NAME}.side_effects",
    "substitutes": f"{FULL_DATASET_NAME}.substitutes",
    "medicine_uses": f"{FULL_DATASET_NAME}.medicine_uses",
    "medicine_side_effects": f"{FULL_DATASET_NAME}.medicine_side_effects",
    "medicine_substitutes": f"{FULL_DATASET_NAME}.medicine_substitutes",
}

WAREHOUSE_SCHEMA = f"""
Project: {PROJECT_ID}
Dataset: {DATASET_ID}

Main table:
`{TABLES["medicines_master"]}`
Columns:
- medicine_id INT64
- client_id INT64
- medicine_name STRING
- habit_forming BOOL
- therapeutic_class_id FLOAT64
- chemical_class_id FLOAT64
- action_class_id FLOAT64

Dimension tables:
`{TABLES["clients"]}`
Columns:
- client_id INT64
- client_name STRING
- client_type STRING
- region STRING

`{TABLES["action_classes"]}`
Columns:
- action_class_id INT64
- action_class_name STRING

`{TABLES["chemical_classes"]}`
Columns:
- chemical_class_id INT64
- chemical_class_name STRING

`{TABLES["uses"]}`
Columns:
- use_id INT64
- use_name STRING

`{TABLES["side_effects"]}`
Columns:
- side_effect_id INT64
- side_effect_name STRING

`{TABLES["substitutes"]}`
Columns:
- substitute_id INT64
- substitute_name STRING

Bridge tables:
`{TABLES["medicine_uses"]}`
Columns:
- medicine_id INT64
- use_id INT64

`{TABLES["medicine_side_effects"]}`
Columns:
- medicine_id INT64
- side_effect_id INT64

`{TABLES["medicine_substitutes"]}`
Columns:
- medicine_id INT64
- substitute_id INT64

Approved joins:
- medicines_master.client_id = clients.client_id
- medicines_master.medicine_id = medicine_uses.medicine_id
- medicine_uses.use_id = uses.use_id
- medicines_master.medicine_id = medicine_side_effects.medicine_id
- medicine_side_effects.side_effect_id = side_effects.side_effect_id
- medicines_master.medicine_id = medicine_substitutes.medicine_id
- medicine_substitutes.substitute_id = substitutes.substitute_id
- SAFE_CAST(medicines_master.chemical_class_id AS INT64) = Action_classes.action_class_id
- SAFE_CAST(medicines_master.action_class_id AS INT64) = Chemical_classes.chemical_class_id

Important:
- Use fully qualified table names.
- Only generate BigQuery Standard SQL.
- Use SELECT queries only.
"""