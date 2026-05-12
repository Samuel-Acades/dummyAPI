import os
import databases
import sqlalchemy
from dotenv import load_dotenv

# This looks for the .env file in your folder
load_dotenv()

# Pull the string from the .env file
DATABASE_URL = os.getenv("DATABASE_URL")

# Supabase strings sometimes start with 'postgres://' 
# but asyncpg requires 'postgresql://'
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()