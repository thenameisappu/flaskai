import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_connection():
    
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "flaskai"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "192602@Bb"),
            port=os.getenv("DB_PORT", "5433")
        )
        return conn
    except Exception as e:
        print(f"Error connecting to the database: {e}")
        raise