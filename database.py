import os
import databases
import sqlalchemy
from dotenv import load_dotenv

# load_dotenv is fine for local, but Render will use Environment Variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Check if the URL actually exists before trying to use it
if not DATABASE_URL:
    # This will show up in your Render logs so you know exactly what happened
    print("CRITICAL ERROR: DATABASE_URL not found in environment variables!")
    # Use a dummy string so the app doesn't crash during build, 
    # but it will fail gracefully during startup
    DATABASE_URL = "postgresql://user:pass@localhost/dummy"

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()