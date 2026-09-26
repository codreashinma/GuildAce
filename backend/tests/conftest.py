import os


os.environ["WORLD_ID_RP_ID"] = "rp_test"
os.environ["WORLD_ID_ENVIRONMENT"] = "production"
os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://test:test@127.0.0.1:5432/test"
)
